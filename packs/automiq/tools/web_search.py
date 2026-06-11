"""
web_search — búsqueda web resiliente para correr desde un datacenter (Render).

Orden de proveedores (usa el primero que tenga key / responda):
  1. Serper.dev          (SERPER_API_KEY)   — Google, barato y confiable
  2. Brave Search API    (BRAVE_API_KEY)    — free tier 2000/mes, anda desde datacenter
  3. Tavily              (TAVILY_API_KEY)   — optimizado para agentes LLM
  4. DuckDuckGo HTML/Lite (sin key)         — gratis pero las IP de datacenter
                                              suelen recibir 202 (anti-bot) → poco fiable

IMPORTANTE: las IP de Render/datacenter reciben 202 de DuckDuckGo (challenge
anti-bot). Por eso `web_search` queda vacío en producción salvo que haya una
API key. Tratamos cualquier status != 200 como fallo (no parseamos el challenge).
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
            json={"q": query, "num": n, "gl": "ar", "hl": "es"},
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


def _brave_search(query: str, n: int) -> List[Dict[str, Any]]:
    """Brave Search API — free tier 2000 queries/mes, confiable desde datacenter."""
    key = os.environ.get("BRAVE_API_KEY", "")
    if not key:
        return []
    try:
        r = httpx.get(
            "https://api.search.brave.com/res/v1/web/search",
            headers={"X-Subscription-Token": key, "Accept": "application/json"},
            params={"q": query, "count": n, "country": "ar", "search_lang": "es"},
            timeout=15.0,
        )
        if r.status_code >= 400:
            return []
        data = r.json()
        out = []
        for item in (data.get("web", {}).get("results", []) or [])[:n]:
            out.append({
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "snippet": item.get("description", ""),
            })
        return out
    except Exception:
        return []


def _tavily_search(query: str, n: int) -> List[Dict[str, Any]]:
    """Tavily — search API pensada para agentes LLM. Free tier disponible."""
    key = os.environ.get("TAVILY_API_KEY", "")
    if not key:
        return []
    try:
        r = httpx.post(
            "https://api.tavily.com/search",
            json={"api_key": key, "query": query, "max_results": n,
                  "search_depth": "basic"},
            timeout=20.0,
        )
        if r.status_code >= 400:
            return []
        data = r.json()
        out = []
        for item in (data.get("results", []) or [])[:n]:
            out.append({
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "snippet": item.get("content", "")[:300],
            })
        return out
    except Exception:
        return []


def _parse_ddg_html(html: str, n: int) -> List[Dict[str, Any]]:
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for res in soup.select("div.result, div.result__body, tr"):
        a = res.select_one("a.result__a") or res.select_one("a.result-link")
        snippet = res.select_one("a.result__snippet, td.result-snippet")
        if not a:
            continue
        href = a.get("href", "")
        if "uddg=" in href:
            try:
                href = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)["uddg"][0]
            except Exception:
                pass
        if not href.startswith("http"):
            continue
        out.append({
            "title": a.get_text(" ", strip=True),
            "url": href,
            "snippet": (snippet.get_text(" ", strip=True) if snippet else ""),
        })
        if len(out) >= n:
            break
    return out


def _ddg_search(query: str, n: int) -> List[Dict[str, Any]]:
    """DuckDuckGo sin key. Prueba HTML y luego Lite. Status != 200 = fallo
    (las IP de datacenter reciben 202 con un challenge anti-bot que NO parseamos).
    """
    endpoints = [
        "https://html.duckduckgo.com/html/?",
        "https://lite.duckduckgo.com/lite/?",
    ]
    for base in endpoints:
        try:
            r = httpx.get(
                base + urllib.parse.urlencode({"q": query, "kl": "ar-es"}),
                headers={"User-Agent": UA, "Accept-Language": "es-AR,es;q=0.9"},
                timeout=15.0,
                follow_redirects=True,
            )
            # 202 = challenge anti-bot (típico desde datacenter): no sirve, seguir
            if r.status_code != 200:
                continue
            out = _parse_ddg_html(r.text, n)
            if out:
                return out
        except Exception:
            continue
    return []


def web_search(query: str, n: int = 5) -> List[Dict[str, Any]]:
    """Devuelve hasta `n` resultados [{title, url, snippet}, ...].

    Cae en cascada por los proveedores con key configurada; DuckDuckGo es el
    último recurso (poco fiable desde datacenter por el 202 anti-bot).
    """
    for provider in (_serper_search, _brave_search, _tavily_search, _ddg_search):
        out = provider(query, n)
        if out:
            return out
    return []
