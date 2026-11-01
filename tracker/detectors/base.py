"""Detector registry. A detector is a function (game, ctx) -> iterable of Event."""
import logging
from dataclasses import dataclass, field
from typing import Callable, Iterable

from ..models import Event, Game

log = logging.getLogger(__name__)

DETECTORS: list[tuple[tuple[str, ...], bool, Callable]] = []


@dataclass
class Context:
    """Shared state detectors may consult."""
    scorigami: dict = field(default_factory=dict)  # league -> rarity.scorigami.Table
    facts: dict = field(default_factory=dict)  # fact id -> dict from seed/rarity_facts.yaml
    favorite_teams: dict = field(default_factory=dict)  # league -> set of abbrs

    def fact(self, fact_id: str) -> list[str]:
        """The curated 'how rare' sentence for an event type, if we have one."""
        f = self.facts.get(fact_id)
        return [f["text"]] if f and f.get("text") else []


def detector(*leagues: str, live: bool = False):
    """Register a detector for the given leagues. live=True detectors also run on games
    still in progress (their events are marked live and replaced when the game ends)."""
    def wrap(fn):
        DETECTORS.append((leagues, live, fn))
        return fn
    return wrap


def run_detectors(game: Game, ctx: Context) -> list[Event]:
    # Import for registration side effects.
    from . import common, football, mlb, nba  # noqa: F401
    events: list[Event] = []
    for leagues, live, fn in DETECTORS:
        if game.league not in leagues:
            continue
        if not game.final and not live:
            continue
        try:
            for ev in fn(game, ctx) or []:
                events.append(ev)
        except Exception:  # one broken detector must never sink the whole run
            log.exception("detector %s failed on %s %s", fn.__name__, game.league, game.id)
    return events


def tiered(value: float, thresholds: Iterable[tuple[float, str]]) -> str | None:
    """thresholds: [(min_value, tier), ...] from highest to lowest."""
    for minimum, tier in thresholds:
        if value >= minimum:
            return tier
    return None


def ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"
