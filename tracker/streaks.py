"""Streaks that run across games: hitting streaks, scoreless-inning runs, team win streaks.

Each finished game updates running counters kept in store.state["streaks"]. When a counter crosses
a milestone, ties a record or breaks one, the streak gets a feed card that grows (and is eventually
marked as ended) along with it. Long active streaks also get a live "streak watch" banner whenever
that player's team is playing."""
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from .models import TIERS, Event, Game

log = logging.getLogger(__name__)

POSTSEASON_TYPES = {"F", "D", "L", "W"}


@dataclass(frozen=True)
class Spec:
    kind: str
    league: str
    noun: str  # "hitting streak"
    unit: str  # "games" | "innings" | "wins" | "losses"
    levels: tuple  # ((value, tier), ...) highest first; innings are counted in outs
    watch: int  # live banner from this value on
    record: int | None = None
    record_holder: str = ""  # "Joe DiMaggio, 1941"
    record_fact: str = ""


SPECS = {(s.league, s.kind): s for s in [
    Spec("hit", "mlb", "hitting streak", "games", ((40, "legendary"), (35, "epic"), (30, "rare")), 25,
         56, "Joe DiMaggio, 1941", "Joe DiMaggio's 56-game hitting streak (1941) is the MLB record."),
    Spec("onbase", "mlb", "on-base streak", "games", ((60, "legendary"), (50, "epic"), (40, "rare")), 35,
         84, "Ted Williams, 1949", "Ted Williams reached base in 84 straight games in 1949, the MLB record."),
    Spec("scoreless", "mlb", "scoreless-innings streak", "innings",
         ((45 * 3, "legendary"), (35 * 3, "epic"), (28 * 3, "rare")), 25 * 3,
         59 * 3, "Orel Hershiser, 1988", "Orel Hershiser's 59 straight scoreless innings (1988) is the MLB record."),
    Spec("post-relief", "mlb", "postseason scoreless streak in relief", "innings",
         ((16 * 3, "legendary"), (13 * 3, "epic"), (10 * 3, "rare")), 10 * 3,
         16 * 3, "Andrew Miller, 2016",
         "Andrew Miller's 16 straight scoreless postseason innings in relief (2016) stood as the record until 2026."),
    Spec("team-win", "mlb", "winning streak", "wins", ((20, "legendary"), (16, "epic"), (13, "rare")), 10),
    Spec("team-loss", "mlb", "losing streak", "losses", ((20, "legendary"), (16, "epic"), (13, "rare")), 10),
    Spec("team-win", "nba", "winning streak", "wins", ((25, "legendary"), (18, "epic"), (14, "rare")), 11,
         33, "1971-72 Lakers", "The 1971-72 Lakers' 33 straight wins is the NBA record."),
    Spec("team-loss", "nba", "losing streak", "losses", ((22, "legendary"), (18, "epic"), (15, "rare")), 12),
]}
# Team streaks only count games from the current season's start; earlier games in our data are a
# partial season, and a streak counted from the middle would be understated.
TEAM_SEASON_START = {"mlb": "2026-03-01", "nba": "2026-10-01"}


def fmt(spec: Spec, value: int) -> str:
    if spec.unit != "innings":
        return f"{value}"
    whole, thirds = divmod(value, 3)
    return f"{whole}{['', '⅓', '⅔'][thirds]}"


