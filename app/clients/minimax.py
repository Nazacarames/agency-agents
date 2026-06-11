"""
Cliente MiniMax-M3 (compatible con Anthropic Messages API).

- POST {base_url}/v1/messages
- Headers: x-api-key, anthropic-version, content-type
- Soporta fallback chain (primary → M2.5 → M2.5-highspeed).
- Reintentos con backoff exponencial vía tenacity.
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
    before_sleep_log,
)
import logging

from ..config import Settings
from ..log import get_logger

log = get_logger("minimax")

ANTHROPIC_VERSION = "2023-06-01"


class MiniMaxError(Exception):
    """Error base de MiniMax."""


class MiniMaxAuthError(MiniMaxError):
    """API key inválida o ausente."""


class MiniMaxRateLimit(MiniMaxError):
    """Rate limit (429)."""


class MiniMaxServerError(MiniMaxError):
    """5xx del proveedor."""


@dataclass
class MiniMaxResponse:
    text: str
    model: str
    input_tokens: int
    output_tokens: int
    stop_reason: Optional[str]
    raw: Dict[str, Any]
    elapsed_ms: int
    content_blocks: List[Dict[str, Any]] = None  # bloques crudos {type,...} de la respuesta
    tool_uses: List[Dict[str, Any]] = None        # solo los bloques type=="tool_use"

    def __post_init__(self):
        if self.content_blocks is None:
            self.content_blocks = []
        if self.tool_uses is None:
            self.tool_uses = []


class MiniMaxClient:
    def __init__(self, settings: Settings):
        self.s = settings
        if not self.s.minimax_api_key:
            raise MiniMaxAuthError("MINIMAX_API_KEY no configurada")
        self._client = httpx.Client(
            base_url=self.s.minimax_base_url.rstrip("/"),
            timeout=self.s.minimax_timeout_seconds,
            headers={
                "x-api-key": self.s.minimax_api_key,
                "anthropic-version": ANTHROPIC_VERSION,
                "content-type": "application/json",
            },
        )
        self._models = [self.s.minimax_model_primary] + self.s.minimax_fallbacks_list

    def close(self) -> None:
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    # ── API pública ──

    def complete(
        self,
        system: str,
        messages: List[Dict[str, Any]],
        *,
        max_tokens: Optional[int] = None,
        temperature: float = 0.7,
        tools: Optional[List[Dict[str, Any]]] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> MiniMaxResponse:
        """Llama al modelo con fallback automático.

        Si `tools` está presente se pasa en el body (Anthropic Messages API,
        formato {name, description, input_schema}) y la respuesta puede traer
        bloques `tool_use` en `response.tool_uses`.
        """
        body_extra = dict(extra or {})
        if tools:
            body_extra["tools"] = tools
        last_error: Optional[Exception] = None
        for model in self._models:
            try:
                return self._call_once(
                    model=model,
                    system=system,
                    messages=messages,
                    max_tokens=max_tokens or self.s.minimax_max_tokens,
                    temperature=temperature,
                    extra=body_extra,
                )
            except (MiniMaxRateLimit, MiniMaxServerError) as e:
                log.warning("model_fallback", model=model, error=str(e))
                last_error = e
                continue
            except httpx.HTTPError as e:
                log.warning("model_http_error", model=model, error=str(e))
                last_error = e
                continue
        raise MiniMaxError(f"Todos los modelos fallaron. Último error: {last_error}")

    # ── internals ──

    @retry(
        retry=retry_if_exception_type((MiniMaxRateLimit, MiniMaxServerError, httpx.TransportError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        before_sleep=before_sleep_log(log, logging.WARNING),
        reraise=True,
    )
    def _call_once(
        self,
        *,
        model: str,
        system: str,
        messages: List[Dict[str, str]],
        max_tokens: int,
        temperature: float,
        extra: Dict[str, Any],
    ) -> MiniMaxResponse:
        body = {
            "model": model,
            "system": system,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            **extra,
        }
        t0 = time.perf_counter()
        resp = self._client.post("/v1/messages", json=body)
        elapsed_ms = int((time.perf_counter() - t0) * 1000)

        if resp.status_code == 401 or resp.status_code == 403:
            raise MiniMaxAuthError(f"Auth inválida ({resp.status_code}): {resp.text[:200]}")
        if resp.status_code == 429:
            raise MiniMaxRateLimit(f"Rate limit: {resp.text[:200]}")
        if resp.status_code >= 500:
            raise MiniMaxServerError(f"Server error {resp.status_code}: {resp.text[:200]}")
        if resp.status_code >= 400:
            raise MiniMaxError(f"HTTP {resp.status_code}: {resp.text[:300]}")

        data = resp.json()

        # Anthropic Messages API: content es una lista de bloques {type, ...}
        content_blocks = data.get("content", []) or []
        text_parts = []
        tool_uses = []
        for block in content_blocks:
            btype = block.get("type")
            if btype == "text":
                text_parts.append(block.get("text", ""))
            elif btype == "tool_use":
                tool_uses.append({
                    "id": block.get("id"),
                    "name": block.get("name"),
                    "input": block.get("input", {}) or {},
                })

        return MiniMaxResponse(
            text="\n".join(text_parts).strip(),
            model=data.get("model", model),
            input_tokens=data.get("usage", {}).get("input_tokens", 0),
            output_tokens=data.get("usage", {}).get("output_tokens", 0),
            stop_reason=data.get("stop_reason"),
            raw=data,
            elapsed_ms=elapsed_ms,
            content_blocks=content_blocks,
            tool_uses=tool_uses,
        )
