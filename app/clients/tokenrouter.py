"""
tokenrouter — cliente OpenAI-compatible para TokenRouter (api.tokenrouter.com).
Backend de texto GRATIS de ÚLTIMO recurso: se invoca desde base.py SOLO cuando
MiniMax falla (típicamente 429 de cuota). Modelo: moonshotai/kimi-k3-free.

Quirks medidos (2026-07-31): es un modelo "thinking" y LENTO (~40-70s). Con
max_tokens bajo gasta todo el presupuesto en razonamiento y devuelve content vacío
→ acá pisamos un piso alto de max_tokens y un timeout generoso. Devuelve un
MiniMaxResponse para que el runner lo consuma sin cambios.
"""
from __future__ import annotations

import time

import httpx

from ..config import Settings
from ..log import get_logger
from .minimax import MiniMaxResponse

log = get_logger("tokenrouter")


def tokenrouter_enabled(s: Settings) -> bool:
    return bool(getattr(s, "tokenrouter_api_key", ""))


def complete_tokenrouter(s: Settings, system: str, user_msg: str,
                         max_tokens: int, temperature: float) -> MiniMaxResponse:
    # Piso alto: el modelo razona antes de responder; con poco presupuesto el
    # content sale vacío (medido). Dejamos aire para el razonamiento + la respuesta.
    mt = max(max_tokens or 0, 2000)
    body = {
        "model": s.tokenrouter_model,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user_msg}],
        "temperature": temperature,
        "max_tokens": mt,
    }
    t0 = time.perf_counter()
    with httpx.Client(base_url=s.tokenrouter_base_url.rstrip("/"),
                      timeout=180.0,
                      headers={"Authorization": f"Bearer {s.tokenrouter_api_key}",
                               "Content-Type": "application/json"}) as c:
        r = c.post("/chat/completions", json=body)
    elapsed = int((time.perf_counter() - t0) * 1000)
    if r.status_code >= 400:
        raise RuntimeError(f"TokenRouter HTTP {r.status_code}: {r.text[:250]}")
    data = r.json()
    choice = (data.get("choices") or [{}])[0]
    text = ((choice.get("message") or {}).get("content") or "").strip()
    usage = data.get("usage") or {}
    return MiniMaxResponse(
        text=text, model=data.get("model", s.tokenrouter_model),
        input_tokens=usage.get("prompt_tokens", 0),
        output_tokens=usage.get("completion_tokens", 0),
        stop_reason=choice.get("finish_reason"), raw=data,
        elapsed_ms=elapsed, content_blocks=[], tool_uses=[],
    )
