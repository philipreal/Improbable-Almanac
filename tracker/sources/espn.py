"""ESPN's public (unofficial) site API for NFL, college football and NBA.

Everything ESPN-specific lives here so a format change only needs fixing in one place."""
import re
from datetime import date

from ..http import get_json
from ..models import Game, Team

BASE = "https://site.api.espn.com/apis/site/v2/sports"
PATHS = {
    "nfl": ("football", "nfl"),
    "cfb": ("football", "college-football"),
    "nba": ("basketball", "nba"),
}
WEB = {"nfl": "nfl", "cfb": "college-football", "nba": "nba"}
SEASON_TYPES = {1: "other", 2: "regular", 3: "postseason", 4: "other"}
# ESPN conference ids for FBS conferences (plus FBS independents).
FBS_CONFERENCES = {"1", "4", "5", "8", "9", "12", "15", "17", "18", "37", "151"}


def scoreboard_url(league: str) -> str:
    sport, slug = PATHS[league]
    return f"{BASE}/{sport}/{slug}/scoreboard"


def fetch_scoreboard(league: str, dates: str | None = None, week: int | None = None,
                     seasontype: int | None = None) -> list[Game]:
    """dates: 'YYYYMMDD' or a year (ESPN no longer accepts date ranges).
    Football can instead be fetched by year + seasontype (2 regular, 3 post) + week.
    No arguments means ESPN's current slate."""
    params = {"limit": 500}  # ESPN silently falls back to 25 results above ~500
    if league == "cfb":
        params["groups"] = 80  # FBS
    if dates:
        params["dates"] = dates
    if week is not None:
        params["week"] = week
    if seasontype is not None:
        params["seasontype"] = seasontype
    data = get_json(scoreboard_url(league), params=params)
    return [g for g in (parse_event(league, e) for e in data.get("events", [])) if g]


def fetch_summary(league: str, game_id: str, cache: bool = False) -> dict:
    sport, slug = PATHS[league]
    return get_json(f"{BASE}/{sport}/{slug}/summary", params={"event": game_id}, cache=cache)


def _team(c: dict) -> Team:
    t = c.get("team", {})
    rank = (c.get("curatedRank") or {}).get("current")
    return Team(
        id=str(t.get("id", "")),
        abbr=t.get("abbreviation", "?"),
        name=t.get("displayName", t.get("name", "?")),
        short=t.get("shortDisplayName", ""),
        logo=t.get("logo", "") or (t.get("logos") or [{}])[0].get("href", ""),
        color=t.get("color", ""),
        rank=rank if rank and rank <= 25 else None,
        conference_id=str(t["conferenceId"]) if t.get("conferenceId") else None,
    )


def _lines(c: dict) -> list[int]:
    return [int(float(x.get("value", 0) or 0)) for x in c.get("linescores", [])]


def parse_line(details: str | None, game: Game) -> tuple[str | None, float | None]:
    """'JAX -2.5' -> ('JAX', 2.5). Pick'em lines return (None, 0.0)."""
    if not details:
        return None, None
    if details.strip().upper() in ("EVEN", "PK", "PICK"):
        return None, 0.0
    m = re.match(r"^\s*([A-Z0-9&]+)\s+-?(\d+(?:\.\d+)?)", details)
    if not m:
        return None, None
    abbr = m.group(1)
    if abbr not in (game.home.abbr, game.away.abbr):
        return None, None
    return abbr, float(m.group(2))


def parse_event(league: str, e: dict) -> Game | None:
    comps = e.get("competitions") or []
    if not comps:
        return None
    c = comps[0]
    competitors = c.get("competitors", [])
    home = next((x for x in competitors if x.get("homeAway") == "home"), None)
    away = next((x for x in competitors if x.get("homeAway") == "away"), None)
    if not home or not away:
        return None
    st = c.get("status") or e.get("status") or {}
    stype = st.get("type", {})
    season_type = SEASON_TYPES.get((e.get("season") or {}).get("type"), "regular")
    g = Game(
        league=league,
        id=str(e["id"]),
        date=e.get("date", ""),
        state=stype.get("state", "pre"),
        detail=stype.get("shortDetail", ""),
        home=_team(home),
        away=_team(away),
        home_score=int(float(home.get("score") or 0)),
        away_score=int(float(away.get("score") or 0)),
        period=int(st.get("period") or 0),
        home_lines=_lines(home),
        away_lines=_lines(away),
        link=f"https://www.espn.com/{WEB[league]}/game/_/gameId/{e['id']}",
        season_type=season_type,
    )
    odds = (c.get("odds") or [{}])[0]
    g.favorite, g.spread = parse_line(odds.get("details"), g)
    return g


def attach_summary(game: Game, summary: dict) -> Game:
    """Fill in details that only the game summary has (closing line, final linescores)."""
    game.data = summary
    if game.spread is None:
        for pc in summary.get("pickcenter", []) or []:
            fav, spread = parse_line(pc.get("details"), game)
            if spread is not None:
                game.favorite, game.spread = fav, spread
                break
    return game


# ---------- helpers for detectors ----------

def football_plays(summary: dict) -> list[dict]:
    """All plays in order, flattened from drives."""
    drives = summary.get("drives") or {}
    plays = []
    for d in drives.get("previous", []) or []:
        for p in d.get("plays", []) or []:
            p = dict(p)
            p["_drive_team"] = str((d.get("team") or {}).get("id", ""))
            plays.append(p)
    cur = drives.get("current")
    if cur:
        for p in cur.get("plays", []) or []:
            p = dict(p)
            p["_drive_team"] = str((cur.get("team") or {}).get("id", ""))
            if not any(q.get("id") == p.get("id") for q in plays):
                plays.append(p)
    return plays


def box_players(summary: dict) -> list[dict]:
    """Per-player stat lines from the box score:
    [{team_id, name, id, category, stats: {key: value}}] (one row per player per stat category)."""
    rows = []
    for team_block in (summary.get("boxscore") or {}).get("players", []) or []:
        team_id = str((team_block.get("team") or {}).get("id", ""))
        for cat in team_block.get("statistics", []) or []:
            keys = cat.get("keys") or []
            for a in cat.get("athletes", []) or []:
                ath = a.get("athlete") or {}
                stats = dict(zip(keys, a.get("stats") or []))
                if not stats:
                    continue
                rows.append({
                    "team_id": team_id,
                    "id": str(ath.get("id", "")),
                    "name": ath.get("displayName", "?"),
                    "position": (ath.get("position") or {}).get("abbreviation", ""),
                    "category": cat.get("name", ""),
                    "stats": stats,
                    "dnp": a.get("didNotPlay", False),
                })
    return rows


def num(v) -> float:
    """Parse ESPN stat strings like '12', '--', '+5'."""
    try:
        return float(str(v).replace("+", ""))
    except (TypeError, ValueError):
        return 0.0


def made_att(v) -> tuple[int, int]:
    """'7-12' -> (7, 12)."""
    try:
        a, b = str(v).split("-")
        return int(a), int(b)
    except ValueError:
        return 0, 0


def daterange_chunks(start: date, end: date, days: int = 7):
    """Yield 'YYYYMMDD-YYYYMMDD' strings covering [start, end]."""
    from datetime import timedelta
    cur = start
    while cur <= end:
        stop = min(end, cur + timedelta(days=days - 1))
        yield f"{cur:%Y%m%d}-{stop:%Y%m%d}"
        cur = stop + timedelta(days=1)
