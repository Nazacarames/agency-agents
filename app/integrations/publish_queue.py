"""
publish_queue — cola de publicaciones para redes (IG/FB).

Objetivo: que los agentes planifiquen/generen muchas piezas sin saturar las cuentas.
Los agentes ENCOLAN cada pieza con un `kind` y un job diario drena:
  - 1 pieza de FEED por día (kind post | carousel | reel), rotando de tipo si se puede
  - hasta MAX_STORIES_PER_DAY historias por día (kind story) — no cuentan para el feed

Persistencia: JSON en el volume (data/publish-queue.json), igual que tasks_store.
Estados: pending → published | failed.
"""
from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytz

MAX_ITEMS = 500          # historial total que se conserva
MAX_PENDING = 30         # tope de cola pendiente (evita backlog infinito)
MAX_STORIES_PER_DAY = 2  # historias diarias (aparte del post/carrusel/reel del feed)
FEED_KINDS = ("post", "carousel", "reel")
# Serializa leer→modificar→guardar (agentes encolan mientras el job drena).
_LOCK = threading.Lock()
_TZ = pytz.timezone("America/Buenos_Aires")


def _data_dir() -> Path:
    return Path(__file__).resolve().parent.parent.parent / "data"


def _store_path() -> Path:
    return _data_dir() / "publish-queue.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today_art() -> str:
    return datetime.now(_TZ).strftime("%Y-%m-%d")


def _art_date(iso: str) -> str:
    try:
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(_TZ).strftime("%Y-%m-%d")
    except Exception:
        return ""


def load_store() -> Dict[str, Any]:
    p = _store_path()
    if not p.exists():
        return {"items": []}
    try:
        with p.open("r", encoding="utf-8") as f:
            data = json.load(f)
        data.setdefault("items", [])
        return data
    except Exception:
        return {"items": []}


def save_store(store: Dict[str, Any]) -> None:
    p = _store_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(store, f, ensure_ascii=False, indent=2)
    os.replace(tmp, p)


def pending_count(store: Optional[Dict[str, Any]] = None) -> int:
    store = store or load_store()
    return sum(1 for it in store["items"] if it.get("status") == "pending")


def _is_ig_fb(it: Dict[str, Any]) -> bool:
    return bool(set(it.get("targets") or ["instagram", "facebook"]) & {"instagram", "facebook"})


def _kind(it: Dict[str, Any]) -> str:
    return (it.get("kind") or "post").lower()


def published_today_count(store: Optional[Dict[str, Any]] = None) -> int:
    """Piezas de FEED (post/carrusel/reel) publicadas HOY en IG/FB (tope 1/día).
    Las historias y los Shorts registrados con record_published NO cuentan."""
    store = store or load_store()
    today = _today_art()
    return sum(
        1 for it in store["items"]
        if it.get("status") == "published"
        and _art_date(it.get("published_at", "")) == today
        and _is_ig_fb(it) and _kind(it) in FEED_KINDS
        and not it.get("recorded")          # record_published no cuenta
    )


def stories_published_today(store: Optional[Dict[str, Any]] = None) -> int:
    store = store or load_store()
    today = _today_art()
    return sum(
        1 for it in store["items"]
        if it.get("status") == "published"
        and _art_date(it.get("published_at", "")) == today
        and _kind(it) == "story"
    )


def enqueue(image: str, caption: str = "", targets: Optional[List[str]] = None,
            source: str = "", kind: str = "post",
            images: Optional[List[str]] = None) -> Optional[Dict[str, Any]]:
    """Encola una pieza. `kind`: post | story | carousel | reel.
    `images`: lista para carruseles (image = portada). Para reels, `image` es el mp4.
    Devuelve el item, o None si la cola pendiente está llena."""
    kind = (kind or "post").lower()
    if kind not in FEED_KINDS + ("story",):
        kind = "post"
    item = {
        "id": uuid.uuid4().hex[:12],
        "image": image,
        "images": images or None,
        "kind": kind,
        "caption": caption or "",
        "targets": targets or ["instagram", "facebook"],
        "source": source or "",
        "status": "pending",
        "created_at": _now(),
        "published_at": None,
        "result": None,
        "error": None,
    }
    with _LOCK:
        store = load_store()
        if pending_count(store) >= MAX_PENDING:
            return None
        store["items"].insert(0, item)
        store["items"] = store["items"][:MAX_ITEMS]
        save_store(store)
    return item


