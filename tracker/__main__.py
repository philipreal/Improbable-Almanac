"""Command line entry point.

    python -m tracker poll                      # check for newly finished games (every 15 min)
    python -m tracker news [--dry-run]          # triage sports news with Claude (every few hours)
    python -m tracker milestones                # MLB career milestones (daily)
    python -m tracker backfill --since 2026-03-25 [--until 2026-10-24] [--leagues mlb nfl] [--blurbs]
    python -m tracker blurbs                    # write notes for any rare+ events missing one
    python -m tracker rebuild-streaks           # recount cross-game streaks from scratch
"""
import argparse
import logging
from datetime import date

from . import pipeline
from .models import LEAGUES


def main():
    p = argparse.ArgumentParser(prog="tracker")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("poll")
    n = sub.add_parser("news")
    n.add_argument("--dry-run", action="store_true")
    sub.add_parser("milestones")
    sub.add_parser("blurbs")
    sub.add_parser("rebuild-streaks")
    b = sub.add_parser("backfill")
    b.add_argument("--since", required=True, type=date.fromisoformat)
    b.add_argument("--until", type=date.fromisoformat, default=date.today())
    b.add_argument("--leagues", nargs="+", default=list(LEAGUES), choices=LEAGUES)
    b.add_argument("--blurbs", action="store_true")
    b.add_argument("--force", action="store_true", help="re-run detectors on already-processed games")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if args.cmd == "poll":
        pipeline.poll()
    elif args.cmd == "news":
        pipeline.news(dry_run=args.dry_run)
    elif args.cmd == "milestones":
        pipeline.daily_milestones()
    elif args.cmd == "blurbs":
        pipeline.fill_missing_blurbs()
    elif args.cmd == "rebuild-streaks":
        pipeline.rebuild_streaks()
    elif args.cmd == "backfill":
        pipeline.backfill(args.since, args.until, leagues=args.leagues, blurbs=args.blurbs, force=args.force)


if __name__ == "__main__":
    main()
