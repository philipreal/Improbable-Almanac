"""NFL and college football oddities, read from ESPN play-by-play and box scores."""
import re

from ..models import Game, make_event
from ..sources.espn import FBS_CONFERENCES, box_players, football_plays, num
from .base import detector, tiered

YARDS_RE = re.compile(
    r"(\d+)\s*Y(?:d|ar)d?s?\s+(pass|Rush|Run|Interception Return|Fumble Return|Kickoff Return|Punt Return|"
    r"Missed Field Goal Return|Blocked Field Goal Return|Field Goal Return|Blocked Punt Return|Return)",
    re.I,
)
FG_RE = re.compile(r"(\d+)\s*Y(?:d|ar)d?s?\s+Field Goal", re.I)
DEF_TD_TYPES = ("interception return touchdown", "fumble return touchdown", "blocked punt touchdown",
                "punt return touchdown", "kickoff return touchdown", "blocked field goal touchdown",
                "missed field goal return touchdown", "defensive touchdown")


def scoring_plays(game: Game) -> list[dict]:
    """ESPN scoringPlays with per-play point deltas added: _da / _dh (away/home)."""
    out, pa, ph = [], 0, 0
    for p in (game.data or {}).get("scoringPlays", []) or []:
        a, h = int(p.get("awayScore") or 0), int(p.get("homeScore") or 0)
        p = dict(p)
        p["_da"], p["_dh"] = a - pa, h - ph
        p["_type"] = ((p.get("type") or {}).get("text") or "").lower()
        p["_team"] = str((p.get("team") or {}).get("id", ""))
        pa, ph = a, h
        out.append(p)
    return out


def team_of(game: Game, p: dict):
    """The team that scored on this play (judged by the score change, which is more reliable
    than ESPN's team tag on returns)."""
    if p.get("_dh", 0) > p.get("_da", 0):
        return game.home
    if p.get("_da", 0) > p.get("_dh", 0):
        return game.away
    return game.team_by_id(p.get("_team", "")) or game.home


def who(text: str) -> str:
    """'Jason Myers 55 Yd Field Goal' -> 'Jason Myers'."""
    m = re.match(r"^\s*([A-Z][\w.'\-]*(?:\s+[A-Z][\w.'\-]*){0,3}?)\s+\d", text or "")
    return m.group(1) if m else ""


@detector("nfl", "cfb")
def safety_oddities(game: Game, ctx):
    """One-point safeties and defensive two-point returns: the rarest scores in football."""
    for p in scoring_plays(game):
        text = p.get("text", "")
        da, dh = p["_da"], p["_dh"]
        low = text.lower()
        both_scored = da > 0 and dh > 0
        if re.search(r"\bsafety\b", low) and (da == 1 or dh == 1 or (both_scored and 1 in (da % 6, dh % 6))):
            yield make_event(
                game, "one-point-safety", category="oddity", tier="legendary",
                title="A one-point safety!",
                detail=f"One of football's rarest plays: a safety on a try worth a single point. Play: {text.strip()}",
                facts=ctx.fact(f"{game.league}-one-point-safety"), unique=str(p.get("id", "")),
            )
            continue
        is_def2 = re.search(r"defensive (two|2)[- ]?(point|pt)", low) or (
            both_scored and 2 in (da, dh) and max(da, dh) >= 6)
        if is_def2:
            yield make_event(
                game, "defensive-2pt", category="oddity", tier="epic",
                title="Defensive two-point return",
                detail=f"A failed try was returned the length of the field for 2 points. Play: {text.strip()}",
                facts=ctx.fact(f"{game.league}-defensive-2pt"), unique=str(p.get("id", "")),
            )


@detector("nfl", "cfb")
def kick_six(game: Game, ctx):
    plays = scoring_plays(game)
    for i, p in enumerate(plays):
        t, text = p["_type"], p.get("text", "")
        if not (("field goal" in t and any(w in t for w in ("return", "blocked", "missed"))) or
                re.search(r"field goal return", text, re.I)):
            continue
        if max(p["_da"], p["_dh"]) < 6:
            continue
        team = team_of(game, p)
        last = i == len(plays) - 1
        period = (p.get("period") or {}).get("number", 0)
        walkoff = last and period >= 4 and game.winner and game.winner.id == team.id and \
            (p.get("clock") or {}).get("displayValue") in ("0:00", "0:01", "0:02", "0:03")
        yield make_event(
            game, "kick-six", category="oddity", tier="legendary" if walkoff else "epic",
            title="Walk-off kick-six!" if walkoff else "Kick-six: field goal returned for a touchdown",
            detail=f"{team.name} took a field-goal try back for six. {text.strip()}",
            teams=[team, game.other(team)], players=[who(text)] if who(text) else [],
            facts=ctx.fact("kick-six"), unique=str(p.get("id", "")),
        )


