"""MLB oddities from the StatsAPI pitch-by-pitch feed."""
from collections import defaultdict

from ..models import Game, make_event
from .base import detector, tiered

HIT_TYPES = ("single", "double", "triple", "home_run")
K_TYPES = ("strikeout", "strikeout_double_play", "strikeout_triple_play")
TP_TYPES = ("triple_play", "grounded_into_triple_play", "strikeout_triple_play")


class Feed:
    """Convenience wrapper around a StatsAPI live feed."""

    def __init__(self, game: Game):
        self.game = game
        self.raw = game.data or {}
        self.gd = self.raw.get("gameData", {})
        self.ld = self.raw.get("liveData", {})
        self.plays = [p for p in self.ld.get("plays", {}).get("allPlays", [])
                      if p.get("result", {}).get("type") == "atBat"]
        self.box = self.ld.get("boxscore", {}).get("teams", {})
        self.linescore = self.ld.get("linescore", {})

    def side_team(self, side: str):
        return self.game.home if side == "home" else self.game.away

    def batting_side(self, play: dict) -> str:
        return "away" if play["about"]["halfInning"] == "top" else "home"

    def position(self, pid) -> str:
        p = self.gd.get("players", {}).get(f"ID{pid}", {})
        return (p.get("primaryPosition") or {}).get("abbreviation", "")

    def name(self, pid) -> str:
        return self.gd.get("players", {}).get(f"ID{pid}", {}).get("fullName", "?")

    def halves(self) -> dict[tuple[int, str], list[dict]]:
        out: dict[tuple[int, str], list[dict]] = defaultdict(list)
        for p in self.plays:
            out[(p["about"]["inning"], p["about"]["halfInning"])].append(p)
        return out

    def pitching_line(self, side: str, pid) -> dict:
        return (self.box.get(side, {}).get("players", {}).get(f"ID{pid}", {}).get("stats", {}) or {}).get("pitching", {})

    def batting_line(self, side: str, pid) -> dict:
        return (self.box.get(side, {}).get("players", {}).get(f"ID{pid}", {}).get("stats", {}) or {}).get("batting", {})

    def innings_batted(self, side: str) -> int:
        return sum(1 for inn in self.linescore.get("innings", []) if "runs" in (inn.get(side) or {}))


def other(side: str) -> str:
    return "home" if side == "away" else "away"


def ip_to_outs(ip: str) -> int:
    try:
        whole, _, frac = str(ip).partition(".")
        return int(whole) * 3 + int(frac or 0)
    except ValueError:
        return 0


@detector("mlb")
def no_hitter(game: Game, ctx):
    f = Feed(game)
    for side in ("home", "away"):  # side = pitching team
        opp = other(side)
        opp_line = f.linescore.get("teams", {}).get(opp, {})
        if opp_line.get("hits", 1) != 0 or f.innings_batted(opp) < 9:
            continue
        pitchers = f.box.get(side, {}).get("pitchers", [])
        opp_bat = (f.box.get(opp, {}).get("teamStats") or {}).get("batting", {})
        perfect = opp_bat.get("plateAppearances", 0) == 3 * f.innings_batted(opp)
        team = f.side_team(side)
        names = [f.name(p) for p in pitchers]
        lost = game.winner is not None and game.winner.id != team.id
        if perfect:
            tier, slug, title = "legendary", "perfect-game", f"PERFECT GAME: {', '.join(names)}"
            detail = f"27 up, 27 down. {team.name} allowed no baserunners at all in {game.matchup()}."
            fact = "mlb-perfect-game"
        elif lost:
            tier, slug, title = "legendary", "no-hitter-loss", f"{team.short or team.name} throw a no-hitter… and lose"
            detail = f"{team.name} didn't allow a hit and still lost {game.matchup()}."
            fact = "mlb-no-hitter-loss"
        else:
            combined = len(pitchers) > 1
            tier, slug = "epic", "no-hitter"
            title = (f"Combined no-hitter by the {team.short or team.name}" if combined
                     else f"No-hitter: {names[0] if names else team.name}")
            detail = f"{' + '.join(names)} held the {f.side_team(opp).name} hitless in {game.matchup()}."
            fact = "mlb-combined-no-hitter" if combined else "mlb-no-hitter"
        yield make_event(game, slug, category="oddity", tier=tier, title=title, detail=detail,
                         teams=[team, f.side_team(opp)], players=names, facts=ctx.fact(fact), unique=side)


