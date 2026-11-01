"""The poll loop: fetch games, run detectors on newly finished ones, publish JSON for the site."""
import logging
import time
from datetime import date, datetime, timedelta, timezone

import requests

from . import loader
from .detectors.base import Context, run_detectors
from .models import LEAGUE_NAMES, LEAGUES, TIERS, Game
from .rarity.facts import load_facts
from .rarity.scorigami import SCORIGAMI_LEAGUES, Table, score_key
from .sources import espn, mlb_statsapi
from .store import Store, load_config, now_iso, read_json, write_json

log = logging.getLogger(__name__)


def build_context(cfg: dict) -> Context:
    return Context(
        scorigami={lg: Table.load(lg) for lg in SCORIGAMI_LEAGUES},
        facts=load_facts(),
        favorite_teams={lg: {a.upper() for a in (cfg["teams"].get(lg) or [])} for lg in LEAGUES},
    )


def favorite_side(game: Game, ctx: Context):
    favs = ctx.favorite_teams.get(game.league, set())
    return [t for t in (game.away, game.home) if t.abbr.upper() in favs]


def game_summary(game: Game, team) -> dict:
    opp = game.other(team)
    us, them = game.score_of(team), game.score_of(opp)
    return {
        "id": game.id, "date": game.date, "link": game.link, "state": game.state, "detail": game.detail,
        "home": team.id == game.home.id, "opp": opp.abbr, "opp_name": opp.name, "opp_logo": opp.logo,
        "us": us, "them": them,
        "result": ("W" if us > them else "L" if us < them else "T") if game.final else "",
    }


def process_game(game: Game, store: Store, ctx: Context) -> list:
    """Run detectors on a finished game and record it."""
    if game.season_type == "other":  # preseason, exhibitions, all-star games
        store.mark_processed(game.league, game.id, game.date)
        return []
    try:
        loader.load_detail(game)
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            log.warning("no detail available for %s %s; skipping", game.league, game.id)
            store.mark_processed(game.league, game.id, game.date)
            return []
        raise
    events = run_detectors(game, ctx)
    # On a re-scan, drop this game's old detector events (scorigami can't be re-detected: the
    # table already counted the game, so that event is kept).
    prefix = f"{game.league}:{game.id}:"
    for k in [k for k in store.events if k.startswith(prefix) and ":scorigami" not in k]:
        del store.events[k]
    favs = favorite_side(game, ctx)
    for ev in events:
        store.add(ev)
    store.streaks().update(game)
    for team in favs:
        s = game_summary(game, team)
        s["events"] = [e.key for e in events]
        store.record_favorite_game(game.league, team.abbr, s)
        meta = store.state.setdefault("favorite_meta", {})
        meta[f"{game.league}:{team.abbr}"] = {"name": team.name, "short": team.short, "logo": team.logo,
                                             "color": team.color}
    store.remove_live(f"{game.league}:{game.id}:")
    store.mark_processed(game.league, game.id, game.date)
    return events


def live_alerts(games: list[Game], ctx: Context) -> list[dict]:
    """In-progress drama worth a banner: no-hitters in progress, scorigami watch, Dad's teams live."""
    alerts = []
    for g in games:
        if g.state != "in":
            continue
        favs = favorite_side(g, ctx)
        if g.league == "mlb":
            hits = g.extra.get("hits", {})
            for side, opp_side in (("home", "away"), ("away", "home")):
                # Pitching side `side` has held `opp_side` hitless.
                if hits.get(opp_side, 1) == 0 and g.period >= 6:
                    team = g.home if side == "home" else g.away
                    alerts.append({
                        "kind": "no-hitter", "league": "mlb", "link": g.link, "teams": [team.abbr],
                        "logos": [team.logo],
                        "title": f"No-hitter in progress: {team.name}",
                        "detail": f"{g.matchup()} · {g.detail}. The {(g.away if side == 'home' else g.home).name} "
                                  f"have no hits.",
                    })
        if g.league in ("nfl", "cfb") and g.period >= 4:
            table = ctx.scorigami.get(g.league)
            if table and table.games and table.lookup(g.home_score, g.away_score) is None:
                alerts.append({
                    "kind": "scorigami-watch", "league": g.league, "link": g.link,
                    "teams": [g.away.abbr, g.home.abbr], "logos": [g.away.logo, g.home.logo],
                    "title": f"Scorigami watch: {score_key(g.home_score, g.away_score).replace('-', '–')}",
                    "detail": f"If {g.matchup()} ends like this ({g.detail}), it's a score that's never "
                              f"happened in {LEAGUE_NAMES[g.league]} history.",
                })
        for team in favs:
            alerts.append({
                "kind": "favorite-live", "league": g.league, "link": g.link, "teams": [team.abbr],
                "logos": [team.logo], "title": f"{team.short or team.name} are playing",
                "detail": f"{g.matchup()} · {g.detail}",
            })
    return alerts


