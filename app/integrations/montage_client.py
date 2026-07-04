"""
montage_client — llama al microservicio externo `automiq-montage` (armado PRO de video:
split + subtítulos + color grade + b-roll + música) que corre APARTE con RAM propia.

Best-effort: si el servicio no está configurado o falla, devuelve None y el caller cae
al armado local de `video_assembler` (sin regresión). No sube archivos: le pasa al
servicio las URLs públicas `public_base_url/media/<file>` de los assets que ya sirve la app.
"""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import List, Optional

from ..config import get_settings
from ..log import get_logger

log = get_logger("montage_client")

# keywords por defecto para el b-roll (en inglés: los bancos de stock buscan mejor así)
_DEFAULT_KEYWORDS = ["small business warehouse", "delivery van logistics", "argentina shop owner"]


def _images_dir() -> Path:
    d = Path(__file__).resolve().parent.parent.parent / "data" / "images"
    d.mkdir(parents=True, exist_ok=True)
    return d


def enabled() -> bool:
    s = get_settings()
    return bool(getattr(s, "montage_service_url", "") and getattr(s, "public_base_url", "")
                and getattr(s, "webhook_secret", ""))


def _media_url(local_path: str, base: str) -> Optional[str]:
    name = Path(str(local_path)).name
    return f"{base}/media/{name}" if name else None


def produce(clip_path: str, frame_paths: List[str], script: str = "",
            keywords: Optional[List[str]] = None, music: Optional[str] = None) -> Optional[str]:
    """Devuelve /media/<file>.mp4 armado por el servicio, o None (best-effort)."""
    if not enabled() or not clip_path:
        return None
    s = get_settings()
    base = (s.public_base_url or "").rstrip("/")
    url = (s.montage_service_url or "").rstrip("/")
    clip_url = _media_url(clip_path, base)
    frame_urls = [u for u in (_media_url(p, base) for p in (frame_paths or [])) if u]
    if not clip_url:
        return None
    body = {
        "clip_url": clip_url,
        "frame_urls": frame_urls,
        "script": (script or "").strip(),
        "keywords": keywords or _DEFAULT_KEYWORDS,
        "music_url": _media_url(music, base) if music else None,
        "formato": "split",
    }
    try:
        import httpx
        with httpx.Client(timeout=200.0) as c:
            r = c.post(f"{url}/produce", json=body,
                       headers={"X-Webhook-Secret": s.webhook_secret})
        if r.status_code != 200 or not r.content or len(r.content) < 10000:
            log.warning("montage_bad_response", status=r.status_code, bytes=len(r.content or b""))
            return None
        fname = f"short_{uuid.uuid4().hex}.mp4"
        (_images_dir() / fname).write_bytes(r.content)
        log.info("montage_used", file=fname, bytes=len(r.content))
        return f"/media/{fname}"
    except Exception as e:
        log.warning("montage_failed", error=str(e)[:200])
        return None
