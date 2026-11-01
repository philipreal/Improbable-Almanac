"""Detectors that work the same way in every league: scorigami, comebacks, upsets,
marathon games and lopsided scores."""
from ..models import LEAGUE_NAMES, Game, make_event
from ..sources.espn import FBS_CONFERENCES, football_plays
from .base import detector, ordinal, tiered


@detector("nfl", "cfb", "mlb")
def scorigami(game: Game, ctx):
    table = ctx.scorigami.get(game.league)
    if table is None or table.games == 0 or table.already_recorded(game):
        return
    before = table.record(game)
    hi, lo = max(game.home_score, game.away_score), min(game.home_score, game.away_score)
    lg = LEAGUE_NAMES[game.league]
    since = table.data.get("since")
    prior_games = table.games - 1
    if before is None:
        yield make_event(
            game, "scorigami", category="never-before", tier="legendary",
            title=f"Scorigami! {hi}–{lo} has never happened before",
            detail=f"{game.matchup()} is a final score that had never occurred in {lg} history.",
            facts=[f"No {lg} game had ever ended {hi}–{lo} in {prior_games:,} games since {since}.",
                   f"This is the {ordinal(table.distinct)} unique final score in {lg} history."],
        )
    elif before["n"] == 1:
        yield make_event(
            game, "scorigami-second", category="never-before", tier="rare",
            title=f"Only the second {hi}–{lo} final ever",
            detail=f"{game.matchup()} matches a final score that had happened just once before.",
            facts=[f"The only other {hi}–{lo} game in {lg} history: {before.get('lastGame', '?')} "
                   f"on {before.get('last', '?')}."],
        )


def score_states(game: Game) -> list[tuple[int, int]]:
    """(away, home) score after each play, in order."""
    d = game.data or {}
    if game.league in ("nfl", "cfb"):
        plays = football_plays(d)
    elif game.league == "nba":
        plays = d.get("plays") or []
    else:
        plays = [p.get("result", {}) for p in (d.get("liveData") or {}).get("plays", {}).get("allPlays", [])]
    states = []
    for p in plays:
        a, h = p.get("awayScore"), p.get("homeScore")
        if a is not None and h is not None:
            states.append((int(a), int(h)))
    return states


COMEBACK = {
    "nfl": [(28, "legendary"), (21, "epic"), (18, "rare")],
    "cfb": [(31, "legendary"), (25, "epic"), (21, "rare")],
    "nba": [(32, "legendary"), (27, "epic"), (24, "rare")],
    "mlb": [(10, "legendary"), (8, "epic"), (6, "rare")],
}
UNIT = {"mlb": "run", "nfl": "point", "cfb": "point", "nba": "point"}


@detector("nfl", "cfb", "nba", "mlb")
def comeback(game: Game, ctx):
    winner = game.winner
    if not winner:
        return
    states = score_states(game)
    if not states:
        return
    win_is_home = winner.id == game.home.id
    deficit = max((a - h) if win_is_home else (h - a) for a, h in states)
    tier = tiered(deficit, COMEBACK[game.league])
    if not tier:
        return
    unit = UNIT[game.league]
    yield make_event(
        game, "comeback", category="wild", tier=tier,
        title=f"{winner.short or winner.name} storm back from {deficit} {unit}s down",
        detail=f"{winner.name} trailed by {deficit} and won {game.matchup()}.",
        teams=[winner, game.other(winner)],
        facts=ctx.fact(f"{game.league}-comeback"),
    )


UPSET = {
    "nfl": [(17, "legendary"), (13.5, "epic"), (10.5, "rare")],
    "cfb": [(35, "legendary"), (27.5, "epic"), (21.5, "rare")],
    "nba": [(17, "legendary"), (14.5, "epic"), (12.5, "rare")],
}


@detector("nfl", "cfb", "nba")
def upset(game: Game, ctx):
    if not game.favorite or not game.spread or not game.winner:
        return
    if game.winner.abbr == game.favorite:
        return
    tier = tiered(game.spread, UPSET[game.league])
    if not tier:
        return
    dog = game.winner
    yield make_event(
        game, "upset", category="wild", tier=tier,
        title=f"{game.spread:g}-point underdog {dog.short or dog.name} win outright",
        detail=f"{dog.name} were {game.spread:g}-point underdogs and won {game.matchup()}.",
        teams=[dog, game.other(dog)],
    )


