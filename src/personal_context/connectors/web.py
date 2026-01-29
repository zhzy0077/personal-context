"""Web content fetcher with content extraction."""

import httpx
from bs4 import BeautifulSoup
from typing import Dict, Any


async def fetch_web_content(url: str) -> Dict[str, Any]:
    """
    Fetch and extract content from a web page.

    Args:
        url: URL to fetch

    Returns:
        Dictionary with title and content
    """
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        response = await client.get(url)
        response.raise_for_status()

        # Parse HTML
        soup = BeautifulSoup(response.text, "html.parser")

        # Extract title
        title = ""
        if soup.title and soup.title.string:
            title = soup.title.string.strip()
        elif soup.find("h1"):
            title = soup.find("h1").get_text().strip()

        # Remove script and style elements
        for script in soup(["script", "style", "nav", "footer", "header"]):
            script.decompose()

        # Extract main content
        # Try to find main content area
        main_content = None
        for selector in ["main", "article", '[role="main"]', ".content", "#content"]:
            main_content = soup.select_one(selector)
            if main_content:
                break

        if not main_content:
            main_content = soup.body if soup.body else soup

        # Get text content
        content = main_content.get_text(separator="\n", strip=True)

        # Clean up excessive whitespace
        lines = [line.strip() for line in content.split("\n") if line.strip()]
        content = "\n\n".join(lines)

        return {
            "title": title or "Untitled",
            "content": content,
            "url": str(response.url),  # Final URL after redirects
        }
