"""
social_publish — publica contenido en Instagram y Facebook vía Meta Graph API.

Flujos:
  Instagram (cuenta Business/Creator linkeada a una Página de FB):
    1) POST /{ig_business_id}/media          (image_url + caption)  -> creation_id
    2) POST /{ig_business_id}/media_publish   (creation_id)          -> media_id
  Facebook (Página):
    POST /{page_id}/photos                    (url + caption)        -> post_id

Config (se setea cuando se crean las cuentas, ver config.py):
  META_PAGE_ID · META_PAGE_TOKEN (long-lived) · IG_BUSINESS_ID · PUBLIC_BASE_URL

La Graph API descarga la imagen por su URL, así que tiene que ser PÚBLICA:
resolvemos `/media/<file>` contra PUBLIC_BASE_URL.

Best-effort: si no está configurado o falla, devuelve {ok: False, error: ...}.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

import httpx

from ..config import get_settings
from ..log import get_logger

log = get_logger("social_publish")

_GRAPH = "https://graph.facebook.com"


def _graph_url(path: str) -> str:
    v = get_settings().meta_graph_version or "v21.0"
    return f"{_GRAPH}/{v}/{path}"


def public_base() -> str:
    s = get_settings()
    return (s.public_base_url or s.render_external_url or "").rstrip("/")


def absolute_url(image: str) -> str:
    """`/media/x.png` -> `https://host/media/x.png`. Si ya es absoluta, la deja."""
    image = (image or "").strip()
    if image.startswith("http://") or image.startswith("https://"):
        return image
    base = public_base()
    if not base:
        return image  # sin base no podemos hacerla pública
    return f"{base}{image if image.startswith('/') else '/' + image}"


def fb_enabled() -> bool:
    s = get_settings()
    return bool(s.meta_page_id and s.meta_page_token)


def ig_enabled() -> bool:
    s = get_settings()
    return bool(s.ig_business_id and s.meta_page_token)


def enabled() -> bool:
    return fb_enabled() or ig_enabled()


def _err(data: dict, resp: httpx.Response) -> str:
    e = (data or {}).get("error") or {}
    return e.get("message") or (resp.text or "")[:200] or f"HTTP {resp.status_code}"


def publish_facebook(image: str, caption: str = "") -> Dict[str, Any]:
    s = get_settings()
    if not fb_enabled():
        return {"ok": False, "error": "FB no configurado (META_PAGE_ID / META_PAGE_TOKEN)"}
    url = absolute_url(image)
    if not url.startswith("http"):
        return {"ok": False, "error": "PUBLIC_BASE_URL no seteada: la imagen no es accesible públicamente"}
    try:
        with httpx.Client(timeout=60) as c:
            r = c.post(_graph_url(f"{s.meta_page_id}/photos"),
                       data={"url": url, "caption": caption or "", "access_token": s.meta_page_token})
            data = r.json() if r.content else {}
            if r.status_code >= 400 or data.get("error"):
                return {"ok": False, "error": _err(data, r)}
            return {"ok": True, "target": "facebook", "id": data.get("post_id") or data.get("id")}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def publish_instagram(image: str, caption: str = "") -> Dict[str, Any]:
    s = get_settings()
    if not ig_enabled():
        return {"ok": False, "error": "IG no configurado (IG_BUSINESS_ID / META_PAGE_TOKEN)"}
    url = absolute_url(image)
    if not url.startswith("http"):
        return {"ok": False, "error": "PUBLIC_BASE_URL no seteada: la imagen no es accesible públicamente"}
    try:
        with httpx.Client(timeout=90) as c:
            # 1) crear contenedor de media
            r = c.post(_graph_url(f"{s.ig_business_id}/media"),
                       data={"image_url": url, "caption": caption or "", "access_token": s.meta_page_token})
            d = r.json() if r.content else {}
            if r.status_code >= 400 or d.get("error"):
                return {"ok": False, "error": _err(d, r)}
            creation_id = d.get("id")
            if not creation_id:
                return {"ok": False, "error": "sin creation_id de la Graph API"}
            # 1b) IG procesa el contenedor de forma ASÍNCRONA: hay que esperar a que
            # status_code == FINISHED antes de publicarlo, si no da "Media ID is not
            # available". Polleamos hasta ~25s.
            for _ in range(12):
                rs = c.get(_graph_url(creation_id),
                           params={"fields": "status_code,status", "access_token": s.meta_page_token})
                ds = rs.json() if rs.content else {}
                st = (ds.get("status_code") or "").upper()
                if st == "FINISHED":
                    break
                if st == "ERROR":
                    return {"ok": False, "error": f"IG no pudo procesar la imagen: {ds.get('status') or 'ERROR'}"}
                time.sleep(2)
            # 2) publicar el contenedor
            r2 = c.post(_graph_url(f"{s.ig_business_id}/media_publish"),
                        data={"creation_id": creation_id, "access_token": s.meta_page_token})
            d2 = r2.json() if r2.content else {}
            if r2.status_code >= 400 or d2.get("error"):
                return {"ok": False, "error": _err(d2, r2)}
            return {"ok": True, "target": "instagram", "id": d2.get("id")}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def publish(image: str, caption: str = "", targets: Optional[List[str]] = None) -> Dict[str, Any]:
    """Publica en los `targets` pedidos (default: ambos). Devuelve resultado por red."""
    targets = targets or ["instagram", "facebook"]
    results: Dict[str, Any] = {}
    for t in targets:
        t = (t or "").lower()
        if t in ("ig", "instagram"):
            results["instagram"] = publish_instagram(image, caption)
        elif t in ("fb", "facebook"):
            results["facebook"] = publish_facebook(image, caption)
    ok = any(v.get("ok") for v in results.values())
    log.info("social_publish", ok=ok, results={k: v.get("ok") for k, v in results.items()})
    return {"ok": ok, "results": results}


def status() -> Dict[str, Any]:
    s = get_settings()
    return {
        "configured": enabled(),
        "facebook": fb_enabled(),
        "instagram": ig_enabled(),
        "public_base_url": public_base() or None,
        "graph_version": s.meta_graph_version or "v21.0",
    }