class Tracker:
    """Wraps store.state['streaks']: {"active": {key: streak}, "applied": {league: [game ids]}}."""

    def __init__(self, store):
        self.store = store
        st = store.state.setdefault("streaks", {})
        self.active = st.setdefault("active", {})
        self._applied_lists = st.setdefault("applied", {})
        self.applied = {lg: set(ids) for lg, ids in self._applied_lists.items()}
        self.current_year = str(datetime.now(timezone.utc).year)

    # ---- bookkeeping ----
    def _bump(self, league, kind, entity, name, team, amount, game: Game):
        key = f"{league}:{kind}:{entity}"
        s = self.active.get(key)
        if not s or s["value"] == 0:
            s = self.active[key] = {"league": league, "kind": kind, "entity": entity, "value": 0,
                                    "start": game.date[:10], "start_game": game.id}
        s.update(name=name, team=team.abbr, logo=team.logo, last=game.date, last_link=game.link,
                 last_matchup=game.matchup())
        s["value"] += amount
        self._publish(key, s, ended=False)

    def _reset(self, league, kind, entity):
        key = f"{league}:{kind}:{entity}"
        s = self.active.get(key)
        if s and s["value"] > 0:
            self._publish(key, s, ended=True)
            del self.active[key]

    def _publish(self, key, s, ended: bool):
        spec = SPECS[(s["league"], s["kind"])]
        v = s["value"]
        tier = next((t for minimum, t in spec.levels if v >= minimum), None)
        broke = spec.record is not None and v > spec.record
        tied = spec.record is not None and v == spec.record
        if tied or broke:
            tier = "legendary"
        if not tier or s["last"][:4] < self.current_year:
            return  # nothing notable, or a leftover from a past postseason
        n, unit = fmt(spec, v), spec.unit
        who = s["name"]
        if broke and not ended:
            title = f"Record! {who}: {n} {unit}, the longest {spec.noun} ever"
        elif tied and not ended:
            title = f"{who} ties the record: {n}-{unit[:-1] if unit.endswith('s') else unit} {spec.noun}"
        elif ended:
            title = f"{who}'s {spec.noun} ends at {n} {unit}"
        else:
            title = f"{who}'s {spec.noun} reaches {n} {unit}"
        detail = f"{who} ({s['team']}): {n} {unit} since {s['start']}"
        detail += f", most recently in {s['last_matchup']}." if not ended else ". It ended in the next game."
        facts = [spec.record_fact] if spec.record_fact else []
        if spec.record and not (tied or broke):
            facts.append(f"{fmt(spec, spec.record - v)} more {unit} would tie {spec.record_holder}.")
        ev = Event(
            key=f"{s['league']}:streak:{s['kind']}:{s['entity']}:{s['start_game']}", league=s["league"],
            category="never-before" if broke else "milestone", tier=tier, title=title, detail=detail,
            date=s["last"], link=s["last_link"], matchup=s["last_matchup"], teams=[s["team"]],
            team_logos=[s["logo"]], players=[who] if not s["kind"].startswith("team") else [], facts=facts,
        )
        existing = self.store.events.get(ev.key)
        if existing and TIERS[existing["tier"]] > TIERS[ev.tier] and not ended:
            ev.tier = existing["tier"]
        self.store.add(ev)

    def save(self):
        for lg, ids in self.applied.items():
            self._applied_lists[lg] = sorted(ids)

    # ---- per game ----
    def update(self, game: Game):
        if not game.final or game.league not in TEAM_SEASON_START:
            return
        done = self.applied.setdefault(game.league, set())
        if game.id in done:
            return
        done.add(game.id)
        if game.date[:10] >= TEAM_SEASON_START[game.league] and game.winner:
            for team in (game.home, game.away):
                won = team.id == game.winner.id
                self._bump(game.league, "team-win" if won else "team-loss", team.abbr, team.name, team, 1, game)
                self._reset(game.league, "team-loss" if won else "team-win", team.abbr)
        if game.league == "mlb" and game.data:
            self._mlb_players(game)

    def _mlb_players(self, game: Game):
        gd = game.data.get("gameData", {})
        ld = game.data.get("liveData", {})
        gtype = gd.get("game", {}).get("type")
        box = ld.get("boxscore", {}).get("teams", {})
        side_team = {"home": game.home, "away": game.away}
        if gtype == "R":
            for side, b in box.items():
                team = side_team[side]
                for pid in b.get("batters", []):
                    p = b["players"].get(f"ID{pid}", {})
                    bat = (p.get("stats") or {}).get("batting") or {}
                    if not bat:
                        continue
                    name = p.get("person", {}).get("fullName", "?")
                    hits, ab = bat.get("hits", 0), bat.get("atBats", 0)
                    reached = hits + bat.get("baseOnBalls", 0) + bat.get("hitByPitch", 0)
                    if hits:
                        self._bump("mlb", "hit", str(pid), name, team, 1, game)
                    elif ab or bat.get("sacFlies", 0):
                        self._reset("mlb", "hit", str(pid))
                    if reached:
                        self._bump("mlb", "onbase", str(pid), name, team, 1, game)
                    elif bat.get("plateAppearances", 0):
                        self._reset("mlb", "onbase", str(pid))
        if gtype == "R":
            self._scoreless(game, "scoreless", box, side_team, relief_only=False)
        elif gtype in POSTSEASON_TYPES:
            self._scoreless(game, "post-relief", box, side_team, relief_only=True)

    def _scoreless(self, game, kind, box, side_team, relief_only):
        starters = {b["pitchers"][0] for b in box.values() if b.get("pitchers")}
        team_of = {pid: side_team[side] for side, b in box.items() for pid in b.get("pitchers", [])}
        names = {pid: b["players"].get(f"ID{pid}", {}).get("person", {}).get("fullName", "?")
                 for b in box.values() for pid in b.get("pitchers", [])}
        # Official scoreless streaks count only innings in which the pitcher wasn't charged with a
        # run: outs earlier in an inning that a run later spoils don't count, and neither do outs
        # after the run in the inning where the previous streak ended. So settle each half-inning
        # as a whole.
        halves: dict[tuple, dict] = {}
        prev_outs, prev_half = 0, None
        for play in game.data["liveData"]["plays"]["allPlays"]:
            half = (play["about"]["inning"], play["about"]["halfInning"])
            if half != prev_half:
                prev_outs, prev_half = 0, half
            h = halves.setdefault(half, {"outs": {}, "runs": set()})
            pitcher = play["matchup"]["pitcher"]["id"]
            for r in play.get("runners", []):
                if r.get("movement", {}).get("end") == "score":
                    # A run in any outing ends the streak, even for relief-only records, where
                    # innings as a starter just don't count toward the total.
                    h["runs"].add((r.get("details", {}).get("responsiblePitcher") or {}).get("id", pitcher))
            outs = (play.get("count") or {}).get("outs", prev_outs)
            if outs > prev_outs and pitcher in team_of:
                h["outs"][pitcher] = h["outs"].get(pitcher, 0) + outs - prev_outs
            prev_outs = outs
        for h in halves.values():
            for pid in h["runs"]:
                self._reset("mlb", kind, str(pid))
            for pid, outs in h["outs"].items():
                if pid in h["runs"] or (relief_only and pid in starters):
                    continue
                self._bump("mlb", kind, str(pid), names.get(pid, "?"), team_of[pid], outs, game)

    # ---- live ----
    def watch(self, playing: dict[str, set[str]]) -> list[dict]:
        """Banners for long active streaks whose team plays today. playing: league -> team abbrs."""
        out = []
        for s in self.active.values():
            spec = SPECS[(s["league"], s["kind"])]
            if s["value"] < spec.watch or s["team"] not in playing.get(s["league"], set()):
                continue
            target = f" Record: {fmt(spec, spec.record)} ({spec.record_holder})." if spec.record else ""
            out.append({
                "kind": "streak-watch", "league": s["league"], "link": s["last_link"], "teams": [s["team"]],
                "logos": [s["logo"]],
                "title": f"Streak watch: {s['name']}, {fmt(spec, s['value'])} {spec.unit}",
                "detail": f"{spec.noun.capitalize()} on the line today.{target}",
            })
        return out