@detector("nfl", "cfb")
def fair_catch_kick(game: Game, ctx):
    for p in football_plays(game.data or {}):
        text = p.get("text") or ""
        if "fair catch kick" not in text.lower():
            continue
        good = re.search(r"\bgood\b", text, re.I) and not re.search(r"no good", text, re.I)
        yield make_event(
            game, "fair-catch-kick", category="oddity", tier="legendary" if good else "epic",
            title="Fair-catch kick " + ("— and it's good!" if good else "attempt"),
            detail=f"The obscure free kick after a fair catch, almost never tried. {text.strip()}",
            facts=ctx.fact("nfl-fair-catch-kick"), unique=str(p.get("id", "")),
        )


@detector("nfl", "cfb")
def long_field_goal(game: Game, ctx):
    thresholds = ([(66, "legendary"), (64, "epic"), (62, "rare")] if game.league == "nfl"
                  else [(65, "legendary"), (62, "epic"), (59, "rare")])
    for p in scoring_plays(game):
        if "field goal good" not in p["_type"]:
            continue
        m = FG_RE.search(p.get("text", ""))
        if not m:
            continue
        yards = int(m.group(1))
        tier = tiered(yards, thresholds)
        if tier:
            team = team_of(game, p)
            kicker = who(p.get("text", ""))
            yield make_event(
                game, "long-fg", category="milestone", tier=tier,
                title=f"{yards}-yard field goal",
                detail=f"{kicker or team.name} drilled a {yards}-yarder for {team.name}.",
                teams=[team, game.other(team)], players=[kicker] if kicker else [],
                facts=ctx.fact(f"{game.league}-long-fg"), unique=str(p.get("id", "")),
            )


@detector("nfl", "cfb")
def long_plays(game: Game, ctx):
    for p in scoring_plays(game):
        m = YARDS_RE.search(p.get("text", ""))
        if not m:
            continue
        yards, kind = int(m.group(1)), m.group(2).lower()
        if kind == "pass":
            tier = tiered(yards, [(99, "legendary" if game.league == "nfl" else "epic"), (98, "rare")])
            label = f"{yards}-yard touchdown pass"
        elif kind in ("rush", "run"):
            tier = tiered(yards, [(99, "legendary"), (98, "epic")])
            label = f"{yards}-yard touchdown run"
        else:
            tier = tiered(yards, [(108, "legendary"), (104, "epic"), (100, "rare")])
            label = f"{yards}-yard {kind.lower()} touchdown"
        if not tier:
            continue
        team = team_of(game, p)
        player = who(p.get("text", ""))
        yield make_event(
            game, "long-play", category="oddity", tier=tier,
            title=label[0].upper() + label[1:],
            detail=f"{player or team.name} went the distance: {p.get('text', '').strip()}",
            teams=[team, game.other(team)], players=[player] if player else [],
            facts=ctx.fact(f"{game.league}-{'99-pass' if kind == 'pass' else '99-run' if kind in ('rush', 'run') else 'long-return'}"),
            unique=str(p.get("id", "")),
        )


@detector("nfl", "cfb")
def non_offensive_tds(game: Game, ctx):
    counts: dict[str, int] = {}
    for p in scoring_plays(game):
        if any(t in p["_type"] for t in DEF_TD_TYPES):
            counts[p["_team"]] = counts.get(p["_team"], 0) + 1
    for team_id, n in counts.items():
        tier = tiered(n, [(4, "legendary"), (3, "epic")])
        team = game.team_by_id(team_id)
        if tier and team:
            yield make_event(
                game, "defense-st-tds", category="oddity", tier=tier,
                title=f"{n} defensive/special-teams touchdowns",
                detail=f"{team.name} scored {n} touchdowns without their offense on the field.",
                teams=[team, game.other(team)], unique=team_id,
            )


def _player_totals(game: Game) -> dict[str, dict]:
    """Merge a player's rows across stat categories: id -> {name, team_id, cat.stat: value}."""
    players: dict[str, dict] = {}
    for r in box_players(game.data or {}):
        p = players.setdefault(r["id"], {"name": r["name"], "team_id": r["team_id"], "cats": set()})
        p["cats"].add(r["category"])
        for k, v in r["stats"].items():
            p[f"{r['category']}.{k}"] = v
    return players


