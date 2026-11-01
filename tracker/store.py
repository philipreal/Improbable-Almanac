"""Persistent state: the event feed, which games we've processed, and site status.

Everything the website reads lives in site/data/. Bookkeeping lives in data/."""
import json
from datetime import datetime, timezone

import yaml

from . import CONFIG_DIR, DATA_DIR, ROOT
from .models import Event

STATE_DIR = ROOT / "data"


def _read(path, default):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return default


def _write(path, data, compact=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, separators=(",", ":")) if compact else json.dumps(data, indent=1, ensure_ascii=False)
    path.write_text(text, encoding="utf-8")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_config() -> dict:
    cfg = yaml.safe_load((CONFIG_DIR / "teams.yaml").read_text(encoding="utf-8")) or {}
    cfg.setdefault("teams", {})
    return cfg


def load_overrides() -> dict:
    path = CONFIG_DIR / "overrides.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else None
    return data or {}


class Store:
    def __init__(self):
        self.events_path = DATA_DIR / "events.json"
        self.state_path = STATE_DIR / "state.json"
        feed = _read(self.events_path, {"events": []})
        self.events: dict[str, dict] = {e["key"]: e for e in feed.get("events", [])}
        self._saved_events = json.dumps(feed.get("events", []), sort_keys=True)
        self.state = _read(self.state_path, {"processed": {}, "favorites": {}, "milestones": {}})
        for k in ("processed", "favorites", "milestones"):
            self.state.setdefault(k, {})
        self.new_keys: list[str] = []
        overrides = load_overrides()
        self.hidden = set(overrides.get("hide", []) or [])

    # ----- games -----
    def processed(self, league: str, game_id: str) -> bool:
        return game_id in self.state["processed"].get(league, {})

    def mark_processed(self, league: str, game_id: str, date: str):
        self.state["processed"].setdefault(league, {})[game_id] = date[:10]

    def record_favorite_game(self, league: str, abbr: str, summary: dict):
        games = self.state["favorites"].setdefault(f"{league}:{abbr}", [])
        games[:] = [g for g in games if g["id"] != summary["id"]]
        games.append(summary)
        games.sort(key=lambda g: g["date"])
        del games[:-40]

    # ----- events -----
    def add(self, ev: Event) -> bool:
        """Add or update an event. Returns True if it's new."""
        if ev.key in self.hidden:
            return False
        existing = self.events.get(ev.key)
        d = ev.to_dict()
        if existing:
            # Keep any blurb we already paid for.
            d["blurb"] = existing.get("blurb") or d["blurb"]
            d["found"] = existing.get("found", now_iso())
            self.events[ev.key] = d
            return False
        d["found"] = now_iso()
        self.events[ev.key] = d
        self.new_keys.append(ev.key)
        return True

    def remove_live(self, game_key_prefix: str):
        for k in [k for k, e in self.events.items() if e.get("live") and k.startswith(game_key_prefix)]:
            del self.events[k]

    def sorted_events(self) -> list[dict]:
        return sorted((e for k, e in self.events.items() if k not in self.hidden),
                      key=lambda e: (e["date"], e["score"]), reverse=True)

    def save(self):
        """Write only what changed, so the scheduled job commits nothing on quiet runs."""
        events = self.sorted_events()
        dumped = json.dumps(events, sort_keys=True)
        if dumped != self._saved_events:
            _write(self.events_path, {"updated": now_iso(), "events": events})
            self._saved_events = dumped
        _write(self.state_path, self.state, compact=True)


def write_json(name: str, data):
    _write(DATA_DIR / name, data)


def read_json(name: str, default=None):
    return _read(DATA_DIR / name, default)
