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


def _wait_container(c: httpx.Client, creation_id: str, token: str,
                    tries: int = 12, sleep: float = 2.0) -> Optional[str]:
    """Espera a que IG procese el contenedor (FINISHED). Devuelve error o None si ok.
    Los videos (reels) tardan minutos → usar tries/sleep más largos."""
    for _ in range(tries):
        rs = c.get(_graph_url(creation_id),
                   params={"fields": "status_code,status", "access_token": token})
        ds = rs.json() if rs.content else {}
        st = (ds.get("status_code") or "").upper()
        if st == "FINISHED":
            return None
        if st == "ERROR":
            return f"IG no pudo procesar el contenido: {ds.get('status') or 'ERROR'}"
        time.sleep(sleep)
    return "timeout esperando que IG procese el contenido"


def _publish_container(c: httpx.Client, creation_id: str, token: str) -> Dict[str, Any]:
    """media_publish + permalink best-effort. Devuelve el dict resultado."""
    s = get_settings()
    r2 = c.post(_graph_url(f"{s.ig_business_id}/media_publish"),
                data={"creation_id": creation_id, "access_token": token})
    d2 = r2.json() if r2.content else {}
    if r2.status_code >= 400 or d2.get("error"):
        return {"ok": False, "error": _err(d2, r2)}
    media_id = d2.get("id")
    link = ""
    try:
        rp = c.get(_graph_url(media_id), params={"fields": "permalink", "access_token": token})
        link = (rp.json() or {}).get("permalink", "") if rp.content else ""
    except Exception:
        pass
    return {"ok": True, "target": "instagram", "id": media_id, "permalink": link}


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
            pid = data.get("post_id") or data.get("id")
            link = f"https://www.facebook.com/{pid}" if pid else ""
            return {"ok": True, "target": "facebook", "id": pid, "permalink": link}
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
            media_id = d2.get("id")
            # permalink (best-effort) para linkear al post desde el panel
            link = ""
            try:
                rp = c.get(_graph_url(media_id), params={"fields": "permalink", "access_token": s.meta_page_token})
                link = (rp.json() or {}).get("permalink", "") if rp.content else ""
            except Exception:
                pass
            return {"ok": True, "target": "instagram", "id": media_id, "permalink": link}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def publish_instagram_story(image: str) -> Dict[str, Any]:
    """Historia de IG (media_type=STORIES). Las historias no llevan caption."""
    s = get_settings()
    if not ig_enabled():
        return {"ok": False, "error": "IG no configurado (IG_BUSINESS_ID / META_PAGE_TOKEN)"}
    url = absolute_url(image)
    if not url.startswith("http"):
        return {"ok": False, "error": "PUBLIC_BASE_URL no seteada: la imagen no es accesible públicamente"}
    try:
        with httpx.Client(timeout=90) as c:
            r = c.post(_graph_url(f"{s.ig_business_id}/media"),
                       data={"image_url": url, "media_type": "STORIES", "access_token": s.meta_page_token})
            d = r.json() if r.content else {}
            if r.status_code >= 400 or d.get("error"):
                return {"ok": False, "error": _err(d, r)}
            err = _wait_container(c, d.get("id"), s.meta_page_token)
            if err:
                return {"ok": False, "error": err}
            return _publish_container(c, d.get("id"), s.meta_page_token)
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def publish_facebook_story(image: str) -> Dict[str, Any]:
    """Historia de la Página de FB: foto sin publicar + /photo_stories."""
    s = get_settings()
    if not fb_enabled():
        return {"ok": False, "error": "FB no configurado (META_PAGE_ID / META_PAGE_TOKEN)"}
    url = absolute_url(image)
    if not url.startswith("http"):
        return {"ok": False, "error": "PUBLIC_BASE_URL no seteada: la imagen no es accesible públicamente"}
    try:
        with httpx.Client(timeout=60) as c:
            r = c.post(_graph_url(f"{s.meta_page_id}/photos"),
                       data={"url": url, "published": "false", "access_token": s.meta_page_token})
            d = r.json() if r.content else {}
            if r.status_code >= 400 or d.get("error"):
                return {"ok": False, "error": _err(d, r)}
            r2 = c.post(_graph_url(f"{s.meta_page_id}/photo_stories"),
                        data={"photo_id": d.get("id"), "access_token": s.meta_page_token})
            d2 = r2.json() if r2.content else {}
            if r2.status_code >= 400 or d2.get("error"):
                return {"ok": False, "error": _err(d2, r2)}
            return {"ok": True, "target": "facebook", "id": d2.get("post_id") or d.get("id"), "permalink": ""}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def publish_instagram_carousel(images: List[str], caption: str = "") -> Dict[str, Any]:
    """Carrusel de IG (2-10 imágenes): un contenedor hijo por imagen + contenedor CAROUSEL."""
    s = get_settings()
    if not ig_enabled():
        return {"ok": False, "error": "IG no configurado (IG_BUSINESS_ID / META_PAGE_TOKEN)"}
    urls = [absolute_url(i) for i in (images or []) if i]
    urls = [u for u in urls if u.startswith("http")][:10]
    if len(urls) < 2:
        return {"ok": False, "error": "un carrusel necesita al menos 2 imágenes públicas"}
    try:
        with httpx.Client(timeout=120) as c:
            children = []
            for u in urls:
                r = c.post(_graph_url(f"{s.ig_business_id}/media"),
                           data={"image_url": u, "is_carousel_item": "true",
                                 "access_token": s.meta_page_token})
                d = r.json() if r.content else {}
                if r.status_code >= 400 or d.get("error"):
                    return {"ok": False, "error": f"item del carrusel: {_err(d, r)}"}
                err = _wait_container(c, d.get("id"), s.meta_page_token)
                if err:
                    return {"ok": False, "error": err}
                children.append(d.get("id"))
            r = c.post(_graph_url(f"{s.ig_business_id}/media"),
                       data={"media_type": "CAROUSEL", "children": ",".join(children),
                             "caption": caption or "", "access_token": s.meta_page_token})
            d = r.json() if r.content else {}
            if r.status_code >= 400 or d.get("error"):
                return {"ok": False, "error": _err(d, r)}
            err = _wait_container(c, d.get("id"), s.meta_page_token)
            if err:
                return {"ok": False, "error": err}
            return _publish_container(c, d.get("id"), s.meta_page_token)
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def publish_instagram_reel(video: str, caption: str = "") -> Dict[str, Any]:
    """Reel de IG (media_type=REELS). El video (mp4 9:16) tiene que ser público;
    IG lo procesa asíncrono y puede tardar minutos → poll largo."""
    s = get_settings()
    if not ig_enabled():
        return {"ok": False, "error": "IG no configurado (IG_BUSINESS_ID / META_PAGE_TOKEN)"}
    url = absolute_url(video)
    if not url.startswith("http"):
        return {"ok": False, "error": "PUBLIC_BASE_URL no seteada: el video no es accesible públicamente"}
    try:
        with httpx.Client(timeout=120) as c:
            r = c.post(_graph_url(f"{s.ig_business_id}/media"),
                       data={"media_type": "REELS", "video_url": url, "caption": caption or "",
                             "share_to_feed": "true", "access_token": s.meta_page_token})
            d = r.json() if r.content else {}
            if r.status_code >= 400 or d.get("error"):
                return {"ok": False, "error": _err(d, r)}
            err = _wait_container(c, d.get("id"), s.meta_page_token, tries=48, sleep=5)
            if err:
                return {"ok": False, "error": err}
            return _publish_container(c, d.get("id"), s.meta_page_token)
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def publish(image: str, caption: str = "", targets: Optional[List[str]] = None,
            kind: str = "post", images: Optional[List[str]] = None) -> Dict[str, Any]:
    """Publica en los `targets` pedidos (default: ambos) según `kind`:
      post (default) → foto en feed IG + FB
      story          → historia IG + historia FB (sin caption)
      carousel       → carrusel en IG; en FB va la primera imagen como foto
      reel           → reel en IG (`image` = video mp4); FB se saltea
    Devuelve resultado por red."""
    targets = [(t or "").lower() for t in (targets or ["instagram", "facebook"])]
    kind = (kind or "post").lower()
    results: Dict[str, Any] = {}
    for t in targets:
        ig = t in ("ig", "instagram")
        fb = t in ("fb", "facebook")
        if kind == "story":
            if ig:
                results["instagram"] = publish_instagram_story(image)
            elif fb:
                results["facebook"] = publish_facebook_story(image)
        elif kind == "carousel":
            if ig:
                results["instagram"] = publish_instagram_carousel(images or [image], caption)
            elif fb:
                results["facebook"] = publish_facebook((images or [image])[0], caption)
        elif kind == "reel":
            if ig:
                results["instagram"] = publish_instagram_reel(image, caption)
            # FB no recibe reels por ahora (upload distinto)
        else:
            if ig:
                results["instagram"] = publish_instagram(image, caption)
            elif fb:
                results["facebook"] = publish_facebook(image, caption)
    if not results:
        return {"ok": False, "results": {}, "error": f"sin targets aplicables para kind={kind}"}
    ok = any(v.get("ok") for v in results.values())
    log.info("social_publish", ok=ok, kind=kind, results={k: v.get("ok") for k, v in results.items()})
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
