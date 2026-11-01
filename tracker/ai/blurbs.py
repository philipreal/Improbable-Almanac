"""Short 'why this is rare' notes for detected events, written by Claude from verified facts only."""
import logging
import os

import anthropic
from pydantic import BaseModel

from . import annotate, have_key

log = logging.getLogger(__name__)

MODEL = os.environ.get("ALMANAC_BLURB_MODEL", "claude-sonnet-5-5")
BATCH = 15

SYSTEM = """You write one-to-two sentence notes for a sports-oddity dashboard made as a birthday gift \
for a lifelong fan who loves rare and strange statistics.

Rules:
- Use ONLY the facts provided for each event. Never add historical counts, dates, records or \
"first time since" claims that aren't in the facts. If the facts don't say how rare it is, explain \
what makes this kind of event unusual in general terms instead (no numbers).
- Be vivid and a little playful, like a great stat-head broadcaster. No hashtags, no emoji.
- Max 45 words per note."""


class Note(BaseModel):
    key: str
    note: str


class Notes(BaseModel):
    notes: list[Note]


def _event_text(e: dict) -> str:
    facts = "\n".join(f"  - {f}" for f in e.get("facts") or []) or "  (none)"
    return (f"key: {e['key']}\nleague: {e['league']}\ntitle: {e['title']}\ndetail: {e['detail']}\n"
            f"game: {e.get('matchup', '')} on {e['date'][:10]}\nfacts:\n{facts}")


def fill(events: list[dict]):
    """Mutates each event dict in place, setting 'blurb'."""
    if not have_key("writing notes"):
        return
    client = anthropic.Anthropic()
    for i in range(0, len(events), BATCH):
        chunk = events[i:i + BATCH]
        prompt = "Write a note for each event below. Return every key.\n\n" + \
                 "\n\n".join(_event_text(e) for e in chunk)
        try:
            resp = client.messages.parse(
                model=MODEL, max_tokens=4000, system=SYSTEM,
                output_config={"effort": "low"},
                messages=[{"role": "user", "content": prompt}],
                output_format=Notes,
            )
        except anthropic.APIError as e:
            annotate("error", f"Claude blurb request failed: {e}")
            continue
        if resp.stop_reason == "refusal" or not resp.parsed_output:
            continue
        by_key = {n.key: n.note.strip() for n in resp.parsed_output.notes}
        for e in chunk:
            if by_key.get(e["key"]):
                e["blurb"] = by_key[e["key"]]
        log.info("blurbs: %d written (%s in / %s out tokens)", len(by_key),
                 resp.usage.input_tokens, resp.usage.output_tokens)
