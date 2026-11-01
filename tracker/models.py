"""Shared data model. Every source normalizes into Game; every detector emits Event."""
from dataclasses import asdict, dataclass, field
from typing import Any

LEAGUES = ("mlb", "nfl", "nba", "cfb")
LEAGUE_NAMES = {"mlb": "MLB", "nfl": "NFL", "nba": "NBA", "cfb": "College Football"}

TIERS = {"legendary": 4, "epic": 3, "rare": 2, "notable": 1}
CATEGORIES = ("never-before", "oddity", "milestone", "wild")
# Dad's favorites: "never happened before" and weird oddities rank a notch higher.
FAVORED = {"never-before": 1.0, "oddity": 0.6, "milestone": 0.0, "wild": 0.0}


@dataclass
class Team:
    id: str
    abbr: str
    name: str
    short: str = ""
    logo: str = ""
    color: str = ""
    rank: int | None = None
    conference_id: str | None = None


@dataclass
class Game:
    league: str
    id: str
    date: str  # ISO start time (UTC)
    state: str  # "pre" | "in" | "post"
    detail: str  # human status, e.g. "Final/OT" or "Top 7th"
    home: Team
    away: Team
    home_score: int = 0
    away_score: int = 0
    period: int = 0
    home_lines: list[int] = field(default_factory=list)
    away_lines: list[int] = field(default_factory=list)
    link: str = ""
    season_type: str = "regular"  # "regular" | "postseason" | "other"
    # Betting favorite and the size of the spread, when known.
    favorite: str | None = None  # team abbr
    spread: float | None = None
    # Source-specific payload: ESPN summary JSON or MLB live feed JSON.
    data: dict[str, Any] | None = None
    # Anything else a source wants to pass along (e.g. live hits for no-hitter watch).
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def final(self) -> bool:
        return self.state == "post"

    @property
    def winner(self) -> Team | None:
        if self.home_score == self.away_score:
            return None
        return self.home if self.home_score > self.away_score else self.away

    @property
    def loser(self) -> Team | None:
        if self.home_score == self.away_score:
            return None
        return self.away if self.home_score > self.away_score else self.home

    def team_by_id(self, team_id: str) -> Team | None:
        team_id = str(team_id)
        for t in (self.home, self.away):
            if t.id == team_id:
                return t
        return None

    def other(self, team: Team) -> Team:
        return self.away if team.id == self.home.id else self.home

    def score_of(self, team: Team) -> int:
        return self.home_score if team.id == self.home.id else self.away_score

    def matchup(self) -> str:
        return f"{self.away.abbr} {self.away_score}, {self.home.abbr} {self.home_score}"


@dataclass
class Event:
    key: str  # stable id used for dedupe
    league: str
    category: str
    tier: str
    title: str
    detail: str
    date: str
    game_id: str = ""
    matchup: str = ""
    link: str = ""
    teams: list[str] = field(default_factory=list)  # team abbrs involved
    team_logos: list[str] = field(default_factory=list)
    players: list[str] = field(default_factory=list)
    facts: list[str] = field(default_factory=list)  # verified numbers for the "how rare" line
    blurb: str = ""
    source: str = "detector"  # "detector" | "news"
    source_name: str = ""
    sport: str = ""
    live: bool = False

    @property
    def score(self) -> float:
        return TIERS[self.tier] + FAVORED.get(self.category, 0)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["score"] = round(self.score, 2)
        return d


def make_event(game: Game, slug: str, *, category: str, tier: str, title: str, detail: str,
               facts: list[str] | None = None, teams: list[Team] | None = None,
               players: list[str] | None = None, unique: str = "") -> Event:
    assert category in CATEGORIES, category
    assert tier in TIERS, tier
    teams = teams if teams is not None else [game.away, game.home]
    key = f"{game.league}:{game.id}:{slug}" + (f":{unique}" if unique else "")
    return Event(
        key=key, league=game.league, category=category, tier=tier, title=title, detail=detail,
        date=game.date, game_id=game.id, matchup=game.matchup(), link=game.link,
        teams=[t.abbr for t in teams], team_logos=[t.logo for t in teams],
        players=players or [], facts=facts or [],
    )
