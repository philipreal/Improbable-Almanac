"""Save real games with known rare events as compressed test fixtures.

    python -m tests.make_fixtures
"""
import dataclasses
import gzip
import json
from pathlib import Path

from tracker.loader import find_game, load_detail

HERE = Path(__file__).parent / "fixtures"
CASES = {
    "mlb_perfect_german_2023": ("mlb", "2023-06-28", "NYY"),
    "mlb_unassisted_tp_2009": ("mlb", "2009-08-23", "PHI"),
    "mlb_four_hr_jdmartinez_2017": ("mlb", "2017-09-04", "AZ"),
    "mlb_immaculate_soroka_2026": ("mlb", "2026-03-30", "AZ"),
    "nfl_tucker_66_2021": ("nfl", "2021-09-26", "BAL"),
    "nfl_tie_2022": ("nfl", "2022-09-11", "HOU"),
    "nfl_ordinary_2026": ("nfl", "2026-10-18", "JAX"),
    "cfb_kick_six_2013": ("cfb", "2013-11-30", "AUB"),
    "nba_westbrook_202020_2019": ("nba", "2019-04-02", "OKC"),
}


def save(name, league, day, team):
    g = load_detail(find_game(league, day, team))
    meta = dataclasses.asdict(g)
    meta.pop("data")
    (HERE / f"{name}.json.gz").write_bytes(gzip.compress(json.dumps({"game": meta, "data": g.data}).encode()))
    print(name, g.matchup())


if __name__ == "__main__":
    HERE.mkdir(exist_ok=True)
    for name, args in CASES.items():
        save(name, *args)
