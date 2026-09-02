"""
scrape_url — HTTP GET a una URL y devuelve texto limpio + links.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List

from . import _http


def scrape_url(url: str, timeout: float = 20.0, max_chars: int = 8000) -> Dict[str, Any]:
    """Devuelve {url, status, text, title, links}.

    httpx directo primero (rápido y trae los `links` para navegar a /contacto).
    Si el sitio bloquea (403 anti-bot típico desde datacenter) o es un SPA que
    devuelve el HTML vacío, cae a Jina Reader (`r.jina.ai`), que lee la página
    igual, gratis. Trunca el texto a `max_chars` para no reventar el contexto.
    """
    r, err, thin = None, "", None
    try:
        r = _http.get(url, timeout=timeout)
    except Exception as e:
        err = str(e)[:200]

    if r is not None and r.status_code < 400:
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(r.text, "html.parser")
            title = (soup.title.string if soup.title else "").strip()
            text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
            links = [{"text": a.get_text(" ", strip=True)[:80], "href": a["href"]}
                     for a in soup.find_all("a", href=True)]
            result = {"url": url, "status": 200, "title": title,
                      "text": text[:max_chars], "links": links[:30]}
            if len(text) >= 200:
                return result
            thin = result  # SPA vacío → probamos Jina antes de rendirnos
        except Exception as e:
            err = f"parse_failed: {e}"

    # Fallback datacenter-proof: Jina Reader lee la página aunque httpx reciba 403.
    from .web_search import read_page
    md = read_page(url, max_chars=max_chars)
    if md:
        return {"url": url, "status": 200, "title": "", "text": md,
                "links": [], "via": "jina"}
    if thin is not None:
        return thin
    if r is not None:
        return {"url": url, "status": r.status_code, "error": err or f"HTTP {r.status_code}"}
    return {"url": url, "error": err or "unreachable"}
