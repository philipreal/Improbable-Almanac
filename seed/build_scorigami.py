"""Build the all-time scorigami tables (every final score through the end of the 2025 seasons).

The live tracker adds 2026 games on top, in order, so new scorigamis are detected as they happen.

    python -m seed.build_scorigami nfl cfb mlb

Sources:
  NFL 1920-1998  FiveThirtyEight's nfl-elo-game dataset (CC BY 4.0)
  NFL 1999-2025  nflverse games.csv
  College        ESPN's scoreboard archive (FBS-involved games)
  MLB            MLB StatsAPI schedules (regular season + postseason)
"""
import csv
import io
import logging
import sys
from datetime import date

from tracker.http import get_json, get_text
from tracker.rarity.scorigami import Table

log = logging.getLogger("seed")
CUTOFF_SEASON = 2025  # last completed season in the seed; 2026 is tracked live


def build_nfl() -> Table:
    t = Table("nfl")
    elo = get_text("https://raw.githubusercontent.com/fivethirtyeight/nfl-elo-game/master/data/nfl_games.csv")
    for r in csv.DictReader(io.StringIO(elo)):
        if int(r["season"]) > 1998 or not r["score1"]:
            continue
        a, b = int(float(r["score1"])), int(float(r["score2"]))
        t.add(a, b, r["date"], f"{r['team2']} {b}, {r['team1']} {a}")
    games = get_text("https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv")
    for r in csv.DictReader(io.StringIO(games)):
        if int(r["season"]) > CUTOFF_SEASON or r["home_score"] in ("", "NA"):
            continue
        h, a = int(r["home_score"]), int(r["away_score"])
        t.add(h, a, r["gameday"], f"{r['away_team']} {a}, {r['home_team']} {h}")
    t.data["since"] = 1920
    t.data["source"] = "FiveThirtyEight (1920–1998, incl. AFL 1960–69), nflverse (1999–2025), live ESPN data (2026–)"
    return t


def _espn_cfb_events(params: dict) -> list[dict]:
    params = {"groups": 80, "limit": 500, **params}  # above ~500 recent seasons silently return 25
    data = get_json("https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard",
                    params=params, cache=True)
    return data.get("events", [])


def build_cfb() -> Table:
    t = Table("cfb")
    seen = set()
    first_year = None

    def take(events, before: str | None = None):
        nonlocal first_year
        for e in events:
            if not e.get("id") or not e.get("competitions") or e["id"] in seen:
                continue
            c = e["competitions"][0]
            if not c["status"]["type"].get("completed"):
                continue
            if before and e["date"] >= before:
                continue
            comp = {x["homeAway"]: x for x in c["competitors"]}
            if "home" not in comp or "away" not in comp:
                continue
            h, a = int(float(comp["home"].get("score") or 0)), int(float(comp["away"].get("score") or 0))
            seen.add(e["id"])
            label = f"{comp['away']['team'].get('abbreviation', '?')} {a}, {comp['home']['team'].get('abbreviation', '?')} {h}"
            t.add(h, a, e["date"][:10], label)
            yr = int(e["date"][:4])
            first_year = yr if first_year is None else min(first_year, yr)

    for year in range(1869, CUTOFF_SEASON + 2):
        before = f"{CUTOFF_SEASON + 1}-07-01" if year == CUTOFF_SEASON + 1 else None
        # Older seasons need a big limit to come back whole; recent ones need a small one.
        events = _espn_cfb_events({"dates": year, "limit": 1000})
        if len(events) <= 25:
            events = _espn_cfb_events({"dates": year})
        truncated = year >= 2001 and len(events) >= 500
        if len(events) > 25 or year < 2001:
            take(events, before)
        if truncated:
            # The calendar-year query hit ESPN's cap: also walk the season week by week.
            n0 = len(seen)
            # The previous season's bowls are played in January of this calendar year.
            take(_espn_cfb_events({"dates": year - 1, "seasontype": 3, "week": 1}), before)
            if year <= CUTOFF_SEASON:
                for week in range(0, 18):
                    take(_espn_cfb_events({"dates": year, "seasontype": 2, "week": week}), before)
                take(_espn_cfb_events({"dates": year, "seasontype": 3, "week": 1}), before)
            log.info("cfb %s: %d from year query + %d more from weekly queries", year, len(events), len(seen) - n0)
        elif events:
            log.info("cfb %s: %d events", year, len(events))
    t.data["since"] = first_year
    t.data["source"] = "ESPN college football archive (games involving FBS programs), live ESPN data (2026–)"
    return t


def build_mlb() -> Table:
    t = Table("mlb")
    first_year = None
    fields = "dates,games,gameDate,gameType,status,codedGameState,teams,away,home,score,team,abbreviation,name,gamePk"
    for year in range(1876, CUTOFF_SEASON + 1):
        data = get_json("https://statsapi.mlb.com/api/v1/schedule", cache=True, params={
            "sportId": 1, "season": year, "gameType": "R,F,D,L,W", "fields": fields, "hydrate": "team"})
        seen = set()
        n = 0
        for d in data.get("dates", []):
            for g in d.get("games", []):
                if g["gamePk"] in seen or g.get("status", {}).get("codedGameState") != "F":
                    continue
                home, away = g["teams"]["home"], g["teams"]["away"]
                if "score" not in home or "score" not in away:
                    continue
                seen.add(g["gamePk"])
                h, a = int(home["score"]), int(away["score"])
                ha = home["team"].get("abbreviation") or home["team"].get("name", "?")
                aa = away["team"].get("abbreviation") or away["team"].get("name", "?")
                t.add(h, a, g["gameDate"][:10], f"{aa} {a}, {ha} {h}")
                n += 1
        if n:
            first_year = first_year or year
            log.info("mlb %s: %d games", year, n)
    t.data["since"] = first_year
    t.data["source"] = "MLB StatsAPI schedules (regular season + postseason), live data (2026–)"
    return t


BUILDERS = {"nfl": build_nfl, "cfb": build_cfb, "mlb": build_mlb}

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    for league in sys.argv[1:] or BUILDERS:
        table = BUILDERS[league]()
        table.data["seeded_through"] = CUTOFF_SEASON
        table.data["seeded_on"] = date.today().isoformat()
        table.save()
        print(f"{league}: {table.games:,} games, {table.distinct:,} distinct scores since {table.data['since']}")
