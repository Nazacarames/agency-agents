"""
youtube_client — sube videos (Shorts) al canal de Automiq vía YouTube Data API v3.

Auth: reusa la credencial OAuth de Google (ADC de usuario, `GOOGLE_SERVICE_ACCOUNT_JSON`),
re-autorizada con el scope `youtube.upload`. Si se prefiere una credencial dedicada,
se puede setear `YOUTUBE_OAUTH_JSON` (mismo formato authorized_user).

⚠️ Hasta que Google AUDITE el proyecto, los videos subidos por API quedan en PRIVADO
(aunque pidas público). Por eso el default es `private`: el video aterriza en YouTube
Studio listo para publicar con un clic. Tras la auditoría se puede pasar a `public` y
queda 100% automático. Subir cuesta ~1600 unidades de cuota (default 10.000/día ≈ 6/día).

Para que YouTube lo trate como SHORT: video vertical <60s + #Shorts en título/descripción.
"""
from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional

from ..config import get_settings
from ..log import get_logger

log = get_logger("youtube_client")

YT_SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
]


def _raw_creds() -> str:
    s = get_settings()
    return getattr(s, "youtube_oauth_json", "") or s.google_service_account_json


def enabled() -> bool:
    return bool(_raw_creds())


def _credentials():
    from google.oauth2.credentials import Credentials as UserCreds
    import google.auth.transport.requests as gar
    info = json.loads(_raw_creds())
    if info.get("type") and info.get("type") != "authorized_user":
        raise RuntimeError("YouTube necesita credencial OAuth de usuario (authorized_user)")
    # NO pasar scopes: en el refresh de un authorized_user re-especificar scopes hace
    # que Google devuelva invalid_scope. El token ya trae los scopes otorgados.
    creds = UserCreds.from_authorized_user_info(info)
    if not creds.valid:
        creds.refresh(gar.Request())
    return creds


def _service():
    from googleapiclient.discovery import build
    # Timeout largo (sube videos de varios MB) pero NO infinito: el default None
    # colgaba el thread para siempre ante un socket muerto.
    try:
        import httplib2
        from google_auth_httplib2 import AuthorizedHttp
        http = AuthorizedHttp(_credentials(), http=httplib2.Http(timeout=300))
        return build("youtube", "v3", http=http, cache_discovery=False)
    except ImportError:
        return build("youtube", "v3", credentials=_credentials(), cache_discovery=False)


def channel_info() -> Dict[str, Any]:
    """Datos del canal autenticado (para verificar la conexión)."""
    yt = _service()
    r = yt.channels().list(part="snippet,statistics", mine=True).execute()
    items = r.get("items") or []
    if not items:
        return {"connected": False, "error": "sin canal en esta cuenta"}
    it = items[0]
    sn = it.get("snippet", {})
    st = it.get("statistics", {})
    return {"connected": True, "channel_id": it.get("id"), "title": sn.get("title"),
            "subscribers": st.get("subscriberCount"), "videos": st.get("videoCount")}


def upload_video(file_path: str, title: str, description: str = "",
                 tags: Optional[List[str]] = None, privacy: Optional[str] = None,
                 made_for_kids: bool = False) -> Dict[str, Any]:
    """Sube un video. Devuelve {id, url, privacy}. Resumable + reintentos."""
    from googleapiclient.http import MediaFileUpload
    s = get_settings()
    privacy = privacy or getattr(s, "youtube_privacy", "private") or "private"
    body = {
        "snippet": {
            "title": title[:100],
            "description": (description or "")[:4900],
            "tags": (tags or [])[:15],
            "categoryId": "22",  # People & Blogs
        },
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": bool(made_for_kids),
        },
    }
    yt = _service()
    media = MediaFileUpload(file_path, mimetype="video/mp4", chunksize=-1, resumable=True)
    req = yt.videos().insert(part="snippet,status", body=body, media_body=media)
    resp = None
    tries = 0
    while resp is None:
        try:
            status, resp = req.next_chunk()
        except Exception as e:
            tries += 1
            if tries > 4:
                raise
            log.warning("yt_upload_retry", n=tries, error=str(e)[:150])
            time.sleep(2 * tries)
    vid = resp.get("id")
    log.info("yt_uploaded", id=vid, privacy=privacy)
    return {"id": vid, "url": f"https://www.youtube.com/shorts/{vid}",
            "watch": f"https://youtu.be/{vid}", "privacy": privacy}


def status() -> Dict[str, Any]:
    """Estado para el panel/diagnóstico."""
    if not enabled():
        return {"configured": False}
    try:
        return {"configured": True, **channel_info()}
    except Exception as e:
        return {"configured": True, "connected": False, "error": str(e)[:200]}
