"""Fetch games (with full detail) from the right source for each league."""
from datetime import date, timedelta

from .models import Game
from .sources import espn, mlb_statsapi


def list_games(league: str, day: date) -> list[Game]:
    if league == "mlb":
        return mlb_statsapi.fetch_schedule(day.isoformat())
    return espn.fetch_scoreboard(league, f"{day:%Y%m%d}")


def list_current(league: str) -> list[Game]:
    """Today's slate (and, for football, this week's)."""
    if league == "mlb":
        today = date.today()
        # Late games finish after midnight UTC; look at yesterday too.
        return mlb_statsapi.fetch_schedule((today - timedelta(days=1)).isoformat(), today.isoformat())
    return espn.fetch_scoreboard(league)


def load_detail(game: Game, cache: bool | None = None) -> Game:
    """Attach the summary/feed that detectors need. Finished games are cached on disk."""
    cache = game.final if cache is None else cache
    if game.league == "mlb":
        game.data = mlb_statsapi.fetch_feed(game.id, cache=cache)
        return game
    return espn.attach_summary(game, espn.fetch_summary(game.league, game.id, cache=cache))


def find_game(league: str, day: str, team: str) -> Game:
    """Look up one game by date and team abbreviation (used by tests and debugging)."""
    d = date.fromisoformat(day)
    for g in list_games(league, d):
        if team.upper() in (g.home.abbr.upper(), g.away.abbr.upper()):
            return g
    raise LookupError(f"no {league} game for {team} on {day}")
