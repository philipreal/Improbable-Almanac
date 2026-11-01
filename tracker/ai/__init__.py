"""Claude-powered helpers. Problems are surfaced as GitHub Actions annotations so a missing
key or a failing API call shows up on the run's summary page instead of passing silently."""
import logging
import os

log = logging.getLogger(__name__)


def annotate(level: str, message: str):
    """level: 'warning' or 'error'."""
    getattr(log, level)(message)
    if os.environ.get("GITHUB_ACTIONS"):
        print(f"::{level}::{message}", flush=True)


def have_key(task: str) -> bool:
    if os.environ.get("ANTHROPIC_API_KEY"):
        return True
    annotate("warning", f"ANTHROPIC_API_KEY is not set, so {task} was skipped. Add it under "
                        "Settings > Secrets and variables > Actions > Repository secrets.")
    return False