@detector("mlb")
def inning_oddities(game: Game, ctx):
    f = Feed(game)
    for (inning, half), pas in f.halves().items():
        side = "away" if half == "top" else "home"
        bat_team, pit_team = f.side_team(side), f.side_team(other(side))
        events = [p["result"].get("eventType") for p in pas]
        # Immaculate inning: three strikeouts on nine pitches by one pitcher.
        pitchers = {p["matchup"]["pitcher"]["id"] for p in pas}
        if len(pas) == 3 and all(e in K_TYPES for e in events) and len(pitchers) == 1:
            pitches = sum(1 for p in pas for ev in p.get("playEvents", []) if ev.get("isPitch"))
            if pitches == 9:
                pname = pas[0]["matchup"]["pitcher"]["fullName"]
                yield make_event(game, "immaculate-inning", category="oddity", tier="epic",
                                 title=f"Immaculate inning: {pname}",
                                 detail=f"{pname} ({pit_team.name}) struck out the side on 9 pitches in the "
                                        f"{half} of inning {inning}.",
                                 teams=[pit_team, bat_team], players=[pname],
                                 facts=ctx.fact("mlb-immaculate-inning"), unique=f"{inning}{half}")
        ks = sum(1 for e in events if e in K_TYPES)
        tier = tiered(ks, [(5, "legendary"), (4, "epic")])
        if tier:
            yield make_event(game, "four-k-inning", category="oddity", tier=tier,
                             title=f"{ks} strikeouts in one inning",
                             detail=f"{pit_team.name} struck out {ks} {bat_team.name} batters in the {half} of "
                                    f"inning {inning} (a dropped third strike let a runner reach).",
                             teams=[pit_team, bat_team], facts=ctx.fact("mlb-four-k-inning"),
                             unique=f"{inning}{half}")
        # Consecutive home runs.
        streak = best = 0
        for e in events:
            streak = streak + 1 if e == "home_run" else 0
            best = max(best, streak)
        tier = tiered(best, [(4, "legendary"), (3, "rare")])
        if tier:
            label = {3: "Back-to-back-to-back", 4: "Back-to-back-to-back-to-back"}.get(best, f"{best} straight")
            yield make_event(game, "consecutive-hr", category="oddity", tier=tier,
                             title=f"{label} home runs",
                             detail=f"{bat_team.name} hit {best} consecutive homers in inning {inning}.",
                             teams=[bat_team, pit_team], facts=ctx.fact(f"mlb-{best}-straight-hr"),
                             unique=f"{inning}{half}")
        # Huge innings.
        runs = (f.linescore.get("innings", [{}] * inning)[inning - 1].get(side) or {}).get("runs", 0) \
            if inning <= len(f.linescore.get("innings", [])) else 0
        tier = tiered(runs or 0, [(15, "legendary"), (13, "epic"), (11, "rare")])
        if tier:
            yield make_event(game, "big-inning", category="wild", tier=tier,
                             title=f"{runs}-run inning",
                             detail=f"{bat_team.name} sent {len(pas)} batters to the plate and scored {runs} in "
                                    f"inning {inning}.",
                             teams=[bat_team, pit_team], unique=f"{inning}{half}")
        grand_slams = sum(1 for p in pas if p["result"].get("eventType") == "home_run" and p["result"].get("rbi") == 4)
        if grand_slams >= 2:
            yield make_event(game, "two-slams-inning", category="oddity", tier="legendary",
                             title="Two grand slams in one inning",
                             detail=f"{bat_team.name} hit {grand_slams} grand slams in inning {inning}.",
                             teams=[bat_team, pit_team], unique=f"{inning}{half}")


