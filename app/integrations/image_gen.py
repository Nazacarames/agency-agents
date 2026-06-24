"""
image_gen — generación de imágenes para el contenido, vía la API de imágenes de MiniMax.

MiniMax expone `/v1/image_generation` (model `image-01`). Generamos la imagen, la
descargamos al volume (`data/images/`) y devolvemos una URL local estable
(`/media/<archivo>.png`) servida por la app — porque las URLs que devuelve MiniMax
son temporales (OSS) y expiran.

Best-effort: si falla (sin API key, error de cuota, etc.) devuelve [] y el contenido
sigue saliendo sin imagen. Nunca rompe una corrida.
"""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import List

import httpx

from ..config import get_settings
from ..log import get_logger

log = get_logger("image_gen")


def _images_dir() -> Path:
    d = Path(__file__).resolve().parent.parent.parent / "data" / "images"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _endpoint() -> str:
    base = (get_settings().minimax_base_url or "https://api.minimax.io/anthropic")
    root = base.split("/anthropic")[0].rstrip("/")
    return f"{root}/v1/image_generation"


def enabled() -> bool:
    s = get_settings()
    return bool(s.minimax_api_key and getattr(s, "images_enabled", True))


def generate_image(prompt: str, aspect_ratio: str = "1:1", n: int = 1) -> List[str]:
    """Genera n imágenes y devuelve URLs locales estables (/media/...). [] si falla."""
    s = get_settings()
    if not enabled() or not (prompt or "").strip():
        return []
    body = {
        "model": getattr(s, "image_model", "image-01"),
        "prompt": prompt.strip()[:1500],
        "aspect_ratio": aspect_ratio or "1:1",
        "response_format": "url",
        "n": max(1, min(n, 4)),
    }
    try:
        with httpx.Client(timeout=120) as c:
            r = c.post(_endpoint(), json=body,
                       headers={"Authorization": f"Bearer {s.minimax_api_key}",
                                "Content-Type": "application/json"})
            r.raise_for_status()
            data = r.json()
        br = data.get("base_resp") or {}
        if br.get("status_code") not in (0, None):
            log.warning("image_gen_api_error", status=br.get("status_code"), msg=br.get("status_msg"))
            return []
        urls = (data.get("data") or {}).get("image_urls") or []
        out: List[str] = []
        for u in urls:
            local = _download(u, c if False else None)
            if local:
                out.append(local)
        log.info("image_gen_ok", generated=len(out))
        return out
    except Exception as e:
        log.warning("image_gen_failed", error=str(e)[:200])
        return []


def _download(url: str, _client=None) -> str:
    """Descarga la imagen al volume y devuelve su URL local (/media/<file>)."""
    try:
        with httpx.Client(timeout=60) as c:
            resp = c.get(url)
            resp.raise_for_status()
            content = resp.content
        fname = f"{uuid.uuid4().hex}.png"
        (_images_dir() / fname).write_bytes(content)
        return f"/media/{fname}"
    except Exception as e:
        log.warning("image_download_failed", error=str(e)[:150])
        return ""
