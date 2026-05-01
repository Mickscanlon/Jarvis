"""
news.py - RSS news aggregation and briefing generation
"""
import os
import logging
from datetime import datetime
from typing import Optional

import feedparser
from llm import chat

logger = logging.getLogger(__name__)

RSS_FEEDS = [
    ("ABC News AU", "https://www.abc.net.au/news/feed/51120/rss.xml"),
    ("ABC Finance", "https://www.abc.net.au/news/feed/2943006/rss.xml"),
    ("Reuters World", "https://feeds.reuters.com/reuters/worldNews"),
    ("BBC News", "http://feeds.bbci.co.uk/news/rss.xml"),
    ("Guardian AU", "https://www.theguardian.com/australia-news/rss"),
]

USER_INTERESTS = ["technology", "business", "property", "victoria", "bendigo", "australia"]


def _fetch_feed(url: str, limit: int = 5) -> list[dict]:
    try:
        import socket
        old_timeout = socket.getdefaulttimeout()
        socket.setdefaulttimeout(8)
        try:
            feed = feedparser.parse(url)
        finally:
            socket.setdefaulttimeout(old_timeout)
        items = []
        for entry in feed.entries[:limit]:
            items.append({
                "title": entry.get("title", ""),
                "summary": entry.get("summary", "")[:300],
                "published": entry.get("published", ""),
                "link": entry.get("link", ""),
            })
        return items
    except Exception as e:
        logger.warning(f"[News] Feed error {url}: {e}")
        return []


def fetch_all_news(max_per_feed: int = 3) -> list[dict]:
    """Fetch from all configured RSS feeds."""
    all_items = []
    for name, url in RSS_FEEDS:
        items = _fetch_feed(url, max_per_feed)
        for item in items:
            item["source"] = name
        all_items.extend(items)
    return all_items


def get_morning_briefing(memory=None) -> dict:
    """Generate a morning news briefing. Returns dict with summary and items."""
    items = fetch_all_news()
    if not items:
        return {"summary": "No news available this morning.", "items": []}

    # Format for LLM
    news_text = "\n".join(
        f"[{item['source']}] {item['title']}: {item['summary']}"
        for item in items[:15]
    )

    result = chat([
        {"role": "user", "content":
         f"Summarise these news stories for a voice morning briefing. "
         f"Pick the 3 most significant stories (especially those relevant to Australia, "
         f"technology, or business). Keep it to 3 sentences total — one per story. "
         f"Conversational tone, no bullet points.\n\n{news_text}"}
    ], tier=2)

    summary = result["content"]

    if memory:
        memory.add_note(
            title=f"Morning Briefing {datetime.now().strftime('%Y-%m-%d')}",
            content=summary + "\n\n---\n" + news_text[:2000],
            topic="news"
        )

    return {"summary": summary, "items": items[:10]}


def get_latest_briefing(memory) -> dict:
    """Get the most recent stored briefing or generate a fresh one."""
    try:
        notes = memory.get_notes(5)
        for note in notes:
            if note.get("topic") == "news":
                return {"summary": note["content"][:500], "title": note["title"]}
    except Exception:
        pass
    return get_morning_briefing(memory)