def next_games(games: list[Game], ctx: Context) -> dict:
    out = {}
    for g in sorted(games, key=lambda g: g.date):
        if g.state != "pre":
            continue
        for team in favorite_side(g, ctx):
            key = f"{g.league}:{team.abbr}"
            if key not in out:
                out[key] = game_summary(g, team)
    return out


def publish_teams(store: Store, cfg: dict, upcoming: dict, live_games: list[Game], ctx: Context):
    teams = []
    meta = store.state.get("favorite_meta", {})
    live_by_team = {}
    for g in live_games:
        if g.state == "in":
            for t in favorite_side(g, ctx):
                live_by_team[f"{g.league}:{t.abbr}"] = game_summary(g, t)
    for league in LEAGUES:
        for abbr in cfg["teams"].get(league) or []:
            key = f"{league}:{abbr.upper()}"
            games = store.state["favorites"].get(key, [])
            m = meta.get(key, {})
            season_events = [k for gm in games for k in gm.get("events", [])]
            teams.append({
                "key": key, "league": league, "abbr": abbr.upper(), "name": m.get("name", abbr),
                "short": m.get("short", ""), "logo": m.get("logo", ""), "color": m.get("color", ""),
                "recent": list(reversed(games[-6:])), "live": live_by_team.get(key),
                "next": upcoming.get(key), "event_count": len(season_events),
            })
    write_json("teams.json", {"updated": now_iso(), "name": cfg.get("name", "Dad"),
                              "site_title": cfg.get("site_title", "The Improbable Almanac"), "teams": teams})


def write_blurbs(store: Store, limit: int = 60):
    from .ai import blurbs
    pending = [store.events[k] for k in store.new_keys
               if k in store.events and not store.events[k].get("blurb")
               and TIERS.get(store.events[k]["tier"], 0) >= TIERS["rare"]]
    if pending:
        blurbs.fill(pending[:limit])


def save_tables(ctx: Context):
    for t in ctx.scorigami.values():
        if t.games and t.dirty:
            t.save()


def poll():
    started = time.time()
    cfg = load_config()
    ctx = build_context(cfg)
    store = Store()
    status = read_json("status.json", {}) or {}
    sources = status.setdefault("sources", {})
    all_current: list[Game] = []
    for league in LEAGUES:
        try:
            games = loader.list_current(league)
            if league == "nba":  # late West Coast games finish after ESPN rolls to the next day
                yday = (datetime.now(timezone.utc) - timedelta(hours=14)).date()
                games += [g for g in loader.list_games("nba", yday) if g.id not in {x.id for x in games}]
            all_current += games
            new = 0
            for g in sorted(games, key=lambda g: g.date):
                if g.final and not store.processed(league, g.id):
                    process_game(g, store, ctx)
                    new += 1
            sources[league] = {"ok": True, "checked": now_iso(), "games": len(games), "new_finals": new}
        except Exception as e:
            log.exception("poll failed for %s", league)
            sources[league] = {"ok": False, "checked": now_iso(), "error": str(e)[:200]}
    playing: dict[str, set[str]] = {}
    for g in all_current:
        if g.state in ("pre", "in") and g.date[:10] <= now_iso()[:10]:
            playing.setdefault(g.league, set()).update({g.home.abbr, g.away.abbr})
    alerts = live_alerts(all_current, ctx) + store.streaks().watch(playing)
    write_json("live.json", {"updated": now_iso(), "alerts": alerts})
    publish_teams(store, cfg, next_games(all_current, ctx), all_current, ctx)
    try:
        write_blurbs(store)
    except Exception:
        log.exception("blurb writing failed")
    save_tables(ctx)
    store.save()
    status.update(last_poll=now_iso(), poll_seconds=round(time.time() - started, 1),
                  new_events=len(store.new_keys))
    write_json("status.json", status)
    log.info("poll done: %d new events in %.0fs", len(store.new_keys), time.time() - started)
    return store.new_keys


def daily_milestones():
    from . import milestones
    store = Store()
    for ev in milestones.check(store.state["milestones"]):
        store.add(ev)
    store.save()
    return store.new_keys


# ---------- backfill ----------

