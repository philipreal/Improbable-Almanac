# The Improbable Almanac

A birthday-gift dashboard that catches rare and strange sports events as they happen: scorigamis,
immaculate innings, one-point safeties, quadruple-doubles, kick-sixes, walk-off balks and more. It
watches every MLB, NFL, NBA and FBS college football game, keeps a spotlight on Dad's teams, and
has Claude scout the wider sports world for anything historic.

It runs itself: GitHub Actions checks the games every 15 minutes and publishes a static site to
GitHub Pages. No server, nothing to maintain.

## One-time setup (about 15 minutes)

1. **Set Dad's teams.** Edit `config/teams.yaml`. Team codes are ESPN abbreviations (`GB`, `MIL`,
   `WIS`...); MLB uses MLB's (`AZ` for Arizona, otherwise the usual ones). Set `name:` to what the
   birthday card should call him.
2. **Create a GitHub repo** (public, so Actions minutes are free) and push this folder to `main`.
3. **Add secrets** under *Settings → Secrets and variables → Actions*:
   - `ANTHROPIC_API_KEY` — powers the "why this is rare" notes and the news scouting.
     Expected cost: a few dollars a month at most (Haiku triages headlines, Sonnet writes notes).
4. **Turn on Pages:** *Settings → Pages → Build and deployment → Source: GitHub Actions*.
5. **Run it once:** *Actions → Poll games → Run workflow*. Then run *Daily chores* once to write
   notes for the season's backlog of events. The site URL appears on the workflow run.
6. Optional: point a custom domain at it, and print a card with a QR code to the URL.

## What runs when

| Workflow | Schedule | What it does |
|---|---|---|
| `poll.yml` | every 15 min | Fetches scoreboards, runs detectors on newly finished games, live banners (no-hitter watch, scorigami watch), publishes the site |
| `news.yml` | every 3 h | Collects headlines + stat-account posts, Claude keeps only genuinely rare happenings |
| `daily.yml` | 10:30 UTC | Runs the tests, MLB career milestones, fills in missing notes, weekly heartbeat |

GitHub's cron is best-effort, so expect events within roughly 15–30 minutes of the final whistle.

## Running locally

```bash
python -m venv .venv && .venv/Scripts/pip install -r requirements.txt   # (bin/ on Mac/Linux)
python -m tracker poll                       # one polling pass
python -m tracker news --dry-run             # see what Claude would keep (needs ANTHROPIC_API_KEY)
python -m tracker backfill --since 2026-03-20 # re-scan a date range
python -m pytest -q tests                    # detectors vs. famous real games
python -m http.server 8765 --directory site  # view the site
```

## How it's built

- `tracker/sources/` — ESPN's public scoreboard/summary API (NFL, college, NBA), MLB StatsAPI
  (pitch-by-pitch), news RSS + Bluesky. All ESPN-specific parsing lives in `espn.py`.
- `tracker/detectors/` — one function per oddity, registered with `@detector(...)`. Each returns
  `Event`s with a tier (Legendary / Epic / Rare) and a category (Never before / Oddity / Milestone /
  Wild game). "Never before" and "Oddity" rank a notch higher, by request.
- `tracker/streaks.py` — streaks that span games: MLB hitting, on-base and scoreless-innings
  streaks (scoreless innings follow MLB's official inning-by-inning rule), the postseason relief
  record, and MLB/NBA team win and losing streaks. `python -m tracker rebuild-streaks` recounts
  them from scratch, including the last three postseasons.
- `tracker/rarity/` — scorigami tables (every final score since 1920 for the NFL, 1873 for college,
  1901 for MLB) and curated facts in `seed/rarity_facts.yaml`. Claude may only use these facts and
  the detector's own numbers when writing notes, so it never invents history.
- `site/` — static HTML/CSS/JS reading `site/data/*.json`. Installable on a phone home screen.

### Adding a detector

```python
@detector("nba")
def my_oddity(game, ctx):
    if something_rare(game):
        yield make_event(game, "my-oddity", category="oddity", tier="epic",
                         title="...", detail="...", facts=ctx.fact("my-oddity"))
```

Add a fixture of a real game where it happened (`tests/make_fixtures.py`) and a line in
`tests/test_detectors.py`.

### False alarm?

Add the event's `key` to `config/overrides.yaml` under `hide:` and push.

### Rebuilding the scorigami history

`python -m seed.build_scorigami nfl cfb mlb` rebuilds through the end of the 2025 seasons; the
live tracker adds 2026 games on top. Before next season, bump `CUTOFF_SEASON` and update the counts
in `seed/rarity_facts.yaml`.

## Data credits

ESPN (unofficial public API), MLB Advanced Media StatsAPI, nflverse, FiveThirtyEight's NFL Elo
dataset (CC BY 4.0), plus the news outlets and Bluesky accounts listed in `tracker/sources/news.py`.
