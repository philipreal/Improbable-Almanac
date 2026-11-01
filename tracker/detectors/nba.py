"""NBA oddities from ESPN box scores and play-by-play."""
import re

from ..models import Game, make_event
from ..sources.espn import box_players, made_att, num
from .base import detector, tiered

SHOT_RE = re.compile(r"^(.*?) makes (\d+)-foot", re.I)


def player_lines(game: Game) -> list[dict]:
    out = []
    for r in box_players(game.data or {}):
        s = r["stats"]
        if r["dnp"] or "points" not in s:
            continue
        fgm, fga = made_att(s.get("fieldGoalsMade-fieldGoalsAttempted"))
        tpm, tpa = made_att(s.get("threePointFieldGoalsMade-threePointFieldGoalsAttempted"))
        ftm, fta = made_att(s.get("freeThrowsMade-freeThrowsAttempted"))
        out.append({
            "id": r["id"], "name": r["name"], "team_id": r["team_id"],
            "min": num(s.get("minutes")), "pts": num(s.get("points")), "reb": num(s.get("rebounds")),
            "ast": num(s.get("assists")), "stl": num(s.get("steals")), "blk": num(s.get("blocks")),
            "fgm": fgm, "fga": fga, "tpm": tpm, "tpa": tpa, "ftm": ftm, "fta": fta,
        })
    return out


SINGLE = [
    # (key, thresholds, title, fact id)
    ("pts", [(70, "legendary"), (60, "epic"), (55, "rare")], "{n} points", "nba-points"),
    ("reb", [(30, "legendary"), (27, "epic"), (25, "rare")], "{n} rebounds", "nba-rebounds"),
    ("ast", [(27, "legendary"), (24, "epic"), (22, "rare")], "{n} assists", "nba-assists"),
    ("blk", [(14, "legendary"), (12, "epic"), (10, "rare")], "{n} blocks", "nba-blocks"),
    ("stl", [(11, "legendary"), (10, "epic"), (8, "rare")], "{n} steals", "nba-steals"),
    ("tpm", [(14, "legendary"), (13, "epic"), (12, "rare")], "{n} three-pointers", "nba-threes"),
]


@detector("nba")
def nba_individual(game: Game, ctx):
    for p in player_lines(game):
        team = game.team_by_id(p["team_id"]) or game.home
        teams = [team, game.other(team)]
        cats = [p["pts"], p["reb"], p["ast"], p["stl"], p["blk"]]
        doubles = sum(1 for c in cats if c >= 10)
        if doubles >= 5:
            yield make_event(game, "quintuple-double", category="never-before", tier="legendary",
                             title=f"{p['name']}: a QUINTUPLE-double", teams=teams, players=[p["name"]],
                             detail=f"{p['name']} hit double figures in all five major stats.",
                             facts=ctx.fact("nba-quintuple-double"), unique=p["id"])
        elif doubles == 4:
            yield make_event(game, "quadruple-double", category="oddity", tier="legendary",
                             title=f"{p['name']} records a quadruple-double", teams=teams, players=[p["name"]],
                             detail=f"{p['name']}: {p['pts']:g} pts, {p['reb']:g} reb, {p['ast']:g} ast, "
                                    f"{p['stl']:g} stl, {p['blk']:g} blk.",
                             facts=ctx.fact("nba-quadruple-double"), unique=p["id"])
        if p["pts"] >= 20 and p["reb"] >= 20 and p["ast"] >= 20:
            yield make_event(game, "20-20-20", category="oddity", tier="legendary",
                             title=f"{p['name']} goes 20-20-20", teams=teams, players=[p["name"]],
                             detail=f"{p['name']}: {p['pts']:g} points, {p['reb']:g} rebounds, {p['ast']:g} assists.",
                             facts=ctx.fact("nba-20-20-20"), unique=p["id"])
        if all(c >= 5 for c in cats):
            yield make_event(game, "5x5", category="oddity", tier="epic",
                             title=f"{p['name']} posts a 5x5", teams=teams, players=[p["name"]],
                             detail=f"At least 5 in every category: {p['pts']:g}/{p['reb']:g}/{p['ast']:g}/"
                                    f"{p['stl']:g}/{p['blk']:g}.",
                             facts=ctx.fact("nba-5x5"), unique=p["id"])
        if doubles >= 3 and 0 < p["min"] <= 20:
            yield make_event(game, "speedy-triple-double", category="oddity", tier="epic",
                             title=f"{p['name']}: triple-double in {p['min']:g} minutes", teams=teams,
                             players=[p["name"]],
                             detail=f"{p['name']} needed only {p['min']:g} minutes for a triple-double.",
                             unique=p["id"])
        perfect_tier = tiered(p["fgm"], [(18, "legendary"), (15, "epic"), (12, "rare")])
        if perfect_tier and p["fgm"] == p["fga"]:
            yield make_event(game, "perfect-shooting", category="oddity", tier=perfect_tier,
                             title=f"{p['name']} goes {p['fgm']}-for-{p['fga']} from the field", teams=teams,
                             players=[p["name"]],
                             detail=f"{p['name']} didn't miss a shot: {p['fgm']}-for-{p['fga']}.",
                             facts=ctx.fact("nba-perfect-shooting"), unique=p["id"])
        for key, thresholds, title, fact in SINGLE:
            tier = tiered(p[key], thresholds)
            if tier:
                n = f"{p[key]:g}"
                yield make_event(game, f"big-{key}", category="milestone", tier=tier,
                                 title=f"{p['name']}: {title.format(n=n)}", teams=teams, players=[p["name"]],
                                 detail=f"{p['name']} ({team.name}) had {title.format(n=n)} in {game.matchup()}.",
                                 facts=ctx.fact(fact), unique=p["id"])


