"""MLB's StatsAPI: schedule, linescores and pitch-by-pitch live feeds."""
from ..http import get_json
from ..models import Game, Team

BASE = "https://statsapi.mlb.com/api"
POSTSEASON = {"F", "D", "L", "W"}
KEEP_TYPES = {"R"} | POSTSEASON


def _team(side: dict) -> Team:
    t = side.get("team", {})
    tid = str(t.get("id", ""))
    return Team(
        id=tid,
        abbr=t.get("abbreviation", t.get("teamCode", "?")).upper(),
        name=t.get("name", "?"),
        short=t.get("teamName", ""),
        logo=f"https://www.mlbstatic.com/team-logos/{tid}.svg",
    )


def _state(status: dict) -> str:
    s = status.get("abstractGameState", "Preview")
    if s == "Final":
        return "post"
    if s == "Live":
        return "in"
    return "pre"


def parse_game(g: dict) -> Game | None:
    if g.get("gameType") not in KEEP_TYPES:
        return None
    status = g.get("status", {})
    # Postponed/suspended games show up as Final-ish with odd codes; skip anything not truly played.
    if status.get("detailedState") in ("Postponed", "Cancelled") or status.get("codedGameState") in ("D", "C"):
        return None
    home, away = g["teams"]["home"], g["teams"]["away"]
    ls = g.get("linescore") or {}
    innings = ls.get("innings", [])
    state = _state(status)
    detail = status.get("detailedState", "")
    if state == "in" and ls:
        detail = f"{ls.get('inningState', '')} {ls.get('currentInningOrdinal', '')}".strip()
    elif state == "post" and ls.get("currentInning", 9) != 9:
        detail = f"Final/{ls.get('currentInning')}"
    game = Game(
        league="mlb",
        id=str(g["gamePk"]),
        date=g.get("gameDate", ""),
        state=state,
        detail=detail,
        home=_team(home),
        away=_team(away),
        home_score=int(home.get("score") or 0),
        away_score=int(away.get("score") or 0),
        period=int(ls.get("currentInning") or 0),
        home_lines=[int((i.get("home") or {}).get("runs") or 0) for i in innings],
        away_lines=[int((i.get("away") or {}).get("runs") or 0) for i in innings],
        link=f"https://www.mlb.com/gameday/{g['gamePk']}",
        season_type="postseason" if g.get("gameType") in POSTSEASON else "regular",
    )
    teams_ls = ls.get("teams") or {}
    game.extra["hits"] = {
        "home": int((teams_ls.get("home") or {}).get("hits") or 0),
        "away": int((teams_ls.get("away") or {}).get("hits") or 0),
    }
    game.extra["outs"] = ls.get("outs")
    game.extra["inning_half"] = ls.get("inningHalf")
    return game


def fetch_schedule(start: str, end: str | None = None) -> list[Game]:
    """start/end are 'YYYY-MM-DD'."""
    params = {"sportId": 1, "hydrate": "linescore,team"}
    if end and end != start:
        params.update(startDate=start, endDate=end)
    else:
        params["date"] = start
    data = get_json(f"{BASE}/v1/schedule", params=params)
    games = []
    seen = set()
    for d in data.get("dates", []):
        for g in d.get("games", []):
            # Resumed suspended games appear twice; keep the last listing.
            parsed = parse_game(g)
            if parsed and parsed.id not in seen:
                seen.add(parsed.id)
                games.append(parsed)
    return games


def fetch_feed(game_pk: str, cache: bool = False) -> dict:
    return get_json(f"{BASE}/v1.1/game/{game_pk}/feed/live", cache=cache)


def fetch_career_leaders(group: str, stat: str, limit: int = 500) -> list[dict]:
    """All-time career totals, highest first: [{id, name, value}]. StatsAPI can't filter to
    active players here, but retired players' totals never change, so diffing snapshots works."""
    data = get_json(f"{BASE}/v1/stats", params={
        "stats": "career", "group": group, "sortStat": stat, "order": "desc",
        "playerPool": "ALL", "limit": limit, "sportId": 1,
    })
    out = []
    for split in (data.get("stats") or [{}])[0].get("splits", []):
        out.append({
            "id": str(split["player"]["id"]),
            "name": split["player"]["fullName"],
            "value": int(split["stat"].get(stat) or 0),
        })
    return out
