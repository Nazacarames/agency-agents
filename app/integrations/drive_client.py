"""
Google Drive — sube archivos a carpetas de la cuenta Workspace (Ventas@automiq.agency).

Reusa las MISMAS creds OAuth de Gmail (GMAIL_CLIENT_ID/SECRET/REFRESH_TOKEN) con el
scope drive.file (solo ve/edita archivos creados por esta app). Si el refresh token
actual no tiene el scope (se minteó antes de agregarlo a gmail_oauth_setup.py), las
llamadas dan 403 → se loguea UNA vez y queda deshabilitado hasta el próximo restart.

Estructura de carpetas (find-or-create, IDs cacheados en data/drive-folders.json):
    Automiq/Contenido/YYYY-MM/imagenes
    Automiq/Contenido/YYYY-MM/videos
    Automiq/Reportes/YYYY-MM
    Automiq/Backups
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import List, Optional

from ..config import get_settings
from ..log import get_logger
from .jsonstore import write_json_atomic

log = get_logger("drive")

DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive.file"]
_CACHE_FILE = Path(__file__).resolve().parent.parent.parent / "data" / "drive-folders.json"

_lock = threading.Lock()
_service = None
_scope_ok = True  # se apaga si el token no tiene drive.file (403)


def enabled() -> bool:
    s = get_settings()
    return bool(_scope_ok and getattr(s, "drive_sync_enabled", True) and s.gmail_configured)


def _build_service():
    global _service
    if _service is not None:
        return _service
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    s = get_settings()
    creds = Credentials(
        token=None,
        refresh_token=s.gmail_refresh_token,
        client_id=s.gmail_client_id,
        client_secret=s.gmail_client_secret,
        token_uri="https://oauth2.googleapis.com/token",
        scopes=DRIVE_SCOPES,
    )
    try:
        import httplib2
        from google_auth_httplib2 import AuthorizedHttp
        http = AuthorizedHttp(creds, http=httplib2.Http(timeout=120))
        _service = build("drive", "v3", http=http, cache_discovery=False)
    except ImportError:
        _service = build("drive", "v3", credentials=creds, cache_discovery=False)
    return _service


def _mark_scope_error(e: Exception) -> bool:
    """Si el error es de scope/permiso, deshabilita Drive en memoria. True si lo era."""
    global _scope_ok
    msg = str(e)
    if "insufficient" in msg.lower() or "403" in msg or "invalid_scope" in msg.lower():
        _scope_ok = False
        log.warning("drive_scope_missing",
                    hint="re-minteá GMAIL_REFRESH_TOKEN con scripts/gmail_oauth_setup.py "
                         "(ahora incluye drive.file) y actualizá la env var en Railway")
        return True
    return False


def _folder_cache() -> dict:
    try:
        return json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _folder_id(parts: List[str]) -> Optional[str]:
    """Find-or-create de la cadena de carpetas. Devuelve el ID de la última."""
    key = "/".join(parts)
    cache = _folder_cache()
    if key in cache:
        return cache[key]
    svc = _build_service()
    parent = "root"
    path_so_far = []
    for name in parts:
        path_so_far.append(name)
        subkey = "/".join(path_so_far)
        if subkey in cache:
            parent = cache[subkey]
            continue
        safe = name.replace("'", "\\'")
        q = (f"name = '{safe}' and '{parent}' in parents and "
             "mimeType = 'application/vnd.google-apps.folder' and trashed = false")
        found = svc.files().list(q=q, fields="files(id)", pageSize=1).execute().get("files", [])
        if found:
            parent = found[0]["id"]
        else:
            meta = {"name": name, "mimeType": "application/vnd.google-apps.folder",
                    "parents": [parent]}
            parent = svc.files().create(body=meta, fields="id").execute()["id"]
        cache[subkey] = parent
    write_json_atomic(_CACHE_FILE, cache)
    return parent


def upload_file(local_path: str | Path, folder_parts: List[str],
                mime: Optional[str] = None) -> Optional[str]:
    """Sube un archivo a la carpeta indicada. Devuelve el webViewLink o None.
    Best-effort: nunca levanta excepción."""
    if not enabled():
        return None
    p = Path(local_path)
    if not p.exists():
        return None
    try:
        with _lock:
            from googleapiclient.http import MediaFileUpload
            svc = _build_service()
            folder = _folder_id(folder_parts)
            media = MediaFileUpload(str(p), mimetype=mime,
                                    resumable=p.stat().st_size > 4_000_000)
            meta = {"name": p.name, "parents": [folder]}
            f = svc.files().create(body=meta, media_body=media,
                                   fields="id,webViewLink").execute()
            link = f.get("webViewLink", "")
            log.info("drive_uploaded", name=p.name, folder="/".join(folder_parts))
            return link
    except Exception as e:
        if not _mark_scope_error(e):
            log.warning("drive_upload_failed", name=p.name, error=str(e)[:200])
        return None
