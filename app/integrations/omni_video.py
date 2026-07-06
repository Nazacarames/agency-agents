"""
omni_video — Gemini Omni Flash (preview) vía Vertex AI: video 9:16 con AUDIO nativo por
generateContent (multi-shot, consistencia de escena — el benchmark 2026 de video).

VERIFICADO 2026-07-06 con nuestra service account (location "global"):
- Dice la frase EXACTA una sola vez, acento rioplatense, voz natural, lip sync (los dos
  males históricos de Veo — repetición y acento neutro — no aparecieron).
- Consistencia de cara: pasando las fotos de Nazareno como inlineData, la cara del video
  ES la de la referencia (hasta la ropa y el mic corbatero).
- Salida: 720x1280 h264+aac inline base64 (~2MB por 8s). El montaje ya normaliza a 1080.

Es PREVIEW (clips ~10s máx) → usar SIEMPRE con fallback a Veo 3.1 (veo_video).
Gotcha del filtro: "se filma a sí mismo" dispara PROHIBITED_CONTENT; describir la cámara
("grabado con la cámara frontal de un celular") pasa sin drama.
"""
from __future__ import annotations

import base64
import urllib.request
from typing import Any, Dict, Optional

import httpx

from ..log import get_logger

log = get_logger("omni_video")

MODEL = "gemini-omni-flash-preview"


def enabled() -> bool:
    try:
        from . import veo_video
        return veo_video.enabled()
    except Exception:
        return False


def generate_and_wait(prompt: str, reference_image_urls: Optional[list] = None,
                      negative_prompt: str = "", timeout_s: int = 600,
                      **_ignored) -> Dict[str, Any]:
    """Genera el video (bloqueante). API compatible con veo_video.generate_and_wait:
    devuelve {"b64": <mp4>} o {} si falla/filtra (el caller cae a Veo)."""
    if not enabled() or not (prompt or "").strip():
        return {}
    try:
        from . import veo_video
        tok, proj = veo_video._token(), veo_video._project()
        parts = []
        for u in (reference_image_urls or []):
            try:
                data = urllib.request.urlopen(u, timeout=20).read()
                parts.append({"inlineData": {"mimeType": "image/jpeg",
                                             "data": base64.b64encode(data).decode()}})
            except Exception as e:
                log.warning("omni_ref_download_failed", url=u[:80], error=str(e)[:100])
        text = prompt
        if parts:
            text = ("La MISMA persona de las fotos de referencia (misma cara, mismo pelo, "
                    "misma identidad). " + text)
        if negative_prompt:
            text += f"\nEvitar estrictamente: {negative_prompt}"
        parts.append({"text": text[:4000]})
        url = (f"https://aiplatform.googleapis.com/v1/projects/{proj}/locations/global"
               f"/publishers/google/models/{MODEL}:generateContent")
        r = httpx.post(url, json={"contents": [{"role": "user", "parts": parts}],
                                  "generationConfig": {"responseModalities": ["TEXT", "VIDEO"]}},
                       headers={"Authorization": f"Bearer {tok}"}, timeout=timeout_s)
        d = r.json()
        if r.status_code != 200:
            log.warning("omni_http_error", status=r.status_code,
                        msg=str(d.get("error", {}).get("message", ""))[:150])
            return {}
        cand = (d.get("candidates") or [{}])[0]
        fr = cand.get("finishReason")
        for p in cand.get("content", {}).get("parts", []):
            blob = p.get("inlineData") or {}
            if "video" in (blob.get("mimeType") or "") and blob.get("data"):
                log.info("omni_video_ok", kb=len(blob["data"]) // 1024)
                return {"b64": blob["data"], "model": MODEL}
        log.warning("omni_no_video", finish=str(fr)[:60])
        return {}
    except Exception as e:
        log.warning("omni_generate_failed", error=str(e)[:200])
        return {}