@detector("mlb")
def batter_oddities(game: Game, ctx):
    f = Feed(game)
    hits: dict[int, list[str]] = defaultdict(list)
    slams: dict[int, int] = defaultdict(int)
    side_of: dict[int, str] = {}
    for p in f.plays:
        bid = p["matchup"]["batter"]["id"]
        side_of[bid] = f.batting_side(p)
        e = p["result"].get("eventType")
        if e in HIT_TYPES:
            hits[bid].append(e)
        if e == "home_run" and p["result"].get("rbi") == 4:
            slams[bid] += 1
        desc = p["result"].get("description", "")
        team = f.side_team(f.batting_side(p))
        opp = game.other(team)
        name = p["matchup"]["batter"]["fullName"]
        if e == "home_run" and "inside-the-park" in desc.lower():
            gs = p["result"].get("rbi") == 4
            yield make_event(game, "inside-the-park", category="oddity", tier="epic" if gs else "rare",
                             title=f"Inside-the-park {'grand slam' if gs else 'home run'}: {name}",
                             detail=desc, teams=[team, opp], players=[name],
                             facts=ctx.fact("mlb-itp-grand-slam" if gs else "mlb-itp-hr"),
                             unique=str(p["atBatIndex"]))
        if e == "home_run" and f.position(bid) == "P":
            yield make_event(game, "pitcher-hr", category="oddity", tier="epic",
                             title=f"Pitcher {name} homers", detail=desc, teams=[team, opp], players=[name],
                             unique=str(p["atBatIndex"]))
        if e in TP_TYPES:
            unassisted = "unassisted" in desc.lower()
            yield make_event(game, "triple-play", category="oddity",
                             tier="legendary" if unassisted else "rare",
                             title="UNASSISTED triple play!" if unassisted else "Triple play",
                             detail=desc, teams=[opp, team],
                             facts=ctx.fact("mlb-unassisted-tp" if unassisted else "mlb-triple-play"),
                             unique=str(p["atBatIndex"]))
        for ev in p.get("playEvents", []):
            if (ev.get("details") or {}).get("eventType") == "stolen_base_home":
                yield make_event(game, "steal-of-home", category="oddity", tier="rare",
                                 title="Steal of home!", detail=(ev.get("details") or {}).get("description", ""),
                                 teams=[team, opp], facts=ctx.fact("mlb-steal-home"),
                                 unique=f"{p['atBatIndex']}-{ev.get('index')}")

    for bid, hs in hits.items():
        side = side_of[bid]
        team, opp = f.side_team(side), f.side_team(other(side))
        name = f.name(bid)
        if all(h in hs for h in HIT_TYPES):
            runs = [hs[i:i + 4] for i in range(len(hs) - 3)]
            natural = list(HIT_TYPES) in runs
            reverse = list(reversed(HIT_TYPES)) in runs
            if natural:
                label, order, fact = "NATURAL cycle", " — in that exact order", "mlb-natural-cycle"
            elif reverse:
                label, order, fact = "REVERSE natural cycle", " — in exactly the reverse order", "mlb-reverse-cycle"
            else:
                label, order, fact = "cycle", "", "mlb-cycle"
            hits_txt = ("homered, tripled, doubled and singled" if reverse and not natural
                        else "singled, doubled, tripled and homered")
            yield make_event(game, "cycle", category="oddity", tier="legendary" if natural or reverse else "epic",
                             title=f"{name} hits for the {label}",
                             detail=f"{name} ({team.name}) {hits_txt}{order}.",
                             teams=[team, opp], players=[name], facts=ctx.fact(fact), unique=str(bid))
        hr = hs.count("home_run")
        if hr >= 4:
            yield make_event(game, "four-hr", category="oddity", tier="legendary",
                             title=f"{name} hits {hr} home runs", detail=f"{name} ({team.name}) homered {hr} times.",
                             teams=[team, opp], players=[name], facts=ctx.fact("mlb-four-hr-game"), unique=str(bid))
        tier = tiered(len(hs), [(7, "legendary"), (6, "epic")])
        if tier:
            yield make_event(game, "six-hits", category="milestone", tier=tier,
                             title=f"{name}: {len(hs)} hits", detail=f"{name} ({team.name}) had {len(hs)} hits.",
                             teams=[team, opp], players=[name], unique=str(bid))
        if slams.get(bid, 0) >= 2:
            yield make_event(game, "two-slams", category="oddity", tier="legendary",
                             title=f"{name} hits two grand slams",
                             detail=f"{name} ({team.name}) cleared the bases twice in one game.",
                             teams=[team, opp], players=[name], facts=ctx.fact("mlb-two-grand-slams"),
                             unique=str(bid))
        rbi = f.batting_line(side, bid).get("rbi", 0)
        tier = tiered(rbi, [(12, "legendary"), (10, "epic")])
        if tier:
            yield make_event(game, "big-rbi", category="milestone", tier=tier,
                             title=f"{name}: {rbi} RBIs", detail=f"{name} ({team.name}) drove in {rbi}.",
                             teams=[team, opp], players=[name], unique=str(bid))