@detector("nba")
def nba_heaves(game: Game, ctx):
    """Made shots from 40+ feet, especially at the buzzer."""
    plays = (game.data or {}).get("plays") or []
    for i, p in enumerate(plays):
        if not p.get("scoringPlay"):
            continue
        m = SHOT_RE.match(p.get("text", ""))
        if not m:
            continue
        feet = int(m.group(2))
        if feet < 40:
            continue
        clock = (p.get("clock") or {}).get("displayValue", "")
        period = (p.get("period") or {}).get("number", 0)
        buzzer = clock in ("0.0", "0.1", "0.2", "0.3", "0.4", "0.5", "0:00")
        team = game.team_by_id((p.get("team") or {}).get("id", "")) or game.home
        a, h = int(p.get("awayScore") or 0), int(p.get("homeScore") or 0)
        pts = int(p.get("scoreValue") or 3)
        before_a, before_h = (a - pts, h) if team.id == game.away.id else (a, h - pts)
        game_winner = (period >= 4 and buzzer and game.final and game.winner and game.winner.id == team.id
                       and i >= len(plays) - 4 and
                       ((team.id == game.away.id and before_a <= before_h) or
                        (team.id == game.home.id and before_h <= before_a)))
        if game_winner:
            tier, title = "legendary", f"{feet}-foot game-winner at the buzzer"
        elif buzzer:
            tier, title = ("epic" if feet >= 60 else "rare"), f"{feet}-foot buzzer-beater"
        elif feet >= 50:
            tier, title = "rare", f"{feet}-foot bomb"
        else:
            continue
        shooter = m.group(1).strip()
        yield make_event(game, "heave", category="oddity", tier=tier, title=f"{shooter}: {title}",
                         detail=f"{shooter} ({team.name}) — {p.get('text', '').strip()} "
                                f"({'end of ' + str(period) + 'Q' if period <= 4 else 'OT'}).",
                         teams=[team, game.other(team)], players=[shooter], unique=str(p.get("id", "")))


@detector("nba")
def nba_quarters(game: Game, ctx):
    for team, lines in ((game.home, game.home_lines), (game.away, game.away_lines)):
        for q, pts in enumerate(lines[:4], start=1):
            high = tiered(pts, [(58, "legendary"), (54, "epic"), (51, "rare")])
            low = tiered(-pts, [(-3, "legendary"), (-5, "epic"), (-7, "rare")])
            if high or low:
                yield make_event(
                    game, "quarter", category="oddity", tier=high or low,
                    title=f"{team.short or team.name}: {pts} points in the {['1st', '2nd', '3rd', '4th'][q - 1]} quarter",
                    detail=f"{team.name} scored {pts} in a single quarter of {game.matchup()}.",
                    teams=[team, game.other(team)], unique=f"{team.id}-{q}",
                )
