"""
vision — deja que el sistema MIRE imágenes (los agentes son ciegos). Usa Gemini
multimodal vía Vertex reusando el auth de veo_video (service account, SIN key nueva).
El scout le pasa los contact sheets de los reels descubiertos y Gemini destila el
playbook de edición/hooks/visual → cierra el loop "descubre → mira → destila" sin humano.

Best-effort: si Vertex no está configurado o la llamada falla, devuelve "".
"""
from __future__ import annotations

import base64
from pathlib import Path
from typing import List

import httpx

from . import veo_video
from ..log import get_logger

log = get_logger("vision")


def enabled() -> bool:
    return veo_video.enabled()


def describe(image_paths: List[str], prompt: str, model: str = "gemini-2.5-flash",
             max_tokens: int = 1800) -> str:
    """Devuelve la respuesta de texto de Gemini mirando las imágenes (hasta 8). "" si falla."""
    if not enabled() or not image_paths:
        return ""
    try:
        token = veo_video._token()
        project = veo_video._project()
    except Exception as e:
        log.warning("vision_auth_failed", error=str(e)[:150])
        return ""
    parts = []
    for p in image_paths[:8]:
        try:
            data = base64.b64encode(Path(p).read_bytes()).decode()
        except Exception:
            continue
        mime = "image/png" if str(p).lower().endswith(".png") else "image/jpeg"
        parts.append({"inlineData": {"mimeType": mime, "data": data}})
    if not parts:
        return ""
    parts.append({"text": prompt})
    url = (f"https://aiplatform.googleapis.com/v1/projects/{project}"
           f"/locations/global/publishers/google/models/{model}:generateContent")
    body = {"contents": [{"role": "user", "parts": parts}],
            "generationConfig": {"temperature": 0.4, "maxOutputTokens": max_tokens,
                                 # gemini-2.5-flash usa "thinking" y se come el budget de
                                 # tokens → respuesta truncada. thinkingBudget=0 lo apaga.
                                 "thinkingConfig": {"thinkingBudget": 0}}}
    try:
        with httpx.Client(timeout=180) as c:
            r = c.post(url, json=body, headers={"Authorization": f"Bearer {token}"})
        if r.status_code != 200:
            log.warning("vision_http", status=r.status_code, body=r.text[:200])
            return ""
        cand = (r.json().get("candidates") or [{}])[0]
        return "".join(pt.get("text", "")
                       for pt in (cand.get("content", {}).get("parts") or [])).strip()
    except Exception as e:
        log.warning("vision_failed", error=str(e)[:150])
        return ""
