"""
veo_video — generación de video con Google Veo 3 (Gemini API).

Usa la API key de Google AI Studio (GOOGLE_API_KEY) sobre el proyecto con los
créditos GCP. Reemplaza a MoneyPrinterTurbo / MiniMax video para los TikToks.

Modo image-to-video: anima una imagen (p.ej. la foto de Nazareno) según un prompt
de movimiento → clip vertical 9:16 de ~8s. Flujo async (long-running operation):
  1. create_task(prompt, image_url|image_b64) -> operation_name
  2. query_task(operation_name) -> {done, status, uri?}
  3. el uri del video requiere la API key appendeada para descargar (fetch_bytes)

Veo 3 genera clips de 8s; el audio lo agrega Veo (ambiente). Aspect 9:16 nativo.

Docs: https://ai.google.dev/gemini-api/docs/video
"""
from __future__ import annotations

import base64
import time
from typing import Any, Dict, Optional

import httpx

from ..config import get_settings
from ..log import get_logger

log = get_logger("veo_video")

_API_ROOT = "https://generativelanguage.googleapis.com/v1beta"


def enabled() -> bool:
    return bool(get_settings().google_api_key)


def _key() -> str:
    return get_settings().google_api_key


def _model() -> str:
    return get_settings().veo_model or "veo-3.0-fast-generate-001"


def fetch_image_b64(url: str) -> Dict[str, str]:
    """Descarga una imagen y la devuelve {bytesBase64Encoded, mimeType} para Veo."""
    with httpx.Client(timeout=60, follow_redirects=True) as c:
        r = c.get(url)
        r.raise_for_status()
        mime = r.headers.get("content-type", "image/jpeg").split(";")[0].strip()
        if not mime.startswith("image/"):
            mime = "image/jpeg"
        return {"bytesBase64Encoded": base64.b64encode(r.content).decode("ascii"),
                "mimeType": mime}


def create_task(prompt: str, image_url: Optional[str] = None,
                image_b64: Optional[Dict[str, str]] = None,
                aspect_ratio: str = "9:16",
                negative_prompt: str = "") -> str:
    """Lanza la generación. Devuelve el operation_name (para pollear)."""
    instance: Dict[str, Any] = {"prompt": (prompt or "").strip()[:2000]}
    img = image_b64 or (fetch_image_b64(image_url) if image_url else None)
    if img:
        instance["image"] = img
    params: Dict[str, Any] = {"aspectRatio": aspect_ratio}
    if negative_prompt:
        params["negativePrompt"] = negative_prompt
    body = {"instances": [instance], "parameters": params}

    url = f"{_API_ROOT}/models/{_model()}:predictLongRunning?key={_key()}"
    with httpx.Client(timeout=90) as c:
        r = c.post(url, json=body)
    data = r.json() if r.content else {}
    if r.status_code >= 400 or "error" in data:
        err = data.get("error") or {"status": r.status_code, "text": r.text[:300]}
        raise RuntimeError(f"veo create error: {err}")
    name = data.get("name")
    if not name:
        raise RuntimeError(f"veo sin operation name: {str(data)[:300]}")
    log.info("veo_task_created", op=name, model=_model(), img=bool(img))
    return name


def _extract_uri(resp: Dict[str, Any]) -> Optional[str]:
    """Saca el uri del video del response de la operación (tolerante a variantes)."""
    gvr = (resp.get("generateVideoResponse")
           or resp.get("response", {}).get("generateVideoResponse") or {})
    samples = (gvr.get("generatedSamples") or gvr.get("generatedVideos")
               or gvr.get("samples") or [])
    for s in samples:
        vid = s.get("video") or s
        uri = vid.get("uri") or vid.get("videoUri")
        if uri:
            return uri
    return None


def query_task(operation_name: str) -> Dict[str, Any]:
    """Estado de la operación: {done, uri?, error?}."""
    url = f"{_API_ROOT}/{operation_name}?key={_key()}"
    with httpx.Client(timeout=30) as c:
        r = c.get(url)
    data = r.json() if r.content else {}
    out: Dict[str, Any] = {"done": bool(data.get("done"))}
    if data.get("error"):
        out["error"] = data["error"]
    if out["done"]:
        resp = data.get("response") or {}
        uri = _extract_uri(resp) or _extract_uri(data)
        if uri:
            out["uri"] = uri
        elif not out.get("error"):
            out["error"] = {"msg": "done sin uri", "raw": str(data)[:400]}
    return out


def fetch_bytes(uri: str) -> bytes:
    """Descarga el mp4 generado. El uri de Gemini necesita la API key."""
    sep = "&" if "?" in uri else "?"
    full = uri if "key=" in uri else f"{uri}{sep}key={_key()}"
    with httpx.Client(timeout=120, follow_redirects=True) as c:
        r = c.get(full)
        r.raise_for_status()
        return r.content


def generate_and_wait(prompt: str, image_url: Optional[str] = None,
                      image_b64: Optional[Dict[str, str]] = None,
                      aspect_ratio: str = "9:16", negative_prompt: str = "",
                      timeout_s: int = 600, poll: int = 12) -> Dict[str, Any]:
    """Crea la tarea y espera (bloqueante) hasta el video. Devuelve {operation, uri}."""
    op = create_task(prompt, image_url, image_b64, aspect_ratio, negative_prompt)
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        q = query_task(op)
        if q.get("done"):
            if q.get("uri"):
                log.info("veo_done", op=op)
                return {"operation": op, "uri": q["uri"]}
            raise RuntimeError(f"veo task fail: {q.get('error')}")
        time.sleep(poll)
    raise TimeoutError(f"veo task timeout ({op})")
