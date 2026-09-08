"""
nvidia — cliente OpenAI-compatible para los modelos del endpoint gratuito de NVIDIA
(build.nvidia.com / integrate.api.nvidia.com). Usado como backend ALTERNATIVO de
ciertos agentes cuando su calidad supera a MiniMax-M3 (bake-off 2026-07-04):
  - GLM 5.2 (z-ai/glm-5.2)        → copy de contenido (más vivo, menos plantillero)
  - DeepSeek V4 Pro (deepseek-v4) → ads + razonamiento (más afilado)

Expone la MISMA interfaz que MiniMaxClient.complete() y devuelve un MiniMaxResponse,
así el runner de los agentes lo consume sin cambios. Es completion directa (sin las
tools/skills de Claude Code): se usa en agentes de texto donde el playbook persistente
ya cubre el contexto de competencia.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

import httpx

from ..config import Settings
from ..log import get_logger
from .minimax import MiniMaxResponse

log = get_logger("nvidia")

# provider lógico → (env model attr, extra body para desactivar reasoning verboso)
_PROVIDER_MODEL = {
    "glm": ("glm_model", {}),
    "deepseek": ("deepseek_model", {"chat_template_kwargs": {"thinking": False}}),
    # Kimi K3 razona antes de responder y el pensamiento se cobra como salida. Medido
    # el 2026-09-08: una pregunta de 6 palabras gastó 92 tokens de completion y tardó
    # 18,6 s con `reasoning_effort: max`. Por eso NO se le recorta el pensamiento y su
    # techo de tokens es alto (ver _MIN_TOKENS): apretarlo hace que se quede sin lugar
    # para responder DESPUÉS de pensar y devuelva vacío o cortado.
    "kimi": ("kimi_model", {"reasoning_effort": "max"}),
}

# Piso de max_tokens por provider. Sólo importa en los que razonan: el pensamiento
# sale del mismo presupuesto que la respuesta.
_MIN_TOKENS = {"kimi": 16384}


def provider_model(provider: str, s: Settings) -> str:
    attr, _ = _PROVIDER_MODEL.get(provider, ("glm_model", {}))
    return getattr(s, attr, "")


class NvidiaClient:
    def __init__(self, settings: Settings):
        self.s = settings
        if not settings.nvidia_api_key:
            raise RuntimeError("NVIDIA no configurado (sin NVIDIA_API_KEY)")
        # Timeout propio, NO el de MiniMax. Kimi y DeepSeek razonan antes de
        # responder: medido el 2026-09-08, tardan 19-30 s en una pregunta trivial y
        # varios minutos en una tarea de verdad. Con los 120 s de MiniMax, toda
        # tarea real cortaba por ReadTimeout y caía al fallback — que es justo cómo
        # estos backends venían "funcionando" sin que nadie lo notara.
        self._client = httpx.Client(
            base_url=settings.nvidia_base_url.rstrip("/"),
            timeout=httpx.Timeout(settings.nvidia_timeout_seconds, connect=15.0),
            headers={"Authorization": f"Bearer {settings.nvidia_api_key}",
                     "Content-Type": "application/json"},
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()

    def complete(self, system: str, messages: List[Dict[str, Any]], *,
                 provider: str = "glm", max_tokens: Optional[int] = None,
                 temperature: float = 0.7) -> MiniMaxResponse:
        model = provider_model(provider, self.s)
        _, extra = _PROVIDER_MODEL.get(provider, ("", {}))
        body: Dict[str, Any] = {
            "model": model,
            "messages": [{"role": "system", "content": system}] + list(messages),
            "temperature": temperature,
            "max_tokens": max(max_tokens or 4000, _MIN_TOKENS.get(provider, 0)),
            "top_p": 0.95,
            **extra,
        }
        t0 = time.perf_counter()
        r = self._client.post("/chat/completions", json=body)
        elapsed = int((time.perf_counter() - t0) * 1000)
        if r.status_code >= 400:
            raise RuntimeError(f"NVIDIA HTTP {r.status_code}: {r.text[:250]}")
        data = r.json()
        choice = (data.get("choices") or [{}])[0]
        text = ((choice.get("message") or {}).get("content") or "").strip()
        usage = data.get("usage") or {}
        return MiniMaxResponse(
            text=text, model=data.get("model", model),
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
            stop_reason=choice.get("finish_reason"), raw=data,
            elapsed_ms=elapsed, content_blocks=[], tool_uses=[],
        )


def complete_with_provider(provider: str, settings: Settings, system: str,
                           user_msg: str, max_tokens: int,
                           temperature: float) -> MiniMaxResponse:
    """Helper para el runner: una completion directa con el provider dado."""
    with NvidiaClient(settings) as c:
        return c.complete(system, [{"role": "user", "content": user_msg}],
                          provider=provider, max_tokens=max_tokens, temperature=temperature)