def _season_games(league: str, since: date, until: date) -> list[Game]:
    games: dict[str, Game] = {}
    if league in ("nfl", "cfb"):
        year = since.year
        for seasontype, weeks in ((2, range(0, 18)), (3, range(1, 6))):
            for week in weeks:
                try:
                    for g in espn.fetch_scoreboard(league, str(year), week=week, seasontype=seasontype):
                        games[g.id] = g
                except Exception:
                    log.warning("no %s week %s/%s", league, seasontype, week)
    elif league == "mlb":
        cur = since
        while cur <= until:
            stop = min(until, cur + timedelta(days=13))
            for g in mlb_statsapi.fetch_schedule(cur.isoformat(), stop.isoformat()):
                games[g.id] = g
            cur = stop + timedelta(days=1)
    else:
        cur = since
        while cur <= until:
            for g in espn.fetch_scoreboard(league, f"{cur:%Y%m%d}"):
                games[g.id] = g
            cur += timedelta(days=1)
    lo, hi = since.isoformat(), (until + timedelta(days=1)).isoformat()
    return sorted((g for g in games.values() if g.final and lo <= g.date[:10] <= hi), key=lambda g: g.date)


def backfill(since: date, until: date, leagues=LEAGUES, blurbs: bool = False, force: bool = False):
    """Scan finished games in a date range. force=True re-runs detectors on games already
    processed (to pick up detector fixes); scorigami tables never double count."""
    cfg = load_config()
    ctx = build_context(cfg)
    store = Store()
    for league in leagues:
        games = _season_games(league, since, until)
        log.info("%s: %d finished games to check", league, len(games))
        for i, g in enumerate(games):
            if store.processed(league, g.id) and not force:
                continue
            try:
                process_game(g, store, ctx)
            except Exception:
                log.exception("failed on %s %s", league, g.id)
            if i % 100 == 0:
                log.info("  %s %d/%d (%d events so far)", league, i, len(games), len(store.events))
                save_tables(ctx)
                store.save()
    publish_teams(store, cfg, {}, [], ctx)
    if blurbs:
        write_blurbs(store, limit=10_000)
    save_tables(ctx)
    store.save()
    return store.new_keys


# ---------- news ----------

def news(dry_run: bool = False):
    from .ai.triage import triage
    from .sources.news import collect
    store = Store()
    seen = store.state.setdefault("news_seen", [])
    seen_set = set(seen)
    items = [it for it in collect() if it["id"] not in seen_set]
    cutoff = (datetime.now(timezone.utc) - timedelta(days=4)).isoformat()
    covered = [e for e in store.sorted_events() if e["date"] >= cutoff]
    kept = triage(items, covered) if items else []
    for ev in kept:
        if dry_run:
            print(f"[{ev.tier}] {ev.sport} | {ev.title} — {ev.source_name}\n    {ev.detail}\n    {ev.link}")
        else:
            store.add(ev)
    log.info("news: %d new items checked, %d kept", len(items), len(kept))
    if not dry_run:
        seen.extend(it["id"] for it in items)
        del seen[:-3000]
        store.save()
        status = read_json("status.json", {}) or {}
        status.update(last_news=now_iso(), news_checked=len(items), news_kept=len(kept))
        write_json("status.json", status)
    return kept


def fill_missing_blurbs():
    from .ai import blurbs
    store = Store()
    pending = [e for e in store.events.values()
               if not e.get("blurb") and TIERS.get(e["tier"], 0) >= TIERS["rare"]]
    blurbs.fill(pending)
    store.save()


def rebuild_streaks(today: date | None = None):
    """Recount every streak from scratch: the last three postseasons (so postseason streaks that
    started earlier are right), then this MLB season and this NBA season, in date order."""
    today = today or date.today()
    store = Store()
    store.state["streaks"] = {}
    for k in [k for k in store.events if ":streak:" in k]:
        del store.events[k]
    tracker = store.streaks()
    games: list[Game] = []
    for year in range(today.year - 3, today.year):
        games += [g for g in mlb_statsapi.fetch_schedule(f"{year}-09-25", f"{year}-11-15")
                  if g.final and g.season_type == "postseason"]
    games += _season_games("mlb", date(today.year, 3, 1), today)
    games += _season_games("nba", date(today.year, 10, 1), today)
    games.sort(key=lambda g: g.date)
    log.info("rebuilding streaks from %d games", len(games))
    for i, g in enumerate(games):
        if g.league == "mlb":
            loader.load_detail(g, cache=True)
        tracker.update(g)
        if i % 500 == 0:
            log.info("  %d/%d", i, len(games))
    store.save()
    return tracker