INDIVIDUAL = {
    # (stat, thresholds by league, title template, fact id)
    "pass_td": ("passing.passingTouchdowns",
                {"nfl": [(7, "legendary"), (6, "epic")], "cfb": [(9, "legendary"), (8, "epic")]},
                "{n} touchdown passes", "pass-td"),
    "pass_yds": ("passing.passingYards",
                 {"nfl": [(550, "legendary"), (500, "epic")], "cfb": [(650, "legendary"), (600, "epic")]},
                 "{n} passing yards", "pass-yds"),
    "rush_yds": ("rushing.rushingYards",
                 {"nfl": [(275, "legendary"), (250, "epic"), (225, "rare")],
                  "cfb": [(375, "legendary"), (330, "epic"), (300, "rare")]},
                 "{n} rushing yards", "rush-yds"),
    "rush_td": ("rushing.rushingTouchdowns",
                {"nfl": [(6, "legendary"), (5, "epic")], "cfb": [(7, "legendary"), (6, "epic")]},
                "{n} rushing touchdowns", "rush-td"),
    "rec_yds": ("receiving.receivingYards",
                {"nfl": [(300, "legendary"), (260, "epic"), (230, "rare")],
                 "cfb": [(350, "legendary"), (300, "epic"), (270, "rare")]},
                "{n} receiving yards", "rec-yds"),
    "rec_td": ("receiving.receivingTouchdowns",
               {"nfl": [(5, "legendary"), (4, "rare")], "cfb": [(6, "legendary"), (5, "epic")]},
               "{n} touchdown catches", "rec-td"),
    "sacks": ("defensive.sacks",
              {"nfl": [(7, "legendary"), (5, "epic")], "cfb": [(6, "legendary"), (5, "epic")]},
              "{n} sacks", "sacks"),
    "ints": ("interceptions.interceptions",
             {"nfl": [(4, "legendary"), (3, "rare")], "cfb": [(5, "legendary"), (4, "epic")]},
             "{n} interceptions", "ints"),
}


@detector("nfl", "cfb")
def individual_records(game: Game, ctx):
    for pid, p in _player_totals(game).items():
        team = game.team_by_id(p["team_id"]) or game.home
        for slug, (stat, by_league, title, fact) in INDIVIDUAL.items():
            n = num(p.get(stat))
            tier = tiered(n, by_league[game.league])
            if tier:
                n_txt = f"{n:g}"
                yield make_event(
                    game, slug, category="milestone", tier=tier,
                    title=f"{p['name']}: {title.format(n=n_txt)}",
                    detail=f"{p['name']} ({team.name}) put up {title.format(n=n_txt)} in {game.matchup()}.",
                    teams=[team, game.other(team)], players=[p["name"]],
                    facts=ctx.fact(f"{game.league}-{fact}"), unique=pid,
                )
        pass_td = num(p.get("passing.passingTouchdowns"))
        rush_td = num(p.get("rushing.rushingTouchdowns"))
        rec_td = num(p.get("receiving.receivingTouchdowns"))
        if pass_td and rush_td and rec_td:
            yield make_event(
                game, "td-triple-threat", category="oddity", tier="legendary",
                title=f"{p['name']} threw, ran AND caught a touchdown",
                detail=f"The touchdown triple crown: {p['name']} ({team.name}) scored every way an offense can.",
                teams=[team, game.other(team)], players=[p["name"]], facts=ctx.fact("td-triple-threat"),
                unique=pid,
            )
        elif pass_td and rec_td:
            yield make_event(
                game, "throw-and-catch-td", category="oddity", tier="epic" if game.league == "nfl" else "rare",
                title=f"{p['name']} threw a TD and caught one",
                detail=f"{p['name']} ({team.name}) both threw and caught a touchdown pass.",
                teams=[team, game.other(team)], players=[p["name"]], unique=pid,
            )


@detector("cfb")
def cfb_rank_upsets(game: Game, ctx):
    w, l = game.winner, game.loser
    if not w or not l or not l.rank:
        return
    fcs_winner = w.conference_id is not None and w.conference_id not in FBS_CONFERENCES
    if fcs_winner:
        tier = "legendary" if l.rank <= 10 else "epic"
        yield make_event(
            game, "fcs-over-ranked", category="wild", tier=tier,
            title=f"FCS {w.short or w.name} take down No. {l.rank} {l.short or l.name}",
            detail=f"An FCS team beat a ranked FBS opponent: {game.matchup()}.",
            teams=[w, l],
        )
    elif not w.rank and l.rank <= 5:
        tier = "epic" if l.rank == 1 else "rare"
        yield make_event(
            game, "unranked-over-top5", category="wild", tier=tier,
            title=f"Unranked {w.short or w.name} stun No. {l.rank} {l.short or l.name}",
            detail=f"{w.name} were unranked and beat No. {l.rank} {l.name}: {game.matchup()}.",
            teams=[w, l],
        )
