"""Detectors must fire on real games known to contain each oddity, and stay quiet on ordinary ones."""
import gzip
import json
from pathlib import Path

import pytest

from tracker.detectors.base import Context, run_detectors
from tracker.models import Game, Team
from tracker.rarity.scorigami import Table

FIX = Path(__file__).parent / "fixtures"


def load(name: str) -> Game:
    raw = json.loads(gzip.decompress((FIX / f"{name}.json.gz").read_bytes()))
    meta = raw["game"]
    meta["home"], meta["away"] = Team(**meta["home"]), Team(**meta["away"])
    return Game(**meta, data=raw["data"]) if "data" not in meta else Game(**meta)


def slugs(game: Game, ctx: Context | None = None) -> dict[str, str]:
    """slug -> tier for every event detected."""
    return {e.key.split(":")[2]: e.tier for e in run_detectors(game, ctx or Context())}


@pytest.mark.parametrize("fixture, slug, tier", [
    ("mlb_perfect_german_2023", "perfect-game", "legendary"),
    ("mlb_unassisted_tp_2009", "triple-play", "legendary"),
    ("mlb_four_hr_jdmartinez_2017", "four-hr", "legendary"),
    ("mlb_immaculate_soroka_2026", "immaculate-inning", "epic"),
    ("nfl_tucker_66_2021", "long-fg", "legendary"),
    ("nfl_tie_2022", "tie", "rare"),
    ("cfb_kick_six_2013", "kick-six", "legendary"),
    ("nba_westbrook_202020_2019", "20-20-20", "legendary"),
])
def test_known_oddities(fixture, slug, tier):
    found = slugs(load(fixture))
    assert found.get(slug) == tier, found


def test_ordinary_game_is_quiet():
    found = slugs(load("nfl_ordinary_2026"))
    assert found == {}, found


def test_perfect_game_is_not_also_a_plain_no_hitter():
    found = slugs(load("mlb_perfect_german_2023"))
    assert "no-hitter" not in found


def test_scorigami_new_and_repeat():
    game = load("nfl_ordinary_2026")  # HOU 34, JAX 31
    table = Table("nfl", {"league": "nfl", "since": 1920, "games": 1, "scores": {"20-17": {"n": 1}}})
    ctx = Context(scorigami={"nfl": table})
    events = [e for e in run_detectors(game, ctx) if "scorigami" in e.key]
    assert len(events) == 1 and events[0].tier == "legendary"
    assert table.lookup(34, 31)["n"] == 1
    # Running the same game again must not double count or re-announce.
    assert not [e for e in run_detectors(game, ctx) if "scorigami" in e.key]
    assert table.lookup(34, 31)["n"] == 1


def _football_game(scoring_plays, home_score, away_score):
    home = Team(id="1", abbr="HOM", name="Home Team")
    away = Team(id="2", abbr="AWY", name="Away Team")
    return Game(league="nfl", id="x1", date="2026-10-01T17:00Z", state="post", detail="Final",
                home=home, away=away, home_score=home_score, away_score=away_score, period=4,
                data={"scoringPlays": scoring_plays, "drives": {"previous": []}, "boxscore": {}})


def test_one_point_safety():
    plays = [
        {"id": "1", "type": {"text": "Passing Touchdown"}, "text": "A 5 Yd pass from B (Kick blocked)",
         "awayScore": 6, "homeScore": 0, "team": {"id": "2"}},
        {"id": "2", "type": {"text": "Safety"}, "text": "Extra point attempt recovered in end zone, one-point safety",
         "awayScore": 7, "homeScore": 0, "team": {"id": "2"}},
    ]
    assert slugs(_football_game(plays, 0, 7)).get("one-point-safety") == "legendary"


def test_defensive_two_point_return():
    plays = [
        {"id": "1", "type": {"text": "Rushing Touchdown"},
         "text": "A 1 Yd Rush (Two-Point Pass Conversion Failed, returned for defensive two-point conversion)",
         "awayScore": 6, "homeScore": 2, "team": {"id": "2"}},
    ]
    assert slugs(_football_game(plays, 2, 6)).get("defensive-2pt") == "epic"


def test_normal_safety_is_not_flagged():
    plays = [{"id": "1", "type": {"text": "Safety"}, "text": "Team Safety", "awayScore": 0, "homeScore": 2,
              "team": {"id": "1"}}]
    found = slugs(_football_game(plays, 2, 0))
    assert "one-point-safety" not in found and "defensive-2pt" not in found