@detector("mlb")
def pitcher_oddities(game: Game, ctx):
    f = Feed(game)
    decisions = f.ld.get("decisions", {})
    decided = {(decisions.get("winner") or {}).get("id"): "win", (decisions.get("save") or {}).get("id"): "save"}
    for side in ("home", "away"):
        team, opp = f.side_team(side), f.side_team(other(side))
        pitchers = f.box.get(side, {}).get("pitchers", [])
        for pid in pitchers:
            line = f.pitching_line(side, pid)
            name = f.name(pid)
            ks = line.get("strikeOuts", 0)
            tier = tiered(ks, [(20, "legendary"), (18, "epic")])
            if tier:
                yield make_event(game, "big-k", category="milestone", tier=tier,
                                 title=f"{name} strikes out {ks}",
                                 detail=f"{name} ({team.name}) struck out {ks} {opp.name} hitters.",
                                 teams=[team, opp], players=[name], facts=ctx.fact("mlb-strikeouts"), unique=str(pid))
            pos = f.position(pid)
            if pos and pos not in ("P", "TWP"):
                margin = abs(game.home_score - game.away_score)
                decision = decided.get(pid)
                if decision:
                    tier, why = "epic", f"and earned the {decision}"
                elif margin <= 3:
                    tier, why = "rare", f"in a {margin}-run game"
                elif ks >= 2:
                    tier, why = "rare", f"and struck out {ks}"
                else:
                    continue  # mop-up duty in blowouts is common now
                yield make_event(game, "position-player-pitching", category="oddity", tier=tier,
                                 title=f"Position player {name} pitches {why}",
                                 detail=f"{name}, normally a {pos}, took the mound for the {team.name} {why} "
                                        f"({line.get('inningsPitched', '?')} IP, {ks} K).",
                                 teams=[team, opp], players=[name], unique=str(pid))
        # Maddux: a complete-game shutout on fewer than 100 pitches.
        if len(pitchers) == 1 and game.score_of(opp) == 0 and game.winner and game.winner.id == team.id:
            line = f.pitching_line(side, pitchers[0])
            pitches = line.get("numberOfPitches", 999)
            if ip_to_outs(line.get("inningsPitched", "0")) >= 27 and pitches < 100:
                name = f.name(pitchers[0])
                yield make_event(game, "maddux", category="oddity", tier="epic" if pitches < 85 else "rare",
                                 title=f"A Maddux: {name} needs only {pitches} pitches",
                                 detail=f"{name} threw a complete-game shutout on {pitches} pitches.",
                                 teams=[team, opp], players=[name], facts=ctx.fact("mlb-maddux"), unique=side)


@detector("mlb")
def game_oddities(game: Game, ctx):
    f = Feed(game)
    # Scoring in every inning.
    for side in ("home", "away"):
        innings = [inn.get(side) or {} for inn in f.linescore.get("innings", [])]
        batted = [i for i in innings if "runs" in i]
        if len(batted) >= 8 and all((i.get("runs") or 0) > 0 for i in batted):
            team = f.side_team(side)
            yield make_event(game, "every-inning", category="oddity", tier="epic",
                             title=f"{team.short or team.name} score in every inning",
                             detail=f"{team.name} put a run on the board in all {len(batted)} innings they batted.",
                             teams=[team, game.other(team)], facts=ctx.fact("mlb-every-inning"), unique=side)
    # Walk-offs: the strange ones, and the grand slams.
    if not f.plays or not game.winner or game.winner.id != game.home.id:
        return
    last = f.plays[-1]
    if last["about"]["halfInning"] != "bottom":
        return
    e = last["result"].get("eventType")
    trailing_by = None
    before = f.plays[-2]["result"] if len(f.plays) > 1 else {}
    if before:
        trailing_by = (before.get("awayScore", 0) or 0) - (before.get("homeScore", 0) or 0)
    name = last["matchup"]["batter"]["fullName"]
    desc = last["result"].get("description", "")
    if e == "home_run" and last["result"].get("rbi") == 4:
        ultimate = trailing_by == 3
        yield make_event(game, "walkoff-slam", category="oddity", tier="legendary" if ultimate else "epic",
                         title=("ULTIMATE grand slam" if ultimate else "Walk-off grand slam") + f": {name}",
                         detail=desc + (" Down three, last swing, game over." if ultimate else ""),
                         teams=[game.home, game.away], players=[name],
                         facts=ctx.fact("mlb-ultimate-grand-slam" if ultimate else "mlb-walkoff-slam"))
        return
    last_event = ((last.get("playEvents") or [{}])[-1].get("details") or {}).get("eventType")
    weird = {"balk": ("walk-off balk", "legendary"), "catcher_interf": ("walk-off catcher's interference", "legendary"),
             "wild_pitch": ("walk-off wild pitch", "rare"), "passed_ball": ("walk-off passed ball", "epic"),
             "hit_by_pitch": ("walk-off hit-by-pitch", "epic"), "field_error": ("walk-off error", "rare"),
             "stolen_base_home": ("walk-off steal of home", "legendary"),
             "walk": ("walk-off walk", "rare"), "intent_walk": ("walk-off intentional walk", "epic")}
    for kind in (last_event, e):
        if kind in weird:
            label, tier = weird[kind]
            yield make_event(game, "weird-walkoff", category="oddity", tier=tier,
                             title=label[0].upper() + label[1:], detail=desc or label,
                             teams=[game.home, game.away], facts=ctx.fact(f"mlb-walkoff-{kind}"))
            return
