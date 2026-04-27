"""
researcher.py - Deep web research agent using DuckDuckGo + httpx
"""
import re
import asyncio
import logging
import httpx
from bs4 import BeautifulSoup
from llm import chat

logger = logging.getLogger(__name__)

SEARCH_URL = "https://html.duckduckgo.com/html/"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}


class ResearchAgent:
    def __init__(self, memory=None):
        self.memory = memory

    async def _search(self, query: str, num_results: int = 5) -> list[dict]:
        """DuckDuckGo HTML search — no API key needed."""
        results = []
        try:
            async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True, timeout=10) as client:
                resp = await client.post(SEARCH_URL, data={"q": query, "b": ""})
                soup = BeautifulSoup(resp.text, "html.parser")
                for result in soup.select(".result__body")[:num_results]:
                    title_el = result.select_one(".result__title")
                    url_el = result.select_one(".result__url")
                    snippet_el = result.select_one(".result__snippet")
                    if title_el and url_el:
                        results.append({
                            "title": title_el.get_text(strip=True),
                            "url": url_el.get_text(strip=True),
                            "snippet": snippet_el.get_text(strip=True) if snippet_el else ""
                        })
        except Exception as e:
            logger.error(f"[Research] Search error: {e}")
        return results

    async def _fetch_page(self, url: str, max_chars: int = 3000) -> str:
        """Fetch a URL and extract clean text."""
        if not url.startswith("http"):
            url = "https://" + url
        try:
            async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True, timeout=10) as client:
                resp = await client.get(url)
                soup = BeautifulSoup(resp.text, "html.parser")
                for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
                    tag.decompose()
                text = soup.get_text(separator="\n", strip=True)
                text = re.sub(r'\n{3,}', '\n\n', text)
                return text[:max_chars]
        except Exception as e:
            return f"[Fetch error: {e}]"

    async def research(self, topic: str, depth: str = "standard") -> str:
        """
        Research a topic at the specified depth.
        depth: quick (3 sources, 200 words), standard (5 sources, 500 words), deep (10 sources, full)
        """
        depth_config = {
            "quick": {"sources": 3, "max_words": 200, "fetch_pages": 1},
            "standard": {"sources": 5, "max_words": 500, "fetch_pages": 3},
            "deep": {"sources": 10, "max_words": 2000, "fetch_pages": 6},
        }
        cfg = depth_config.get(depth, depth_config["standard"])

        logger.info(f"[Research] Researching '{topic}' ({depth})")

        results = await self._search(topic, cfg["sources"])
        if not results:
            return f"No search results found for '{topic}'."

        # Fetch top pages for content
        content_parts = []
        fetch_tasks = [self._fetch_page(r["url"]) for r in results[:cfg["fetch_pages"]]]
        pages = await asyncio.gather(*fetch_tasks)

        for i, (result, page) in enumerate(zip(results, pages)):
            content_parts.append(
                f"Source {i+1}: {result['title']}\nURL: {result['url']}\n"
                f"Snippet: {result['snippet']}\nContent: {page}\n---"
            )

        # Add remaining snippets
        for result in results[cfg["fetch_pages"]:]:
            content_parts.append(f"Source: {result['title']}\n{result['snippet']}\n---")

        raw_content = "\n\n".join(content_parts)

        # Use Sonnet or Opus for synthesis
        use_opus = depth == "deep"
        tier = 3 if use_opus else 2

        prompt = (
            f"Research topic: {topic}\n\nSources:\n{raw_content[:8000]}\n\n"
            f"Synthesise a {'comprehensive' if depth == 'deep' else 'concise'} research report. "
            f"Include key findings, relevant data, and cite sources. "
            f"Target length: {cfg['max_words']} words. "
            f"Format: clear sections with headers if deep research."
        )

        result = chat([{"role": "user", "content": prompt}], tier=tier)
        report = result["content"]

        # Save to notes if memory available
        if self.memory:
            self.memory.add_note(
                title=f"Research: {topic}",
                content=report,
                topic="research",
                tags=f"research,{topic.replace(' ', '_')}"
            )

        return report
