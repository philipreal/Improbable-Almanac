"""Scorigami tables: every final score in a league's history and how often it has happened.

Stored at site/data/scorigami/{league}.json so the website can draw the grid directly."""
import json
from datetime import datetime, timezone

from .. import DATA_DIR
from ..models import Game

SCORIGAMI_LEAGUES = ("nfl", "cfb", "mlb")


def score_key(a: int, b: int) -> str:
    hi, lo = max(a, b), min(a, b)
    return f"{hi}-{lo}"


class Table:
    def __init__(self, league: str, data: dict | None = None):
        self.league = league
        self.data = data or {"league": league, "since": None, "games": 0, "scores": {}, "recent": [],
                             "recorded": []}
        self.data.setdefault("recent", [])
        self.data.setdefault("recorded", [])
        self._recorded = set(self.data["recorded"])
        self.dirty = False

    @property
    def path(self):
        return DATA_DIR / "scorigami" / f"{self.league}.json"

    @classmethod
    def load(cls, league: str) -> "Table":
        t = cls(league)
        if t.path.exists():
            t = cls(league, json.loads(t.path.read_text(encoding="utf-8")))
        return t

    def save(self):
        self.data["recorded"] = sorted(self._recorded)
        self.data["updated"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, separators=(",", ":")), encoding="utf-8")
        self.dirty = False

    @property
    def games(self) -> int:
        return self.data["games"]

    @property
    def distinct(self) -> int:
        return len(self.data["scores"])

    def lookup(self, a: int, b: int) -> dict | None:
        return self.data["scores"].get(score_key(a, b))

    def already_recorded(self, game: Game) -> bool:
        return game.id in self._recorded

    def add(self, a: int, b: int, date: str, label: str, game_id: str | None = None):
        """Add one historical or new game."""
        if game_id is not None:
            if game_id in self._recorded:
                return
            self._recorded.add(game_id)
        self.dirty = True
        key = score_key(a, b)
        entry = self.data["scores"].get(key)
        if entry is None:
            entry = self.data["scores"][key] = {"n": 0, "first": date, "firstGame": label}
        entry["n"] += 1
        if not entry.get("last") or date >= entry["last"]:
            entry["last"], entry["lastGame"] = date, label
        if date < entry.get("first", date):
            entry["first"], entry["firstGame"] = date, label
        self.data["games"] += 1

    def record(self, game: Game) -> dict | None:
        """Record a finished game. Returns the entry as it was *before* this game."""
        if self.already_recorded(game):
            return None
        before = self.lookup(game.home_score, game.away_score)
        before = dict(before) if before else None
        day = game.date[:10]
        label = game.matchup()
        self.add(game.home_score, game.away_score, day, label, game_id=game.id)
        if before is None:
            self.data["recent"].insert(0, {"score": score_key(game.home_score, game.away_score),
                                           "date": day, "game": label, "link": game.link})
            self.data["recent"] = self.data["recent"][:50]
        return before