def record_published(image: str, caption: str, target: str, result: Dict[str, Any],
                     source: str = "") -> Dict[str, Any]:
    """Registra una publicación YA hecha por fuera de la cola (Shorts de YouTube,
    posts de TikTok) para que aparezca en la sección Publicaciones del panel.
    No pasa por pending ni cuenta para el tope diario de IG/FB."""
    item = {
        "id": uuid.uuid4().hex[:12],
        "image": image,
        "kind": "post",
        "caption": caption or "",
        "targets": [target],
        "source": source or "",
        "status": "published",
        "recorded": True,
        "created_at": _now(),
        "published_at": _now(),
        "result": {target: result},
        "error": None,
    }
    with _LOCK:
        store = load_store()
        store["items"].insert(0, item)
        store["items"] = store["items"][:MAX_ITEMS]
        save_store(store)
    return item


def list_queue(status: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
    items = load_store().get("items", [])
    if status:
        items = [it for it in items if it.get("status") == status]
    return items[:limit]


def _pick_feed_item(store: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Elige la próxima pieza de FEED: la pendiente más vieja, pero si su kind
    repite el de la última publicación del feed y hay otro kind esperando,
    prefiere variar (no salen dos reels/posts seguidos si hay alternativa)."""
    pend = [it for it in store["items"]
            if it.get("status") == "pending" and _kind(it) in FEED_KINDS]
    if not pend:
        return None
    pend.sort(key=lambda it: it.get("created_at", ""))
    last_kind = ""
    for it in store["items"]:  # items están ordenados nuevo→viejo
        if it.get("status") == "published" and _is_ig_fb(it) and _kind(it) in FEED_KINDS \
                and not it.get("recorded"):
            last_kind = _kind(it)
            break
    if last_kind:
        distinto = [it for it in pend if _kind(it) != last_kind]
        if distinto:
            return distinto[0]
    return pend[0]


def _publish_item(item: Dict[str, Any]) -> Dict[str, Any]:
    """Publica un item (según su kind) y persiste el resultado."""
    from ..log import get_logger
    log = get_logger("publish_queue")
    from . import social_publish as sp
    res = sp.publish(item["image"], item.get("caption", ""), item.get("targets"),
                     kind=_kind(item), images=item.get("images"))
    # releer el store por si cambió mientras publicábamos
    with _LOCK:
        store = load_store()
        for it in store["items"]:
            if it["id"] == item["id"]:
                if res.get("ok"):
                    it["status"] = "published"
                    it["published_at"] = _now()
                    it["result"] = res.get("results")
                else:
                    it["status"] = "failed"
                    it["error"] = json.dumps(res.get("results") or res, ensure_ascii=False)[:500]
                break
        save_store(store)
    log.info("publish_queue_drained", id=item["id"], kind=_kind(item), ok=res.get("ok"),
             source=item.get("source"))
    _notify_discord(item, res)
    return {"ok": res.get("ok"), "item": item["id"], "kind": _kind(item),
            "results": res.get("results")}


def drain_one(force: bool = False) -> Dict[str, Any]:
    """Publica 1 pieza de FEED pendiente si hoy no salió ninguna (salvo force),
    y hasta MAX_STORIES_PER_DAY historias. Pensado para correr 1x/día. SÍNCRONO
    (llamarlo con asyncio.to_thread desde el scheduler para no bloquear el event
    loop: la Graph API hace self-fetch de /media). Devuelve un dict con el resultado."""
    store = load_store()
    from . import social_publish as sp
    if not sp.enabled():
        return {"ok": False, "error": "publicación a redes no configurada"}
    # Auto-reparación: completar permalinks que quedaron pendientes en publicaciones
    # previas (IG a veces no devuelve el permalink justo al publicar; al otro día ya está).
    try:
        backfill_permalinks()
    except Exception:
        pass
    out: Dict[str, Any] = {"ok": True}
    # 1) pieza de feed (post/carrusel/reel)
    if not force and published_today_count(store) >= 1:
        out["feed"] = {"skipped": "ya se publicó hoy"}
    else:
        item = _pick_feed_item(store)
        out["feed"] = _publish_item(item) if item else {"skipped": "cola de feed vacía"}
        out["ok"] = out["feed"].get("ok", True)
    # 2) historias del día (no cuentan para el tope del feed)
    stories: List[Dict[str, Any]] = []
    store = load_store()
    quota = MAX_STORIES_PER_DAY - stories_published_today(store)
    pend_stories = sorted(
        (it for it in store["items"] if it.get("status") == "pending" and _kind(it) == "story"),
        key=lambda it: it.get("created_at", ""))
    for it in pend_stories[:max(0, quota)]:
        stories.append(_publish_item(it))
    if stories:
        out["stories"] = stories
    return out


def backfill_permalinks() -> Dict[str, Any]:
    """Completa permalinks faltantes en posts YA publicados, consultando la Graph API
    por el media/post id guardado. Idempotente: sólo toca los que no tienen permalink.
    Arregla los posts viejos (publicados antes de guardar permalink) y los que el IG
    no devolvió el link al instante."""
    import httpx
    from ..config import get_settings
    s = get_settings()
    token = s.meta_page_token
    if not token:
        return {"ok": False, "error": "sin meta_page_token", "updated": 0}
    store = load_store()
    updated = 0
    graph = f"https://graph.facebook.com/{s.meta_graph_version or 'v21.0'}"
    with httpx.Client(timeout=15) as c:
        for it in store.get("items", []):
            res = it.get("result")
            if not isinstance(res, dict):
                continue
            changed = False
            ig = res.get("instagram")
            if isinstance(ig, dict) and ig.get("ok") and not ig.get("permalink") and ig.get("id"):
                try:
                    r = c.get(f"{graph}/{ig['id']}", params={"fields": "permalink", "access_token": token})
                    pl = (r.json() or {}).get("permalink")
                    if pl:
                        ig["permalink"] = pl
                        changed = True
                except Exception:
                    pass
            fb = res.get("facebook")
            if isinstance(fb, dict) and fb.get("ok") and not fb.get("permalink") and fb.get("id"):
                try:
                    r = c.get(f"{graph}/{fb['id']}", params={"fields": "permalink_url", "access_token": token})
                    pl = (r.json() or {}).get("permalink_url")
                    if pl:
                        fb["permalink"] = pl
                        changed = True
                except Exception:
                    pass
            if changed:
                updated += 1
    if updated:
        save_store(store)
    return {"ok": True, "updated": updated}


def _notify_discord(item: Dict[str, Any], res: Dict[str, Any]) -> None:
    """Avisa a Discord el resultado de la publicación (best-effort)."""
    try:
        from ..config import get_settings
        from ..clients.discord import DiscordWebhook
        s = get_settings()
        if not getattr(s, "discord_configured", False):
            return
        parts = []
        for net, r in (res.get("results") or {}).items():
            lbl = "Instagram" if net == "instagram" else "Facebook"
            parts.append(f"✅ {lbl}: {r.get('permalink') or 'ok'}" if r.get("ok") else f"❌ {lbl}: {str(r.get('error',''))[:120]}")
        cap = (item.get("caption") or "")[:120]
        klabel = {"story": "Historia", "carousel": "Carrusel", "reel": "Reel"}.get(_kind(item), "Publicación")
        msg = (f"📣 **{klabel} del día**\n" + "\n".join(parts) + (f"\n> {cap}…" if cap else ""))
        dw = DiscordWebhook(s)
        dw.send(msg, url=getattr(s, "discord_images_webhook_url", "") or None)
        dw.close()
    except Exception:
        pass


def delete_item(item_id: str) -> bool:
    with _LOCK:
        store = load_store()
        before = len(store["items"])
        store["items"] = [it for it in store["items"] if it.get("id") != item_id]
        save_store(store)
        return len(store["items"]) < before


def summary() -> Dict[str, Any]:
    store = load_store()
    return {
        "pending": pending_count(store),
        "published_today": published_today_count(store),
        "stories_today": stories_published_today(store),
        "max_stories_per_day": MAX_STORIES_PER_DAY,
        "max_pending": MAX_PENDING,
        "items": store["items"][:50],
    }
