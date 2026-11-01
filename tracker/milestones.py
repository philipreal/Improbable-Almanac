"""MLB career milestones (500 homers, 3,000 hits...), found by diffing daily career leaderboards."""
import logging
from datetime import date

from .models import Event
from .sources.mlb_statsapi import fetch_career_leaders

log = logging.getLogger(__name__)

# (group, stat, label, [(threshold, tier), ...])
MILESTONES = [
    ("hitting", "homeRuns", "career home runs", [(700, "legendary"), (600, "legendary"), (500, "epic"), (400, "rare")]),
    ("hitting", "hits", "career hits", [(4000, "legendary"), (3000, "epic"), (2500, "rare")]),
    ("hitting", "stolenBases", "career stolen bases", [(800, "legendary"), (600, "epic"), (500, "rare")]),
    ("pitching", "strikeOuts", "career strikeouts", [(4000, "legendary"), (3000, "epic"), (2500, "rare")]),
    ("pitching", "wins", "career wins", [(300, "legendary"), (250, "epic"), (200, "rare")]),
    ("pitching", "saves", "career saves", [(600, "legendary"), (500, "epic"), (400, "rare")]),
]


def check(state: dict, today: date | None = None) -> list[Event]:
    """state is store.state['milestones'] (mutated). Returns new milestone events."""
    today = today or date.today()
    events = []
    for group, stat, label, thresholds in MILESTONES:
        try:
            leaders = fetch_career_leaders(group, stat)
        except Exception:
            log.exception("milestone fetch failed for %s", stat)
            continue
        prev = state.get(stat)
        current = {p["id"]: p["value"] for p in leaders}
        if prev is not None:
            for p in leaders:
                before = prev.get(p["id"])
                if before is None or before >= p["value"]:
                    continue
                for threshold, tier in thresholds:
                    if before < threshold <= p["value"]:
                        rank = 1 + sum(1 for q in leaders if q["value"] > p["value"])
                        events.append(Event(
                            key=f"mlb:milestone:{p['id']}:{stat}:{threshold}", league="mlb",
                            category="milestone", tier=tier,
                            title=f"{p['name']} reaches {threshold:,} {label}",
                            detail=f"{p['name']} is now at {p['value']:,} {label}, "
                                   f"No. {rank} on the all-time list.",
                            date=f"{today.isoformat()}T23:00:00Z", players=[p["name"]],
                            facts=[f"{p['name']} ranks No. {rank} all-time with {p['value']:,} {label}."],
                        ))
                        break
        state[stat] = current
    return events
