"""Bookkeeping: milestone diffs, event dedupe, and the no-API-key fallbacks."""
from datetime import date

from tracker import milestones
from tracker.ai import blurbs, triage
from tracker.models import Event


def test_milestone_crossing(monkeypatch):
    boards = {"homeRuns": [{"id": "1", "name": "Slugger", "value": 499}]}
    monkeypatch.setattr(milestones, "fetch_career_leaders", lambda group, stat: boards.get(stat, []))
    state = {}
    assert milestones.check(state, date(2026, 5, 1)) == []  # first run only snapshots
    boards["homeRuns"] = [{"id": "1", "name": "Slugger", "value": 501}]
    events = milestones.check(state, date(2026, 5, 2))
    assert [e.title for e in events] == ["Slugger reaches 500 career home runs"]
    assert milestones.check(state, date(2026, 5, 3)) == []  # no repeat


def test_store_dedupes_and_keeps_blurbs(tmp_path, monkeypatch):
    from tracker import store as store_mod
    monkeypatch.setattr(store_mod, "DATA_DIR", tmp_path / "site")
    monkeypatch.setattr(store_mod, "STATE_DIR", tmp_path / "data")
    s = store_mod.Store()
    s.events_path = tmp_path / "site" / "events.json"
    s.state_path = tmp_path / "data" / "state.json"
    ev = Event(key="nfl:1:tie", league="nfl", category="oddity", tier="rare", title="Tie", detail="d",
               date="2026-10-01T00:00Z")
    assert s.add(ev) is True
    s.events[ev.key]["blurb"] = "paid-for note"
    assert s.add(ev) is False
    assert s.events[ev.key]["blurb"] == "paid-for note"


def test_ai_skips_without_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    events = [{"key": "k", "league": "nfl", "title": "t", "detail": "d", "date": "2026-01-01"}]
    blurbs.fill(events)
    assert "blurb" not in events[0]
    assert triage.triage([{"id": "1", "source": "x", "title": "t", "text": "", "url": "", "date": ""}], []) == []
