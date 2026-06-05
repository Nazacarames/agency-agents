"""
Cliente Discord — usa Webhook (no requiere bot ni gateway persistente).
Ideal para entregar outputs de agentes a un canal específico.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import httpx
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

from ..config import Settings
from ..log import get_logger

log = get_logger("discord")


class DiscordError(Exception):
    pass


@dataclass
class DiscordEmbed:
    title: Optional[str] = None
    description: Optional[str] = None
    color: int = 0x3498DB  # azul
    fields: Optional[List[Dict[str, Any]]] = None
    footer: Optional[str] = None
    url: Optional[str] = None


class DiscordWebhook:
    def __init__(self, settings: Settings):
        self.s = settings
        if not self.s.discord_webhook_url:
            raise DiscordError("DISCORD_WEBHOOK_URL no configurada")
        self._url = self.s.discord_webhook_url
        self._client = httpx.Client(timeout=30)

    def close(self) -> None:
        self._client.close()

    @retry(
        retry=retry_if_exception_type((httpx.TransportError, DiscordError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=8),
        reraise=True,
    )
    def send(
        self,
        content: str,
        *,
        embed: Optional[DiscordEmbed] = None,
        username: Optional[str] = None,
        avatar_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Envía un mensaje (texto plano) o un embed. Si content > 2000 chars, va como embed.description."""
        username = username or self.s.discord_default_username
        avatar_url = avatar_url or self.s.discord_avatar_url or None

        payload: Dict[str, Any] = {"username": username}
        if avatar_url:
            payload["avatar_url"] = avatar_url

        if embed:
            embed_dict: Dict[str, Any] = {"color": embed.color}
            if embed.title:
                embed_dict["title"] = embed.title[:256]
            if embed.description:
                embed_dict["description"] = embed.description[:4096]
            if embed.url:
                embed_dict["url"] = embed.url
            if embed.fields:
                embed_dict["fields"] = embed.fields[:25]
            if embed.footer:
                embed_dict["footer"] = {"text": embed.footer[:2048]}
            payload["embeds"] = [embed_dict]
        else:
            payload["content"] = content[:2000]

        resp = self._client.post(
            f"{self._url}?wait=true",
            json=payload,
        )
        if resp.status_code == 429:
            raise DiscordError(f"Rate limited: {resp.text[:200]}")
        if resp.status_code >= 400:
            raise DiscordError(f"HTTP {resp.status_code}: {resp.text[:200]}")
        return resp.json() if resp.content else {}

    def send_agent_output(
        self,
        agent_name: str,
        text: str,
        *,
        run_id: Optional[str] = None,
        elapsed_ms: Optional[int] = None,
    ) -> None:
        """Helper: entrega el output de un agente como embed formateado."""
        title = f"🤖 {agent_name}"
        if run_id:
            title += f" · `{run_id[:8]}`"
        footer_parts = ["Automiq Agents"]
        if elapsed_ms is not None:
            footer_parts.append(f"{elapsed_ms}ms")
        if run_id:
            footer_parts.append(run_id)
        embed = DiscordEmbed(
            title=title,
            description=text[:3900],  # margen para evitar truncado
            color=0x2ECC71,            # verde "ok"
            footer=" · ".join(footer_parts),
        )
        try:
            self.send("", embed=embed)
        except DiscordError as e:
            log.error("discord_delivery_failed", agent=agent_name, error=str(e))
            raise
