"""Cross-game streaks: counting rules, idempotence, and the cards they produce."""
from tracker.models import Game, Team
from tracker.streaks import Tracker

HOME = Team(id="1", abbr="HOM", name="Home Club")
AWAY = Team(id="2", abbr="AWY", name="Away Club")
ACE, REL = 101, 202


class FakeStore:
    def __init__(self):
        self.state, self.events, self.new_keys = {}, {}, []

    def add(self, ev):
        self.events[ev.key] = ev.to_dict()


def _play(inning, half, pitcher, outs_after, scorer_charged_to=None):
    runners = []
    if scorer_charged_to:
        runners.append({"movement": {"end": "score"}, "details": {"responsiblePitcher": {"id": scorer_charged_to}}})
    return {"about": {"inning": inning, "halfInning": half}, "matchup": {"pitcher": {"id": pitcher}},
            "count": {"outs": outs_after}, "runners": runners, "result": {"type": "atBat"}}


def _mlb_game(gid, plays, gtype="R", date="2026-05-01T23:00Z"):
    box = {"home": {"pitchers": [ACE, REL], "batters": [], "players": {
        f"ID{ACE}": {"person": {"fullName": "Ace"}}, f"ID{REL}": {"person": {"fullName": "Reliever"}}}},
           "away": {"pitchers": [], "batters": [], "players": {}}}
    return Game(league="mlb", id=gid, date=date, state="post", detail="Final", home=HOME, away=AWAY,
                home_score=1, away_score=0,
                data={"gameData": {"game": {"type": gtype}},
                      "liveData": {"boxscore": {"teams": box}, "plays": {"allPlays": plays}}})


def test_scoreless_counts_only_clean_innings():
    t = Tracker(FakeStore())
    plays = [
        # Top 1: two outs, then a run charged to the ace -> none of this inning counts.
        _play(1, "top", ACE, 1), _play(1, "top", ACE, 2), _play(1, "top", ACE, 2, scorer_charged_to=ACE),
        _play(1, "top", ACE, 3),
        # Top 2 and 3: clean.
        _play(2, "top", ACE, 1), _play(2, "top", ACE, 2), _play(2, "top", ACE, 3),
        _play(3, "top", ACE, 1), _play(3, "top", ACE, 2), _play(3, "top", ACE, 3),
    ]
    t.update(_mlb_game("g1", plays))
    assert t.active["mlb:scoreless:101"]["value"] == 6  # two innings, in outs


def test_inherited_runner_spoils_the_inning_for_the_pitcher_who_left_him():
    t = Tracker(FakeStore())
    plays = [_play(1, "top", ACE, 1), _play(1, "top", REL, 2, scorer_charged_to=ACE), _play(1, "top", REL, 3)]
    t.update(_mlb_game("g1", plays))
    assert "mlb:scoreless:101" not in t.active
    assert t.active["mlb:scoreless:202"]["value"] == 2


def test_games_are_counted_once():
    t = Tracker(FakeStore())
    game = _mlb_game("g1", [_play(1, "top", ACE, 1), _play(1, "top", ACE, 2), _play(1, "top", ACE, 3)])
    t.update(game)
    t.update(game)
    assert t.active["mlb:scoreless:101"]["value"] == 3


def test_relief_record_card_and_starts_still_break_streaks():
    store = FakeStore()
    t = Tracker(store)
    clean_inning = lambda i: [_play(i, "top", REL, 1), _play(i, "top", REL, 2), _play(i, "top", REL, 3)]
    for n in range(17):  # 17 scoreless relief innings across postseason games
        t.update(_mlb_game(f"p{n}", [_play(1, "top", ACE, 3)] + clean_inning(2), gtype="W",
                           date=f"2026-10-{n + 10:02d}T23:00Z"))
    cards = [e for k, e in store.events.items() if "post-relief:202" in k]
    assert cards and cards[0]["tier"] == "legendary" and cards[0]["title"].startswith("Record!")
    # Allowing a run, even in a start, ends it.
    t.update(_mlb_game("p99", [_play(1, "top", REL, 0, scorer_charged_to=REL)], gtype="W",
                       date="2026-10-30T23:00Z"))
    assert "mlb:post-relief:202" not in t.active


def test_team_win_streak():
    store = FakeStore()
    t = Tracker(store)
    for n in range(14):
        t.update(Game(league="mlb", id=f"t{n}", date=f"2026-07-{n + 1:02d}T23:00Z", state="post", detail="Final",
                      home=HOME, away=AWAY, home_score=5, away_score=1))
    assert t.active["mlb:team-win:HOM"]["value"] == 14
    assert t.active["mlb:team-loss:AWY"]["value"] == 14
    assert any("winning streak reaches 14" in e["title"] for e in store.events.values())
