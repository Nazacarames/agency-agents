"""
publish_queue — cola de publicaciones para redes (IG/FB).

Objetivo: que los agentes planifiquen/generen muchas piezas, pero se publique COMO
MÁXIMO 1 por día. En vez de publicar inline, los agentes ENCOLAN cada imagen
(image url + caption + targets) y un job diario (`scheduler._drain_publish_queue`)
DRENA 1 sola por día.

Persistencia: JSON en el volume (data/publish-queue.json), igual que tasks_store.
Estados: pending → published | failed.
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytz

MAX_ITEMS = 500          # historial total que se conserva
MAX_PENDING = 30         # tope de cola pendiente (evita backlog infinito)
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


def published_today_count(store: Optional[Dict[str, Any]] = None) -> int:
    store = store or load_store()
    today = _today_art()
    return sum(1 for it in store["items"]
               if it.get("status") == "published" and _art_date(it.get("published_at", "")) == today)


def enqueue(image: str, caption: str = "", targets: Optional[List[str]] = None,
            source: str = "") -> Optional[Dict[str, Any]]:
    """Encola una pieza. Devuelve el item, o None si la cola pendiente está llena."""
    store = load_store()
    if pending_count(store) >= MAX_PENDING:
        return None
    item = {
        "id": uuid.uuid4().hex[:12],
        "image": image,
        "caption": caption or "",
        "targets": targets or ["instagram", "facebook"],
        "source": source or "",
        "status": "pending",
        "created_at": _now(),
        "published_at": None,
        "result": None,
        "error": None,
    }
    store["items"].insert(0, item)
    store["items"] = store["items"][:MAX_ITEMS]
    save_store(store)
    return item


def list_queue(status: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
    items = load_store().get("items", [])
    if status:
        items = [it for it in items if it.get("status") == status]
    return items[:limit]


def _oldest_pending(store: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    pend = [it for it in store["items"] if it.get("status") == "pending"]
    if not pend:
        return None
    # los más viejos primero (created_at asc)
    pend.sort(key=lambda it: it.get("created_at", ""))
    return pend[0]


def drain_one(force: bool = False) -> Dict[str, Any]:
    """Publica 1 pieza pendiente si todavía no se publicó ninguna hoy (salvo force).
    Pensado para correr 1x/día. SÍNCRONO (llamarlo con asyncio.to_thread desde el
    scheduler para no bloquear el event loop: la Graph API hace self-fetch de /media).
    Devuelve un dict con el resultado."""
    from ..log import get_logger
    log = get_logger("publish_queue")
    store = load_store()
    if not force and published_today_count(store) >= 1:
        return {"ok": True, "skipped": "ya se publicó hoy"}
    # Auto-reparación: completar permalinks que quedaron pendientes en publicaciones
    # previas (IG a veces no devuelve el permalink justo al publicar; al otro día ya está).
    try:
        backfill_permalinks()
    except Exception:
        pass
    item = _oldest_pending(store)
    if not item:
        return {"ok": True, "skipped": "cola vacía"}
    from . import social_publish as sp
    if not sp.enabled():
        return {"ok": False, "error": "publicación a redes no configurada"}
    res = sp.publish(item["image"], item.get("caption", ""), item.get("targets"))
    # releer el store por si cambió mientras publicábamos
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
    log.info("publish_queue_drained", id=item["id"], ok=res.get("ok"), source=item.get("source"))
    _notify_discord(item, res)
    return {"ok": res.get("ok"), "item": item["id"], "results": res.get("results")}


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
    graph = "https://graph.facebook.com/v21.0"
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
        msg = ("📣 **Publicación del día**\n" + "\n".join(parts) + (f"\n> {cap}…" if cap else ""))
        dw = DiscordWebhook(s)
        dw.send(msg, url=getattr(s, "discord_images_webhook_url", "") or None)
        dw.close()
    except Exception:
        pass


def delete_item(item_id: str) -> bool:
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
        "max_pending": MAX_PENDING,
        "items": store["items"][:50],
    }
