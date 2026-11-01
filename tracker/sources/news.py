"""Headlines from sports news feeds and stat-nerd social accounts, for the 'Elsewhere' column."""
import hashlib
import logging
import re
from datetime import datetime, timedelta, timezone

import feedparser

from ..http import get_json, session

log = logging.getLogger(__name__)

RSS_FEEDS = {
    "ESPN": "https://www.espn.com/espn/rss/news",
    "ESPN Soccer": "https://www.espn.com/espn/rss/soccer/news",
    "CBS Sports": "https://www.cbssports.com/rss/headlines/",
    "Yahoo Sports": "https://sports.yahoo.com/rss/",
    "BBC Sport": "https://feeds.bbci.co.uk/sport/rss.xml",
    "The Guardian": "https://www.theguardian.com/sport/rss",
    "MLB.com": "https://www.mlb.com/feeds/news/rss.xml",
    "r/sports": "https://www.reddit.com/r/sports/top/.rss?t=day",
}
# Accounts that post nothing but weird stats, so they skip the keyword filter.
BLUESKY = {
    "Codify Baseball": "codifybaseball.bsky.social",
    "Jayson Stark": "jaysonst.bsky.social",
    "NFL Research": "nflresearch.bsky.social",
}
RARE_WORDS = re.compile(
    r"first time|first ever|first-ever|since 1[89]\d\d|since 20[01]\d|never before|never been|only the \w+|"
    r"\bonly\b.*\bever\b|record|scorigami|history|unprecedented|historic|longest|youngest|oldest|"
    r"no-hitter|perfect game|immaculate|hat trick|\bodd\b|bizarre|strangest|wildest|improbable",
    re.I,
)


def _id(url: str, text: str) -> str:
    return hashlib.sha1((url or text).encode()).hexdigest()[:16]


def _strip(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html or "")).strip()


def collect(hours: int = 30) -> list[dict]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    items = []
    for name, url in RSS_FEEDS.items():
        try:
            resp = session().get(url, timeout=20)
            feed = feedparser.parse(resp.content)
        except Exception as e:
            log.warning("feed %s failed: %s", name, e)
            continue
        for entry in feed.entries:
            when = entry.get("published_parsed") or entry.get("updated_parsed")
            published = datetime(*when[:6], tzinfo=timezone.utc) if when else datetime.now(timezone.utc)
            if published < cutoff:
                continue
            title = _strip(entry.get("title", ""))
            summary = _strip(entry.get("summary", ""))[:400]
            if not RARE_WORDS.search(f"{title} {summary}"):
                continue
            items.append({"id": _id(entry.get("link", ""), title), "source": name, "url": entry.get("link", ""),
                          "title": title, "text": summary, "date": published.isoformat()})
    for name, handle in BLUESKY.items():
        try:
            data = get_json("https://public.api.bsky.app/xrpc/app.bsky.feed.getAuthorFeed",
                            params={"actor": handle, "limit": 30, "filter": "posts_no_replies"})
        except Exception as e:
            log.warning("bluesky %s failed: %s", handle, e)
            continue
        for item in data.get("feed", []):
            if item.get("reason"):  # reposts
                continue
            post = item.get("post", {})
            rec = post.get("record", {})
            created = rec.get("createdAt", "")
            try:
                published = datetime.fromisoformat(created.replace("Z", "+00:00"))
            except ValueError:
                continue
            if published < cutoff:
                continue
            rkey = post.get("uri", "").rsplit("/", 1)[-1]
            url = f"https://bsky.app/profile/{handle}/post/{rkey}"
            text = rec.get("text", "")
            items.append({"id": _id(url, text), "source": name, "url": url, "title": text[:140],
                          "text": text[:600], "date": published.isoformat()})
    log.info("news: %d candidate items", len(items))
    return items
