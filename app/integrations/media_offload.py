"""
media_offload — saca la media del volumen (500MB) hacia Drive, que es el archivo.

El volumen se llena con imágenes/videos generados; con disco lleno TODOS los
save_store fallan en silencio. Este pase deja en el volumen SOLO lo que está por
publicarse (pendiente en la cola) o es muy reciente; el resto lo sube a Drive
(reusando el link que dejó drive_sync, o subiéndolo si falta), estampa el link en
el item de la cola (`archived`/`drive_link` → el panel muestra "ver en Drive") y
borra el archivo local.

Publicar a IG/FB/TikTok sigue usando /media local: por eso NO se toca lo pendiente
ni lo de las últimas horas. Best-effort: si Drive no está o algo falla, no borra.
Corre en el housekeeping diario y se puede disparar por /api/admin/offload-media.
"""
from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Set
from zoneinfo import ZoneInfo

from ..log import get_logger
from . import drive_client, drive_sync

log = get_logger("media_offload")

_DATA = Path(__file__).resolve().parent.parent.parent / "data"
_IMG_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
_VID_EXTS = {".mp4", ".mov", ".webm"}


def _pending_names(store: Dict[str, Any]) -> Set[str]:
    """Archivos referenciados por items PENDIENTES: nunca borrar (se van a publicar)."""
    out: Set[str] = set()
    for it in store.get("items", []):
        if it.get("status") != "pending":
            continue
        for url in [it.get("image")] + (it.get("images") or []):
            if url:
                out.add(str(url).rsplit("/", 1)[-1])
    return out


def run(min_age_hours: int = 24) -> Dict[str, Any]:
    if not drive_client.enabled():
        return {"ok": False, "reason": "drive deshabilitado o sin creds/scope"}
    images = _DATA / "images"
    if not images.exists():
        return {"ok": True, "offloaded": 0, "freed_mb": 0.0}

    from . import publish_queue as pq
    store = pq.load_store()
    pending = _pending_names(store)

    # basename -> items (para estampar el link de Drive en el item que lo usa)
    idx: Dict[str, list] = {}
    for it in store.get("items", []):
        for url in [it.get("image")] + (it.get("images") or []):
            if url:
                idx.setdefault(str(url).rsplit("/", 1)[-1], []).append(it)

    month = datetime.now(ZoneInfo("America/Argentina/Buenos_Aires")).strftime("%Y-%m")
    cutoff = time.time() - min_age_hours * 3600
    offloaded = freed = 0
    changed = False

    for p in images.iterdir():
        try:
            if not p.is_file() or p.name in pending:
                continue
            if p.stat().st_mtime > cutoff:
                continue  # muy reciente: puede seguir mostrándose local, no tocar
            ext = p.suffix.lower()
            if ext not in _IMG_EXTS and ext not in _VID_EXTS:
                continue
            link = drive_sync.link_for(p.name)
            if not link:
                kind = "videos" if ext in _VID_EXTS else "imagenes"
                link = drive_client.upload_file(p, ["Automiq", "Contenido", month, kind]) or ""
                if link:
                    drive_sync.remember(p.name, link)
            if not link:
                continue  # no se pudo asegurar copia en Drive → NO borrar
            for it in idx.get(p.name, []):
                it["archived"] = True
                it["drive_link"] = link
                changed = True
            size = p.stat().st_size
            p.unlink()
            offloaded += 1
            freed += size
        except Exception:
            continue

    if changed:
        try:
            pq.save_store(store)
        except Exception as e:
            log.warning("offload_save_failed", error=str(e)[:150])

    res = {"ok": True, "offloaded": offloaded, "freed_mb": round(freed / 1_048_576, 1)}
    log.info("media_offload_done", **res)
    return res
