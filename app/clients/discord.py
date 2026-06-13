"""
Cliente Discord — usa Webhook (no requiere bot ni gateway persistente).
Ideal para entregar outputs de agentes a un canal específico.
"""
from __future__ import annotations

import json as _json
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

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
        # Se permite construir si hay AL MENOS un webhook (general, por-agente o errores);
        # el destino concreto se resuelve por llamada (send(url=...)).
        if not settings.discord_configured:
            raise DiscordError("No hay ningún webhook de Discord configurado")
        self._url = self.s.discord_webhook_url  # default/fallback (puede ser "")
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
        url: Optional[str] = None,
        file: Optional[Tuple[str, str]] = None,
    ) -> Dict[str, Any]:
        """Envía un mensaje (texto plano) o un embed. Si content > 2000 chars, va como embed.description.
        `url` apunta a un webhook específico (canal del agente); si no, usa el general.
        `file` = (filename, contenido_texto) para adjuntar un archivo (reportes largos)."""
        target_url = url or self._url
        if not target_url:
            raise DiscordError("No hay webhook destino (ni específico ni general)")
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

        if file is not None:
            fname, fcontent = file
            files = {"files[0]": (fname, (fcontent or "").encode("utf-8"), "text/markdown")}
            resp = self._client.post(
                f"{target_url}?wait=true",
                data={"payload_json": _json.dumps(payload)},
                files=files,
            )
        else:
            resp = self._client.post(
                f"{target_url}?wait=true",
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
        url: Optional[str] = None,
        color: int = 0x2ECC71,     # verde "ok"
    ) -> None:
        """Helper: entrega el output de un agente como embed formateado.
        `url` = webhook del canal del agente (si None, usa el general)."""
        title = f"🤖 {agent_name}"
        if run_id:
            title += f" · `{run_id[:8]}`"
        footer_parts = ["Automiq Agents"]
        if elapsed_ms is not None:
            footer_parts.append(f"{elapsed_ms}ms")
        if run_id:
            footer_parts.append(run_id)

        text = text or ""
        # Si el reporte es largo, el embed sólo entra ~3900 chars → mandamos un PREVIEW
        # y adjuntamos el reporte COMPLETO como archivo .md para no perder nada.
        LIMIT = 3900
        file = None
        if len(text) > LIMIT:
            desc = (
                text[:1800].rstrip()
                + "\n\n— ✂️ —\n\n*(Reporte largo: preview arriba; el COMPLETO va adjunto como "
                ".md más abajo.)*"
            )
            safe = agent_name.replace("❌", "").strip().replace(" ", "-")
            fname = f"{safe}-report{('-'+run_id[:8]) if run_id else ''}.md"
            file = (fname, text)
        else:
            desc = text

        embed = DiscordEmbed(
            title=title,
            description=desc[:4096],
            color=color,
            footer=" · ".join(footer_parts),
        )
        try:
            self.send("", embed=embed, url=url, file=file)
        except DiscordError as e:
            log.error("discord_delivery_failed", agent=agent_name, error=str(e))
            raise
