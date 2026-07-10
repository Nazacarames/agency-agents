"""
linkedin_client — publicación en LinkedIn con la API OFICIAL (perfil del miembro).

OAuth 2.0 3-legged con scope `openid profile w_member_social` (producto "Share on
LinkedIn" + "Sign In with LinkedIn using OpenID Connect" de la app — ambos de
aprobación instantánea en developers.linkedin.com). Publica posts de texto + imagen
en el perfil conectado vía /rest/posts (API versionada).

Config: LINKEDIN_CLIENT_ID + LINKEDIN_CLIENT_SECRET (Railway; defaults vacíos).
Token en data/linkedin-token.json (volume, gitignoreado). Los tokens duran ~60 días
y el refresh programático requiere partnership → cuando vence, se reconecta desde
/linkedin (1 clic). Best-effort en todo.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import httpx

from ..config import get_settings
from ..log import get_logger

log = get_logger("linkedin_client")

_API_VERSION = "202506"
_DATA = Path(__file__).resolve().parent.parent.parent / "data"
_TOKEN_FILE = _DATA / "linkedin-token.json"

# Little Text Format de LinkedIn: estos chars deben escaparse en commentary o da 400.
_LTF_CHARS = "\\|{}@[]()<>#*_~"


def _escape_ltf(text: str) -> str:
    out = []
    for ch in text or "":
        out.append("\\" + ch if ch in _LTF_CHARS else ch)
    return "".join(out)


def configured() -> bool:
    s = get_settings()
    return bool(getattr(s, "linkedin_client_id", "") and getattr(s, "linkedin_client_secret", ""))


def load_token() -> Dict[str, Any]:
    try:
        return json.loads(_TOKEN_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_token(tok: Dict[str, Any]) -> None:
    from .jsonstore import write_json_atomic
    write_json_atomic(_TOKEN_FILE, tok)


def clear_token() -> None:
    try:
        _TOKEN_FILE.unlink()
    except Exception:
        pass


def connected() -> bool:
    tok = load_token()
    return bool(tok.get("access_token")) and tok.get("expires_at", 0) > time.time()


def _redirect_uri() -> str:
    s = get_settings()
    return (s.public_base_url or "").rstrip("/") + "/auth/linkedin/callback"


def authorize_url(state: str) -> str:
    s = get_settings()
    from urllib.parse import urlencode
    q = urlencode({"response_type": "code", "client_id": s.linkedin_client_id,
                   "redirect_uri": _redirect_uri(), "state": state,
                   "scope": "openid profile w_member_social"})
    return f"https://www.linkedin.com/oauth/v2/authorization?{q}"


def exchange_code(code: str) -> Dict[str, Any]:
    """Cambia el code por el access token + identidad (sub) y lo persiste."""
    s = get_settings()
    with httpx.Client(timeout=30) as c:
        r = c.post("https://www.linkedin.com/oauth/v2/accessToken", data={
            "grant_type": "authorization_code", "code": code,
            "redirect_uri": _redirect_uri(),
            "client_id": s.linkedin_client_id, "client_secret": s.linkedin_client_secret,
        })
        d = r.json()
        if "access_token" not in d:
            raise RuntimeError(f"token error: {str(d)[:200]}")
        info = c.get("https://api.linkedin.com/v2/userinfo",
                     headers={"Authorization": f"Bearer {d['access_token']}"}).json()
    tok = {"access_token": d["access_token"],
           "expires_at": time.time() + int(d.get("expires_in", 0)),
           "sub": info.get("sub", ""), "name": info.get("name", "")}
    save_token(tok)
    log.info("linkedin_connected", name=tok["name"][:40])
    return tok


def _headers(tok: Dict[str, Any]) -> Dict[str, str]:
    return {"Authorization": f"Bearer {tok['access_token']}",
            "LinkedIn-Version": _API_VERSION,
            "X-Restli-Protocol-Version": "2.0.0",
            "Content-Type": "application/json"}


def publish(text: str, image_path: Optional[str] = None) -> Dict[str, Any]:
    """Publica un post (texto + imagen opcional) en el perfil conectado.
    Devuelve {ok, id, permalink} o {ok: False, error}."""
    tok = load_token()
    if not (tok.get("access_token") and tok.get("sub")):
        return {"ok": False, "error": "LinkedIn no conectado (entrá a /linkedin)"}
    if tok.get("expires_at", 0) < time.time():
        return {"ok": False, "error": "token de LinkedIn vencido — reconectá en /linkedin"}
    author = f"urn:li:person:{tok['sub']}"
    try:
        with httpx.Client(timeout=120) as c:
            content = None
            if image_path and Path(image_path).exists():
                r = c.post("https://api.linkedin.com/rest/images?action=initializeUpload",
                           headers=_headers(tok),
                           json={"initializeUploadRequest": {"owner": author}})
                v = (r.json().get("value") or {})
                up_url, img_urn = v.get("uploadUrl"), v.get("image")
                if not (up_url and img_urn):
                    return {"ok": False, "error": f"init upload: {str(r.json())[:150]}"}
                pr = c.put(up_url, content=Path(image_path).read_bytes(),
                           headers={"Authorization": f"Bearer {tok['access_token']}"})
                if pr.status_code not in (200, 201):
                    return {"ok": False, "error": f"upload imagen: HTTP {pr.status_code}"}
                content = {"media": {"id": img_urn}}
            body: Dict[str, Any] = {
                "author": author,
                "commentary": _escape_ltf(text[:2900]),
                "visibility": "PUBLIC",
                "distribution": {"feedDistribution": "MAIN_FEED",
                                 "targetEntities": [], "thirdPartyDistributionChannels": []},
                "lifecycleState": "PUBLISHED",
                "isReshareDisabledByAuthor": False,
            }
            if content:
                body["content"] = content
            r = c.post("https://api.linkedin.com/rest/posts", headers=_headers(tok), json=body)
            if r.status_code != 201:
                try:
                    err = r.json().get("message", r.text)
                except Exception:
                    err = r.text
                return {"ok": False, "error": f"HTTP {r.status_code}: {str(err)[:200]}"}
            urn = r.headers.get("x-restli-id", "")
            log.info("linkedin_published", urn=urn[:60])
            return {"ok": True, "id": urn,
                    "permalink": f"https://www.linkedin.com/feed/update/{urn}" if urn else ""}
    except Exception as e:
        log.warning("linkedin_publish_failed", error=str(e)[:200])
        return {"ok": False, "error": str(e)[:200]}


def status() -> Dict[str, Any]:
    tok = load_token()
    exp = tok.get("expires_at", 0)
    return {"configured": configured(), "connected": connected(),
            "name": tok.get("name", ""),
            "expires": (datetime.fromtimestamp(exp, tz=timezone.utc).isoformat()[:10]
                        if exp else None)}