@detector("nfl", "cfb", "nba", "mlb")
def marathon(game: Game, ctx):
    if game.league == "mlb":
        innings = max(len(game.home_lines), len(game.away_lines), game.period)
        tier = tiered(innings, [(20, "legendary"), (18, "epic"), (15, "rare")])
        if tier:
            yield make_event(
                game, "marathon", category="wild", tier=tier,
                title=f"{innings}-inning marathon",
                detail=f"{game.matchup()} took {innings} innings to decide.",
                facts=ctx.fact("mlb-long-game"),
            )
        return
    ots = max(0, game.period - 4)
    if ots == 0:
        return
    if game.league == "nfl":
        tier = "epic" if ots >= 2 else None
    elif game.league == "cfb":
        tier = tiered(ots, [(7, "legendary"), (5, "epic"), (4, "rare")])
    else:
        tier = tiered(ots, [(5, "legendary"), (4, "epic"), (3, "rare")])
    if tier:
        label = "overtime" if ots == 1 else f"{ots} overtimes"
        yield make_event(
            game, "marathon", category="wild", tier=tier,
            title=f"{label.capitalize()}!" if ots > 1 else "Overtime thriller",
            detail=f"{game.matchup()} needed {label}.",
            facts=ctx.fact(f"{game.league}-ot{ots}") or ctx.fact(f"{game.league}-long-game"),
        )


@detector("nfl")
def nfl_tie(game: Game, ctx):
    if game.home_score == game.away_score:
        yield make_event(
            game, "tie", category="oddity", tier="rare",
            title=f"A tie! {game.home_score}–{game.away_score}",
            detail=f"{game.matchup()} ended in a tie after overtime.",
            facts=ctx.fact("nfl-tie"),
        )


SCORING = {
    # league: (team points thresholds, combined thresholds, margin thresholds)
    "nfl": ([(63, "legendary"), (58, "epic"), (54, "rare")],
            [(110, "legendary"), (100, "epic"), (92, "rare")],
            [(55, "legendary"), (48, "epic"), (44, "rare")]),
    "cfb": ([(90, "legendary"), (83, "epic"), (77, "rare")],
            [(130, "legendary"), (118, "epic"), (108, "rare")],
            [(80, "legendary"), (73, "epic"), (68, "rare")]),
    "nba": ([(175, "legendary"), (168, "epic"), (162, "rare")],
            [(320, "legendary"), (305, "epic"), (295, "rare")],
            [(60, "legendary"), (54, "epic"), (48, "rare")]),
    "mlb": ([(30, "legendary"), (25, "epic"), (21, "rare")],
            [(40, "legendary"), (35, "epic"), (31, "rare")],
            [(25, "legendary"), (21, "epic"), (19, "rare")]),
}


@detector("nfl", "cfb", "nba", "mlb")
def lopsided(game: Game, ctx):
    team_t, combined_t, margin_t = SCORING[game.league]
    unit = UNIT[game.league]
    hi = max(game.home_score, game.away_score)
    combined = game.home_score + game.away_score
    margin = abs(game.home_score - game.away_score)
    winner = game.winner
    # Only the most striking angle per game.
    candidates = []
    t = tiered(hi, team_t)
    if t and winner:
        candidates.append((t, "points", f"{winner.short or winner.name} hang {hi} {unit}s",
                           f"{winner.name} scored {hi} in {game.matchup()}."))
    t = tiered(combined, combined_t)
    if t:
        candidates.append((t, "combined", f"{combined} combined {unit}s",
                           f"{game.matchup()}: a {combined}-{unit} shootout."))
    t = tiered(margin, margin_t)
    if t and winner:
        candidates.append((t, "margin", f"{margin}-{unit} rout",
                           f"{winner.name} won by {margin}: {game.matchup()}."))
    if game.league == "nba":
        lo = min(game.home_score, game.away_score)
        t = tiered(-lo, [(-70, "epic"), (-76, "rare")])
        if t:
            loser = game.loser or game.home
            candidates.append((t, "low", f"{loser.short or loser.name} held to {lo}",
                               f"Only {lo} points for {loser.name}: {game.matchup()}."))
    if not candidates:
        return
    from ..models import TIERS
    tier, slug, title, detail = max(candidates, key=lambda c: TIERS[c[0]])
    loser = game.loser
    if (game.league == "cfb" and loser and loser.conference_id
            and loser.conference_id not in FBS_CONFERENCES):
        # FBS teams pounding FCS opponents is a September tradition, not an oddity.
        tier = {"legendary": "epic", "epic": "rare"}.get(tier)
        if not tier:
            return
    yield make_event(game, f"lopsided-{slug}", category="wild", tier=tier, title=title, detail=detail)
