"""
notify_discord — manda un embed al webhook de Discord.

Usa la URL en DISCORD_WEBHOOK_URL del entorno. Si no está, no hace nada.
"""
from __future__ import annotations

import os
from typing import Any, Dict, Optional

import httpx


def notify_discord(
    title: str,
    description: str = "",
    *,
    color: int = 0x3498DB,
    footer: Optional[str] = None,
    url: Optional[str] = None,
) -> Dict[str, Any]:
    webhook = os.environ.get("DISCORD_WEBHOOK_URL", "")
    if not webhook:
        return {"sent": False, "reason": "DISCORD_WEBHOOK_URL not set"}
    embed: Dict[str, Any] = {"title": title[:256], "color": color}
    if description:
        embed["description"] = description[:4096]
    if footer:
        embed["footer"] = {"text": footer[:2048]}
    if url:
        embed["url"] = url
    try:
        r = httpx.post(
            webhook,
            json={"username": "Automiq Agents", "embeds": [embed]},
            timeout=15.0,
        )
        return {"sent": r.status_code < 400, "status": r.status_code}
    except Exception as e:
        return {"sent": False, "error": str(e)[:200]}
