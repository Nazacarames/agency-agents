"""
web_search — búsqueda web. Usa Serper.dev si SERPER_API_KEY está en el
entorno, si no cae a DuckDuckGo HTML (gratis, menos cobertura).
"""
from __future__ import annotations

import os
import urllib.parse
from typing import Any, Dict, List

import httpx

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")


def _serper_search(query: str, n: int) -> List[Dict[str, Any]]:
    key = os.environ.get("SERPER_API_KEY", "")
    if not key:
        return []
    try:
        r = httpx.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": key, "Content-Type": "application/json"},
            json={"q": query, "num": n},
            timeout=15.0,
        )
        if r.status_code >= 400:
            return []
        data = r.json()
        out = []
        for item in data.get("organic", [])[:n]:
            out.append({
                "title": item.get("title", ""),
                "url": item.get("link", ""),
                "snippet": item.get("snippet", ""),
            })
        return out
    except Exception:
        return []


def _ddg_search(query: str, n: int) -> List[Dict[str, Any]]:
    """DuckDuckGo HTML — gratis, sin API key. Útil como fallback."""
    try:
        r = httpx.get(
            "https://html.duckduckgo.com/html/?" + urllib.parse.urlencode({"q": query}),
            headers={"User-Agent": UA},
            timeout=15.0,
            follow_redirects=True,
        )
        if r.status_code >= 400:
            return []
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(r.text, "html.parser")
        out = []
        for res in soup.select("div.result"):
            a = res.select_one("a.result__a")
            snippet = res.select_one("a.result__snippet")
            if not a:
                continue
            href = a.get("href", "")
            if "uddg=" in href:
                # ddg wrap URL
                try:
                    href = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)["uddg"][0]
                except Exception:
                    pass
            out.append({
                "title": a.get_text(" ", strip=True),
                "url": href,
                "snippet": (snippet.get_text(" ", strip=True) if snippet else ""),
            })
            if len(out) >= n:
                break
        return out
    except Exception:
        return []


def web_search(query: str, n: int = 5) -> List[Dict[str, Any]]:
    """Devuelve hasta `n` resultados [{title, url, snippet}, ...].

    Primero intenta Serper (10 USD/mes, 2500 búsq). Si no hay key o falla,
    cae a DuckDuckGo HTML.
    """
    out = _serper_search(query, n)
    if out:
        return out
    return _ddg_search(query, n)
