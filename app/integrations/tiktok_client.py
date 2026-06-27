"""
tiktok_client — Login Kit (OAuth v2) + Content Posting API de TikTok.

App "Automiq Publisher". Conecta la cuenta oficial de la marca por OAuth (una vez),
guarda el token en el volume y postea videos PROPIOS vía la Content Posting API
(Direct Post con PULL_FROM_URL desde un dominio verificado).

Flujo:
  1. authorize_url(state) → el usuario autoriza en TikTok.
  2. exchange_code(code)  → guarda access/refresh token (data/tiktok-token.json).
  3. valid_access_token() → refresca solo si está por vencer.
  4. post_video_from_url(url, caption) → publica (en sandbox: privado/SELF_ONLY).

Docs: https://developers.tiktok.com/doc/content-posting-api-get-started
Sandbox: hasta que TikTok apruebe la app, solo postea a la cuenta autorizada como
privado. `tiktok_sandbox=True` fuerza privacy SELF_ONLY.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

import httpx

from ..config import Settings
from ..log import get_logger

log = get_logger("tiktok")

_AUTH_URL = "https://www.tiktok.com/v2/auth/authorize/"
_TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
_CREATOR_INFO_URL = "https://open.tiktokapis.com/v2/post/publish/creator_info/query/"
_VIDEO_INIT_URL = "https://open.tiktokapis.com/v2/post/publish/video/init/"
_STATUS_URL = "https://open.tiktokapis.com/v2/post/publish/status/fetch/"


class TikTokError(RuntimeError):
    pass


def _token_path() -> Path:
    d = Path(__file__).resolve().parent.parent.parent / "data"
    d.mkdir(parents=True, exist_ok=True)
    return d / "tiktok-token.json"


def load_token() -> Dict[str, Any]:
    p = _token_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_token(tok: Dict[str, Any]) -> None:
    p = _token_path()
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(tok, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, p)


def clear_token() -> None:
    try:
        _token_path().unlink()
    except FileNotFoundError:
        pass


class TikTokClient:
    def __init__(self, settings: Settings):
        self.s = settings
        self.client_key = settings.tiktok_client_key
        self.client_secret = settings.tiktok_client_secret
        self.redirect_uri = settings.tiktok_redirect_uri_effective

    def configured(self) -> bool:
        return bool(self.client_key and self.client_secret and self.redirect_uri)

    # ── OAuth ──
    def authorize_url(self, state: str) -> str:
        from urllib.parse import urlencode
        params = {
            "client_key": self.client_key,
            "scope": ",".join(self.s.tiktok_scopes_list),
            "response_type": "code",
            "redirect_uri": self.redirect_uri,
            "state": state,
        }
        return f"{_AUTH_URL}?{urlencode(params)}"

    def exchange_code(self, code: str) -> Dict[str, Any]:
        data = {
            "client_key": self.client_key,
            "client_secret": self.client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": self.redirect_uri,
        }
        tok = self._token_request(data)
        save_token(tok)
        log.info("tiktok_connected", open_id=tok.get("open_id"), scope=tok.get("scope"))
        return tok

    def refresh(self) -> Dict[str, Any]:
        tok = load_token()
        rt = tok.get("refresh_token")
        if not rt:
            raise TikTokError("no hay refresh_token; reconectá la cuenta")
        data = {
            "client_key": self.client_key,
            "client_secret": self.client_secret,
            "grant_type": "refresh_token",
            "refresh_token": rt,
        }
        new = self._token_request(data)
        save_token(new)
        log.info("tiktok_token_refreshed", open_id=new.get("open_id"))
        return new

    def _token_request(self, data: Dict[str, str]) -> Dict[str, Any]:
        with httpx.Client(timeout=30) as c:
            r = c.post(_TOKEN_URL, data=data,
                       headers={"Content-Type": "application/x-www-form-urlencoded"})
        body = r.json() if r.content else {}
        if r.status_code >= 400 or body.get("error"):
            raise TikTokError(f"oauth token error {r.status_code}: {body.get('error_description') or body}")
        # TikTok devuelve los campos al tope (no anidados en data) en v2.
        now = int(time.time())
        body["obtained_at"] = now
        body["expires_at"] = now + int(body.get("expires_in", 0) or 0)
        body["refresh_expires_at"] = now + int(body.get("refresh_expires_in", 0) or 0)
        return body

    def valid_access_token(self) -> str:
        tok = load_token()
        at = tok.get("access_token")
        if not at:
            raise TikTokError("cuenta de TikTok no conectada")
        # refrescar si vence en <2 min
        if int(tok.get("expires_at", 0)) - int(time.time()) < 120:
            tok = self.refresh()
            at = tok.get("access_token")
        return at

    # ── Content Posting ──
    def _post_json(self, url: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        at = self.valid_access_token()
        with httpx.Client(timeout=60) as c:
            r = c.post(url, json=payload, headers={
                "Authorization": f"Bearer {at}",
                "Content-Type": "application/json; charset=UTF-8",
            })
        body = r.json() if r.content else {}
        err = (body.get("error") or {})
        if r.status_code >= 400 or (err and err.get("code") not in (None, "ok")):
            raise TikTokError(f"{url.split('/v2/')[-1]} error {r.status_code}: {err or body}")
        return body

    def creator_info(self) -> Dict[str, Any]:
        """Info del creador (privacy levels permitidos, límites). Requerido antes de postear."""
        return self._post_json(_CREATOR_INFO_URL, {})

    def post_video_from_url(self, video_url: str, caption: str = "",
                            privacy_level: Optional[str] = None) -> Dict[str, Any]:
        """Direct Post de un video alojado en un dominio verificado (PULL_FROM_URL).
        En sandbox el privacy se fuerza a SELF_ONLY (privado)."""
        priv = privacy_level or ("SELF_ONLY" if self.s.tiktok_sandbox else "PUBLIC_TO_EVERYONE")
        payload = {
            "post_info": {
                "title": (caption or "")[:2200],
                "privacy_level": priv,
                "disable_duet": False,
                "disable_comment": False,
                "disable_stitch": False,
            },
            "source_info": {
                "source": "PULL_FROM_URL",
                "video_url": video_url,
            },
        }
        res = self._post_json(_VIDEO_INIT_URL, payload)
        pid = (res.get("data") or {}).get("publish_id")
        log.info("tiktok_post_init", publish_id=pid, privacy=priv)
        return res

    def post_video_file_upload(self, video_bytes: bytes, caption: str = "",
                               privacy_level: Optional[str] = None) -> Dict[str, Any]:
        """Direct Post subiendo los BYTES del video (FILE_UPLOAD). No requiere
        verificación de dominio (a diferencia de PULL_FROM_URL). Sube en 1 chunk."""
        priv = privacy_level or ("SELF_ONLY" if self.s.tiktok_sandbox else "PUBLIC_TO_EVERYONE")
        size = len(video_bytes)
        payload = {
            "post_info": {
                "title": (caption or "")[:2200],
                "privacy_level": priv,
                "disable_duet": False,
                "disable_comment": False,
                "disable_stitch": False,
            },
            "source_info": {
                "source": "FILE_UPLOAD",
                "video_size": size,
                "chunk_size": size,
                "total_chunk_count": 1,
            },
        }
        res = self._post_json(_VIDEO_INIT_URL, payload)
        data = res.get("data") or {}
        upload_url = data.get("upload_url")
        pid = data.get("publish_id")
        if not upload_url:
            raise TikTokError(f"init sin upload_url: {res}")
        with httpx.Client(timeout=180) as c:
            r = c.put(upload_url, content=video_bytes, headers={
                "Content-Type": "video/mp4",
                "Content-Length": str(size),
                "Content-Range": f"bytes 0-{size - 1}/{size}",
            })
        if r.status_code not in (200, 201, 206):
            raise TikTokError(f"upload PUT error {r.status_code}: {r.text[:200]}")
        log.info("tiktok_post_file_upload", publish_id=pid, privacy=priv, bytes=size)
        return res

    @staticmethod
    def fetch_bytes(url: str) -> bytes:
        with httpx.Client(timeout=90, follow_redirects=True) as c:
            r = c.get(url)
            r.raise_for_status()
            return r.content

    def publish_status(self, publish_id: str) -> Dict[str, Any]:
        return self._post_json(_STATUS_URL, {"publish_id": publish_id})

    # ── estado para el panel/UI ──
    def status(self) -> Dict[str, Any]:
        tok = load_token()
        connected = bool(tok.get("access_token"))
        return {
            "configured": self.configured(),
            "connected": connected,
            "open_id": tok.get("open_id"),
            "scope": tok.get("scope"),
            "sandbox": bool(self.s.tiktok_sandbox),
            "expires_at": tok.get("expires_at"),
            "redirect_uri": self.redirect_uri,
        }


def get_tiktok_client(settings: Settings) -> TikTokClient:
    return TikTokClient(settings)
