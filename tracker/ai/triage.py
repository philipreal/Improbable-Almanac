"""Claude reads candidate headlines and keeps only the genuinely rare happenings."""
import logging
import os
from typing import Literal

import anthropic
from pydantic import BaseModel

from ..models import Event

log = logging.getLogger(__name__)

MODEL = os.environ.get("ALMANAC_TRIAGE_MODEL", "claude-haiku-5-5")
BATCH = 40
KEEP_AT = 4

SYSTEM = """You are the editor of a sports-oddity almanac made for a fan who loves rare and strange \
events: things that have never happened before, bizarre stat quirks, records, and wild games.

For each candidate item, decide whether it describes a genuinely rare sporting event that actually \
happened (not a preview, opinion piece, rumor, betting tip, injury or transaction news). Score rarity:
5 = historic/never-before-seen, 4 = very rare (a handful of times per decade or a notable record),
3 = unusual but happens most seasons, 2 = mildly interesting, 1 = not rare.

Rules:
- Judge only from the item's own text. Do not add facts it doesn't state.
- headline: a crisp 4-10 word title. summary: one or two sentences restating the claim from the text.
- league: mlb, nfl, nba or cfb (FBS college football) if it's one of those, else other.
- duplicate_of: if the item is about the same event as one in the 'already covered' list, give that key."""


class Verdict(BaseModel):
    id: str
    rarity: int
    is_event: bool
    league: Literal["mlb", "nfl", "nba", "cfb", "other"]
    sport: str
    category: Literal["never-before", "oddity", "milestone", "wild"]
    headline: str
    summary: str
    duplicate_of: str | None = None


class Verdicts(BaseModel):
    verdicts: list[Verdict]


def triage(items: list[dict], covered: list[dict]) -> list[Event]:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        log.warning("ANTHROPIC_API_KEY not set; skipping news triage")
        return []
    client = anthropic.Anthropic()
    covered_text = "\n".join(f"- {e['key']}: {e['title']}" for e in covered[:80]) or "(none)"
    by_id = {it["id"]: it for it in items}
    kept: list[Event] = []
    for i in range(0, len(items), BATCH):
        chunk = items[i:i + BATCH]
        listing = "\n\n".join(f"id: {it['id']}\nsource: {it['source']}\ntitle: {it['title']}\ntext: {it['text']}"
                              for it in chunk)
        try:
            resp = client.messages.parse(
                model=MODEL, max_tokens=8000, system=SYSTEM, output_config={"effort": "low"},
                messages=[{"role": "user", "content":
                           f"Already covered:\n{covered_text}\n\nCandidates:\n\n{listing}\n\n"
                           "Return a verdict for every candidate id."}],
                output_format=Verdicts,
            )
        except anthropic.APIError:
            log.exception("triage request failed")
            continue
        if resp.stop_reason == "refusal" or not resp.parsed_output:
            continue
        log.info("triage: %d verdicts (%s in / %s out tokens)", len(resp.parsed_output.verdicts),
                 resp.usage.input_tokens, resp.usage.output_tokens)
        for v in resp.parsed_output.verdicts:
            it = by_id.get(v.id)
            if not it or not v.is_event or v.rarity < KEEP_AT or v.duplicate_of:
                continue
            kept.append(Event(
                key=f"news:{v.id}", league=v.league, category=v.category,
                tier="legendary" if v.rarity >= 5 else "epic",
                title=v.headline, detail=v.summary, date=it["date"], link=it["url"],
                source="news", source_name=it["source"], sport=v.sport, blurb=v.summary,
            ))
    return kept
