"""
drive_sync — job diario que sube a Google Drive todo lo nuevo:

  - data/images/*.jpg|png  → Automiq/Contenido/YYYY-MM/imagenes
  - data/images/*.mp4      → Automiq/Contenido/YYYY-MM/videos
  - data/*-report-*.md     → Automiq/Reportes/YYYY-MM
  - data/*.json (stores)   → Automiq/Backups/data-backup-YYYY-MM-DD.zip
    (leads, finanzas, cola de publicación, memoria… — el volumen de Railway es
    punto único de falla; con esto hay copia diaria fuera de la plataforma)

Dedup por nombre en data/drive-sync.json (los stores van siempre: el zip del día
pisa su entrada). Best-effort: cualquier fallo se loguea y no rompe nada.
"""
from __future__ import annotations

import json
import zipfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from ..log import get_logger
from . import drive_client
from .jsonstore import write_json_atomic

log = get_logger("drive_sync")

_DATA = Path(__file__).resolve().parent.parent.parent / "data"
_STATE = _DATA / "drive-sync.json"
_IMG_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
_VID_EXTS = {".mp4", ".mov", ".webm"}
_MAX_STATE = 8000  # nombres recordados (las imágenes viejas las borra housekeeping)


def _state() -> dict:
    try:
        return json.loads(_STATE.read_text(encoding="utf-8"))
    except Exception:
        return {"uploaded": []}


def sync() -> dict:
    if not drive_client.enabled():
        return {"ok": False, "reason": "drive deshabilitado o sin creds/scope"}
    now = datetime.now(ZoneInfo("America/Argentina/Buenos_Aires"))
    month = now.strftime("%Y-%m")
    st = _state()
    uploaded = list(st.get("uploaded", []))
    seen = set(uploaded)

    def _mark(name: str) -> None:
        seen.add(name)
        uploaded.append(name)
        # estado incremental: si un deploy mata el sync a mitad de camino, lo ya
        # subido no se vuelve a subir (files.create duplicaría por nombre)
        if len(uploaded) % 20 == 0:
            st["uploaded"] = uploaded[-_MAX_STATE:]
            write_json_atomic(_STATE, st)

    counts = {"imagenes": 0, "videos": 0, "reportes": 0, "backup": 0}

    # ── contenido (imágenes y videos generados) ──
    img_dir = _DATA / "images"
    if img_dir.exists():
        for p in sorted(img_dir.iterdir()):
            if p.name in seen or not p.is_file():
                continue
            ext = p.suffix.lower()
            if ext in _IMG_EXTS:
                kind = "imagenes"
            elif ext in _VID_EXTS:
                kind = "videos"
            else:
                continue
            if drive_client.upload_file(p, ["Automiq", "Contenido", month, kind]):
                _mark(p.name)
                counts[kind] += 1
            elif not drive_client.enabled():
                break  # scope caído: no insistir con el resto

    # ── reportes de agentes (los preps de reunión van a su carpeta propia) ──
    for p in sorted(_DATA.glob("*-report-*.md")):
        if p.name in seen:
            continue
        folder = (["Automiq", "Reuniones"] if p.name.startswith("meeting-prep-")
                  else ["Automiq", "Reportes", month])
        if drive_client.upload_file(p, folder, mime="text/markdown"):
            _mark(p.name)
            counts["reportes"] += 1
        elif not drive_client.enabled():
            break

    # ── agenda de reuniones legible (se regenera y pisa en cada sync) ──
    try:
        from . import meetings_store
        meets = meetings_store.list_meetings()
        if drive_client.enabled():
            lines = [f"# Agenda de reuniones — Automiq (actualizada {now.strftime('%Y-%m-%d %H:%M')})", ""]
            if not meets:
                lines.append("_Sin reuniones registradas._")
            for m in meets:
                extra = "".join(
                    f" · {m[k]}" for k in ("location",) if m.get(k)
                ) + (f" — {m['notes']}" if m.get("notes") else "")
                lines.append(f"- **{(m.get('scheduled_at') or '?')[:16]}** · "
                             f"{m.get('title') or 'Reunión'} · "
                             f"{m.get('client_name') or 's/cliente'} · "
                             f"{m.get('status') or ''}{extra}")
            if drive_client.upload_text("agenda-reuniones.md", "\n".join(lines),
                                        ["Automiq", "Reuniones"]):
                counts["reuniones"] = 1
    except Exception as e:
        log.warning("drive_meetings_failed", error=str(e)[:200])

    # ── backup diario de stores (zip con todos los data/*.json) ──
    zip_path = _DATA / f"data-backup-{now.strftime('%Y-%m-%d')}.zip"
    if drive_client.enabled() and zip_path.name not in seen:
        try:
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
                for p in sorted(_DATA.glob("*.json")):
                    z.write(p, p.name)
            if drive_client.upload_file(zip_path, ["Automiq", "Backups"],
                                        mime="application/zip"):
                _mark(zip_path.name)
                counts["backup"] = 1
        except Exception as e:
            log.warning("drive_backup_failed", error=str(e)[:200])
        finally:
            try:
                zip_path.unlink(missing_ok=True)
            except Exception:
                pass

    st["uploaded"] = uploaded[-_MAX_STATE:]
    st["last_sync"] = now.isoformat()
    write_json_atomic(_STATE, st)
    log.info("drive_sync_done", **counts)
    return {"ok": True, **counts}
