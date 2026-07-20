"""
scrape_url — HTTP GET a una URL y devuelve texto limpio + links.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List

from . import _http


def scrape_url(url: str, timeout: float = 20.0, max_chars: int = 8000) -> Dict[str, Any]:
    """Devuelve {url, status, text, title, links}.

    Trunca el texto a `max_chars` para no reventar el contexto del modelo.
    """
    try:
        r = _http.get(url, timeout=timeout)
        if r.status_code >= 400:
            return {"url": url, "status": r.status_code, "error": f"HTTP {r.status_code}"}
    except Exception as e:
        return {"url": url, "error": str(e)[:200]}

    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(r.text, "html.parser")
        title = (soup.title.string if soup.title else "").strip()
        text = soup.get_text(" ", strip=True)
        text = re.sub(r"\s+", " ", text)
        links = []
        for a in soup.find_all("a", href=True):
            links.append({"text": a.get_text(" ", strip=True)[:80], "href": a["href"]})
        return {
            "url": url,
            "status": 200,
            "title": title,
            "text": text[:max_chars],
            "links": links[:30],
        }
    except Exception as e:
        return {"url": url, "error": f"parse_failed: {e}"}
