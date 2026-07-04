"""
trends_client — cliente mínimo del MCP de TrendsMCP (trendsmcp.ai) por HTTP/JSON-RPC.

El MCP expone get_trends / get_growth / get_top_trends sobre Google/YouTube/TikTok/
Reddit/etc. Como los agentes de contenido corren por GLM (completion directa, SIN
cliente MCP), NO podemos enchufar el MCP a ellos: en cambio llamamos las tools por
HTTP y su resultado se inyecta al playbook (igual patrón que competitor_study).

Auth: Bearer TRENDS_API_KEY. Stateless (sin sesión). Free tier 100 req/mes → usar
frugal (refresh semanal). Best-effort: si falla, devuelve None/[].
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import httpx

from ..config import get_settings
from ..log import get_logger

log = get_logger("trends_client")

_PREFIX = "trendsMCP___"


def enabled() -> bool:
    return bool(getattr(get_settings(), "trends_api_key", ""))


def _rpc(client: httpx.Client, url: str, key: str, method: str,
         params: Optional[Dict] = None, _id: int = 1) -> Dict[str, Any]:
    body = {"jsonrpc": "2.0", "id": _id, "method": method, "params": params or {}}
    r = client.post(url, json=body, headers={
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    })
    r.raise_for_status()
    raw = r.text
    if "data:" in raw:            # respuesta SSE → tomar la línea data:
        for ln in raw.splitlines():
            if ln.startswith("data:"):
                raw = ln[5:].strip()
                break
    return json.loads(raw)


def _tool(tool: str, args: Dict[str, Any]) -> Optional[Any]:
    """Llama una tool del MCP y devuelve el payload ya parseado (o None)."""
    s = get_settings()
    key = getattr(s, "trends_api_key", "")
    url = getattr(s, "trends_mcp_url", "https://api.trendsmcp.ai/mcp")
    if not key:
        return None
    try:
        with httpx.Client(timeout=45) as c:
            _rpc(c, url, key, "initialize", {
                "protocolVersion": "2025-03-26", "capabilities": {},
                "clientInfo": {"name": "automiq", "version": "1.0"}})
            r = _rpc(c, url, key, "tools/call",
                     {"name": _PREFIX + tool, "arguments": args}, _id=2)
        if "error" in r:
            log.warning("trends_tool_error", tool=tool, msg=str(r["error"])[:150])
            return None
        content = (r.get("result") or {}).get("content", [])
        txt = "".join(x.get("text", "") for x in content if x.get("type") == "text")
        try:
            data = json.loads(txt)
        except Exception:
            return txt
        # el payload real suele venir anidado como string JSON en `body`
        if isinstance(data, dict) and "body" in data:
            try:
                return json.loads(data["body"])
            except Exception:
                return data["body"]
        return data
    except Exception as e:
        log.warning("trends_call_failed", tool=tool, error=str(e)[:150])
        return None


def growth(keyword: str, source: str = "google search", period: str = "3M") -> Optional[Dict]:
    """Crecimiento de un término (dirección + %). Devuelve el primer result o None."""
    d = _tool("get_growth", {"keyword": keyword, "source": source, "period": period})
    if isinstance(d, dict):
        res = d.get("results") or []
        return res[0] if res else d
    return None


def top_trends(type_: str = "Google Trends", limit: int = 10) -> List[Any]:
    """Top trends de un tipo ('Google Trends', 'Google News Top News', ...)."""
    d = _tool("get_top_trends", {"type": type_, "limit": limit})
    if isinstance(d, dict):
        return d.get("data") or []
    return []
