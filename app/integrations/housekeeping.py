"""
housekeeping — retención del volumen /app/data (500MB).

Nada limpiaba data/images (PNG/MP4 de image_gen, chat_mockup, videos) ni los
reportes diarios data/*-report-*.md: con 1 post + 2 historias/día + reels de
varios MB el volumen se llenaba en semanas y, con disco lleno, TODOS los
save_store fallan EN SILENCIO (tragan la excepción) → el sistema deja de
persistir. Corre diario vía scheduler.

Reglas:
- data/images: borrar archivos con mtime > IMAGES_KEEP_DAYS, salvo los
  referenciados por items pendientes de publish_queue (todavía se van a publicar).
- data/*.md de reportes: borrar con mtime > REPORTS_KEEP_DAYS (chief_of_staff
  lee 72h; /last sirve el más reciente — nadie necesita meses de historia).
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Dict

from ..log import get_logger

log = get_logger("housekeeping")

_DATA = Path(__file__).resolve().parent.parent.parent / "data"
IMAGES_KEEP_DAYS = 30
REPORTS_KEEP_DAYS = 60


def _pending_media() -> set:
    """Nombres de archivo referenciados por items PENDIENTES de la cola (no borrar:
    todavía se van a publicar). Incluye las imágenes de carruseles."""
    try:
        from . import publish_queue as pq
        out = set()
        for it in pq.load_store().get("items", []):
            if it.get("status") != "pending":
                continue
            for url in [it.get("image")] + (it.get("images") or []):
                if url:
                    out.add(str(url).rsplit("/", 1)[-1])
        return out
    except Exception:
        return set()


def cleanup() -> Dict[str, int]:
    now = time.time()
    removed_media = removed_reports = freed = 0

    images = _DATA / "images"
    if images.exists():
        keep = _pending_media()
        cutoff = now - IMAGES_KEEP_DAYS * 86400
        for p in images.iterdir():
            try:
                if not p.is_file() or p.name in keep or p.stat().st_mtime > cutoff:
                    continue
                size = p.stat().st_size
                p.unlink()
                removed_media += 1
                freed += size
            except Exception:
                continue

    if _DATA.exists():
        cutoff = now - REPORTS_KEEP_DAYS * 86400
        for p in _DATA.glob("*-report-*.md"):
            try:
                if p.stat().st_mtime < cutoff:
                    freed += p.stat().st_size
                    p.unlink()
                    removed_reports += 1
            except Exception:
                continue
        for p in _DATA.glob("*-leads-*.json"):
            try:
                if p.stat().st_mtime < cutoff:
                    freed += p.stat().st_size
                    p.unlink()
                    removed_reports += 1
            except Exception:
                continue

    res = {"media": removed_media, "reports": removed_reports,
           "freed_mb": round(freed / 1_048_576, 1)}
    log.info("housekeeping_done", **res)
    return res
