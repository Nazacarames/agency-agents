"""
gemini_free — mirar imágenes y VIDEO por la API gratuita de Google AI Studio.

Ojo con la confusión, porque el 2026-09-16 sacamos Google de los agentes: esto
NO es Vertex. Son dos cosas distintas.

  · **Vertex AI** (lo que salió): service account, proyecto de Google Cloud,
    factura por uso. Quedó reservado para CLAMEVET.
  · **AI Studio** (esto): una API key suelta, sin tarjeta y sin facturación.
    Cuota gratuita con límite de peticiones por minuto.

Por qué vuelve a entrar: al salir de Vertex perdimos analizar VIDEO NATIVO —con
audio y movimiento— y lo reemplazamos por frames sueltos, que es bastante peor
para juzgar un short hablado. Esta API lo devuelve. Medido el 2026-09-17 con la
misma imagen y el mismo clip que usamos para elegir el modelo de visión:

  · imagen  → 3,3 s y correcto (glm-5.3-flash tardaba ~155 s)
  · video   → 3,9 s, y acertó que el clip NO tiene audio. Es decir: escuchó.

Lo que NO se le confía: el texto de los agentes sigue en Kimi. Acá sólo mira.

⚠️ El tier gratuito se satura: una de las llamadas de prueba devolvió
**503 "This model is currently experiencing high demand"**. Por eso hay cadena de
modelos y, si todo falla, el llamador cae a su camino de siempre. Nunca levanta.
"""
from __future__ import annotations

import base64
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from ..config import get_settings
from ..log import get_logger

log = get_logger("gemini_free")

BASE = "https://generativelanguage.googleapis.com/v1beta"

# En orden. El primero es el mejor medido; los que siguen cubren el 503 por
# saturación, que en el tier gratis pasa de verdad.
MODELOS = ("gemini-3.6-flash", "gemini-flash-latest", "gemini-2.5-flash")

# El límite práctico del `inlineData` de esta API. Un clip más pesado que esto se
# rechaza, así que el llamador tiene que caer a su alternativa.
MAX_INLINE = 18 * 1024 * 1024


def enabled() -> bool:
    return bool(getattr(get_settings(), "gemini_api_key", ""))


def _generar(partes: List[Dict[str, Any]], max_tokens: int,
             timeout: float = 240.0) -> str:
    """Prueba los modelos en orden hasta que uno conteste. "" si ninguno."""
    if not enabled():
        return ""
    key = get_settings().gemini_api_key
    cuerpo = {
        "contents": [{"role": "user", "parts": partes}],
        "generationConfig": {
            "temperature": 0.3, "maxOutputTokens": max_tokens,
            # Los flash de Gemini "piensan" y ese pensamiento sale del MISMO
            # presupuesto de tokens que la respuesta: sin esto vuelve truncada o
            # vacía. Ya nos pasó en CLAMEVET y en GLM; es el mismo error.
            "thinkingConfig": {"thinkingBudget": 0},
        },
    }
    for modelo in MODELOS:
        try:
            with httpx.Client(timeout=timeout) as c:
                r = c.post(f"{BASE}/models/{modelo}:generateContent",
                           params={"key": key}, json=cuerpo)
            if r.status_code == 200:
                cand = (r.json().get("candidates") or [{}])[0]
                txt = "".join(p.get("text", "") for p in
                              (cand.get("content", {}).get("parts") or [])).strip()
                if txt:
                    return txt
                log.warning("gemini_vacio", modelo=modelo)
                continue
            # 503 = saturado, 429 = cuota. Los dos se resuelven probando otro.
            log.warning("gemini_http", modelo=modelo, status=r.status_code,
                        detalle=r.text[:160])
        except Exception as e:                              # noqa: BLE001
            log.warning("gemini_falló", modelo=modelo, error=str(e)[:150])
    return ""


def describir_imagenes(rutas: List[str], prompt: str,
                       max_tokens: int = 1800) -> str:
    """Mira hasta 8 imágenes. "" si no pudo."""
    partes: List[Dict[str, Any]] = []
    for ruta in rutas[:8]:
        p = Path(ruta)
        try:
            datos = base64.b64encode(p.read_bytes()).decode()
        except Exception:
            continue
        mime = "image/png" if str(p).lower().endswith(".png") else "image/jpeg"
        partes.append({"inlineData": {"mimeType": mime, "data": datos}})
    if not partes:
        return ""
    partes.append({"text": prompt})
    return _generar(partes, max_tokens)


def describir_video(video_path: str, prompt: str, max_tokens: int = 1800) -> str:
    """Analiza el VIDEO ENTERO: movimiento, audio y texto en pantalla en el tiempo.

    Esto es lo que no puede hacer un modelo que sólo ve fotos, y es la razón por
    la que este módulo existe. "" si el clip pesa de más o si falla.
    """
    try:
        raw = Path(video_path).read_bytes()
    except Exception:
        return ""
    if len(raw) > MAX_INLINE:
        log.warning("gemini_video_muy_pesado", bytes=len(raw))
        return ""
    return _generar([{"inlineData": {"mimeType": "video/mp4",
                                     "data": base64.b64encode(raw).decode()}},
                     {"text": prompt}], max_tokens)
