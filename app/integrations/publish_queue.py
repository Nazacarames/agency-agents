"""
publish_queue — cola de publicaciones para redes (IG/FB).

Objetivo: que los agentes planifiquen/generen muchas piezas sin saturar las cuentas.
Los agentes ENCOLAN cada pieza con un `kind` y un job diario drena:
  - 1 pieza de FEED por día (kind post | carousel | reel), rotando de tipo si se puede
  - hasta MAX_STORIES_PER_DAY historias por día (kind story) — no cuentan para el feed

Persistencia: JSON en el volume (data/publish-queue.json), igual que tasks_store.
Estados: pending → published | failed | expired (venció esperando, ver PENDING_TTL_DIAS).
"""
from __future__ import annotations

import json
import os
import re
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytz

from ..log import get_logger

log = get_logger("publish_queue")

MAX_ITEMS = 500          # historial total que se conserva
PENDING_TTL_DIAS = 14    # una pieza que no salió en dos semanas ya no es noticia
MAX_STORIES_PER_DAY = 2  # historias diarias (aparte del post/carrusel/reel del feed)
FEED_KINDS = ("post", "carousel", "reel")
# Estados que cuentan como "ya ocupó el cupo de hoy". `parcial` entra: salió en al
# menos una red, y volver a drenar duplicaría la publicación en esa.
PUBLICADO = ("published", "parcial")

# Tope por CARRIL, no uno solo compartido. El feed drena 1/día y las historias 2/día:
# con un tope único el feed se lo comía entero (2026-08-07: 27 de feed contra 3
# historias, cola 30/30) y encima aceptaba mucho más de lo que puede salir antes de
# vencer. Un carril no puede tener más pendientes que lo que drena en PENDING_TTL_DIAS
# — lo que sobra vence sin publicarse y la cuota de Vertex que costó generarlo se tira.
MAX_PENDING_FEED = 14    # 1/día × 14 días de TTL
# A 1/día, una cola que se pasó del tope NO se recupera: mientras drena, lo que vence
# se pierde y `enqueue()` sigue rechazando lo nuevo. El 2026-08-17 había 15 pendientes
# de feed, el más viejo del 03/08, y 5 vencieron sin publicarse. Mientras esté por
# encima del tope drena a este ritmo; abajo del tope vuelve solo a 1/día.
FEED_CATCHUP = 3
MAX_PENDING_STORY = 6    # 2/día × 3 días: una historia de la semana pasada ya no es historia
LANE_CAP = {"feed": MAX_PENDING_FEED, "story": MAX_PENDING_STORY}
MAX_PENDING = MAX_PENDING_FEED + MAX_PENDING_STORY   # total, para mostrar en el panel


def _lane(kind: str) -> str:
    """Carril de drenado de una pieza. Lo que no es historia va al feed."""
    return "story" if (kind or "post").lower() == "story" else "feed"
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


def pending_count(store: Optional[Dict[str, Any]] = None,
                  lane: Optional[str] = None) -> int:
    """Pendientes en la cola; con `lane` ("feed" | "story"), sólo los de ese carril."""
    store = store or load_store()
    return sum(1 for it in store["items"]
               if it.get("status") == "pending"
               and (lane is None or _lane(it.get("kind")) == lane))


def _dias_de_la_mas_vieja(store: Dict[str, Any]) -> int:
    """Días que lleva esperando la pieza de feed pendiente más vieja."""
    ahora = datetime.now(timezone.utc)
    dias = 0
    for it in store["items"]:
        if it.get("status") != "pending" or _lane(it.get("kind")) != "feed":
            continue
        try:
            d = datetime.fromisoformat(it["created_at"])
        except Exception:
            continue
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        dias = max(dias, (ahora - d).days)
    return dias


def expire_stale() -> int:
    """Vence los pendientes viejos; devuelve cuántos. Sin esto la cola se fosiliza:
    contra 1 pieza de feed por día se encolaban 3, así que el 2026-08-02 lo más viejo
    llevaba 24 días esperando y ocupaba el tope con contenido que ya no aplicaba.
    No se borra nada — queda `expired` en el historial, solo deja de ser publicable."""
    corte = datetime.now(timezone.utc) - timedelta(days=PENDING_TTL_DIAS)
    n = 0
    with _LOCK:
        store = load_store()
        for it in store["items"]:
            if it.get("status") != "pending":
                continue
            try:
                if datetime.fromisoformat(it["created_at"]) < corte:
                    it["status"] = "expired"
                    n += 1
            except Exception:
                pass   # sin fecha usable no se vence: mejor publicarlo que perderlo
        if n:
            save_store(store)
    return n


def free_slots(lane: Optional[str] = None) -> int:
    """Lugares libres. Los agentes lo miran ANTES de generar imágenes: generarlas para
    descartarlas al encolar quema cuota de Vertex al pedo (el 2026-08-02 se generaron
    18, entró 1, y de paso nos comimos varios 429).

    Hay que pedirlo POR CARRIL: el total no sirve para decidir si generar una historia
    cuando lo que está lleno es el feed."""
    store = load_store()
    if lane:
        return max(0, LANE_CAP.get(lane, 0) - pending_count(store, lane))
    return sum(max(0, cap - pending_count(store, ln)) for ln, cap in LANE_CAP.items())


def _clean_caption(caption: str) -> str:
    """El modelo a veces escribe `\\n` literal en vez de saltos de línea reales."""
    return (caption or "").replace("\\n", "\n").strip()


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
        if it.get("status") in PUBLICADO
        and _art_date(it.get("published_at", "")) == today
        and _is_ig_fb(it) and _kind(it) in FEED_KINDS
        and not it.get("recorded")          # record_published no cuenta
    )


def stories_published_today(store: Optional[Dict[str, Any]] = None) -> int:
    store = store or load_store()
    today = _today_art()
    return sum(
        1 for it in store["items"]
        if it.get("status") in PUBLICADO
        and _art_date(it.get("published_at", "")) == today
        and _kind(it) == "story"
    )


def _sumar_rechazo(nombre: str, origen: str) -> None:
    """Cuenta los rechazos por nombre de tercero, por día y por agente.

    Sin este número el gate es invisible: nadie sabe si frenó una pieza o mil, ni
    qué agente las está generando. Va al mismo store que la cola para no sumar otro
    archivo que después nadie limpia.
    """
    try:
        with _LOCK:
            store = load_store()
            reg = store.setdefault("rechazos_nombre_tercero", {})
            dia = reg.setdefault(_today_art(), {})
            clave = f"{origen or '?'}:{nombre}"
            dia[clave] = dia.get(clave, 0) + 1
            # Sólo los últimos 30 días: un contador que crece para siempre es otra
            # lista que nadie limpia.
            for viejo in sorted(reg)[:-30]:
                reg.pop(viejo, None)
            save_store(store)
    except Exception as e:
        log.warning("no pude contar el rechazo: %s", str(e)[:120])


def rechazos_de_hoy() -> Dict[str, int]:
    """Rechazos por nombre de tercero de hoy, para que el agente lo reporte."""
    try:
        return dict(load_store().get("rechazos_nombre_tercero", {}).get(_today_art(), {}))
    except Exception:
        return {}


def _clientes_no_nombrables() -> List[str]:
    """Clientes que NO se pueden nombrar en material público.

    La política es: **sólo CLAMEVET es nombrable**; cualquier otro va en genérico
    ("una distribuidora de Córdoba") salvo permiso escrito. La lista se arma sola
    desde el registro de clientes para que dar de alta uno nuevo no exija acordarse
    de esto — que es exactamente como se filtra un nombre.
    """
    fuera = {"clamevet"}          # el único con permiso
    nombres: List[str] = []
    try:
        from . import clients_store as cs
        for c in cs.list_clients():
            n = (c.get("name") or "").strip()
            if not n or n.lower().startswith("clamevet"):
                continue
            # El nombre entero y también el primer token largo: "Cordoba
            # Automatizaciones (CBA Portones)" tiene que pegar con "CBA Portones"
            # y con "Cordoba Automatizaciones" sueltos.
            nombres.append(n)
            for parte in re.split(r"[()/,]", n):
                parte = parte.strip()
                if len(parte) >= 6 and parte.lower() not in fuera:
                    nombres.append(parte)
    except Exception as e:
        log.warning("no pude leer los clientes para el gate de nombres: %s", str(e)[:120])
    return nombres


def nombre_de_tercero(caption: str) -> str:
    """El nombre de cliente que aparece en el texto, o "" si no hay ninguno.

    Existe porque publicar el nombre de un cliente sin permiso escrito es un
    problema con una persona real del otro lado, y no se deshace borrando el post.
    Se chequea acá —en el ÚNICO punto por el que pasa todo lo que se publica— y no
    en cada agente, porque un gate que hay que acordarse de invocar no es un gate.
    """
    texto = (caption or "").lower()
    if not texto:
        return ""
    for n in _clientes_no_nombrables():
        # Límite de palabra a los costados para que "CBA" no pegue dentro de otra
        # palabra. Sin \b, que el editor lo corrompe a un backspace literal.
        if re.search(r"(?<![\w])" + re.escape(n.lower()) + r"(?![\w])", texto):
            return n
    return ""


def enqueue(image: str, caption: str = "", targets: Optional[List[str]] = None,
            source: str = "", kind: str = "post",
            images: Optional[List[str]] = None) -> Optional[Dict[str, Any]]:
    """Encola una pieza. `kind`: post | story | carousel | reel.
    `images`: lista para carruseles (image = portada). Para reels, `image` es el mp4.
    Devuelve el item, o None si la cola pendiente está llena o si el texto nombra a
    un cliente sin permiso."""
    tercero = nombre_de_tercero(caption)
    if tercero:
        log.warning("pieza RECHAZADA: el texto nombra a «%s», que no es nombrable "
                    "en publico. Origen: %s", tercero, source or "?")
        _sumar_rechazo(tercero, source)
        return None
    kind = (kind or "post").lower()
    if kind not in FEED_KINDS + ("story",):
        kind = "post"
    item = {
        "id": uuid.uuid4().hex[:12],
        "image": image,
        "images": images or None,
        "kind": kind,
        "caption": _clean_caption(caption),
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
        lane = _lane(kind)
        if pending_count(store, lane) >= LANE_CAP[lane]:
            return None
        store["items"].insert(0, item)
        store["items"] = store["items"][:MAX_ITEMS]
        save_store(store)
    return item


def record_published(image: str, caption: str, target: str, result: Dict[str, Any],
                     source: str = "", kind: str = "post") -> Dict[str, Any]:
    """Registra una publicación YA hecha por fuera de la cola (Shorts de YouTube,
    posts de TikTok, reels inline) para que aparezca en la sección Publicaciones.
    No pasa por pending ni cuenta para el tope diario de IG/FB."""
    item = {
        "id": uuid.uuid4().hex[:12],
        "image": image,
        "kind": (kind or "post").lower(),
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
    res = sp.publish(item["image"], _clean_caption(item.get("caption", "")), item.get("targets"),
                     kind=_kind(item), images=item.get("images"))
    # releer el store por si cambió mientras publicábamos
    with _LOCK:
        store = load_store()
        for it in store["items"]:
            if it["id"] == item["id"]:
                it["result"] = res.get("results")
                if res.get("ok"):
                    it["status"] = "published"
                    it["published_at"] = _now()
                elif res.get("parcial"):
                    # Salió en una red y en otra no. NO es "published": el panel
                    # lo mostraba así y media publicación se perdía en silencio.
                    # Queda `published_at` porque ocupó el cupo del día —si no,
                    # el próximo drenaje publicaría otra encima en la red que sí
                    # funcionó— y queda escrito cuál falta para reintentar sólo esa.
                    it["status"] = "parcial"
                    it["published_at"] = _now()
                    it["error"] = "no salió en: " + ", ".join(res.get("fallaron") or [])
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
    # 1) pieza(s) de feed (post/carrusel/reel): 1/día, salvo que la cola esté pasada
    # del tope o que la más vieja esté por vencer — ahí drena de a FEED_CATCHUP.
    cupo = FEED_CATCHUP if (pending_count(store, "feed") > MAX_PENDING_FEED
                            or _dias_de_la_mas_vieja(store) >= PENDING_TTL_DIAS - 3) else 1
    ya = 0 if force else published_today_count(store)
    piezas: List[Dict[str, Any]] = []
    while ya < cupo:
        item = _pick_feed_item(load_store())
        if item is None:
            break
        piezas.append(_publish_item(item))
        ya += 1
    # Vencer DESPUÉS de publicar, no antes: si una pieza llegó a su último día, sale
    # hoy o no sale nunca, y expirarla primero era garantizar lo segundo (2026-08-17:
    # 5 piezas del 03/08 vencieron sin publicarse con el carril parado).
    vencidos = expire_stale()
    if vencidos:
        from ..log import get_logger
        get_logger("publish_queue").info("publish_queue_expired", n=vencidos,
                                         ttl_dias=PENDING_TTL_DIAS)
    if piezas:
        out["feed"] = piezas[0]
        if len(piezas) > 1:
            out["feed_extra"] = piezas[1:]
        out["ok"] = all(p.get("ok", True) for p in piezas)
    else:
        out["feed"] = {"skipped": "ya se publicó hoy" if ya else "cola de feed vacía"}
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


def retry_item(item_id: str) -> bool:
    """Vuelve un item a pending para que el próximo drenaje lo tome de nuevo.

    Si quedó `parcial`, se reintenta SÓLO en las redes que fallaron: los
    `targets` se recortan a esas. Reintentarlo entero duplicaría el posteo en la
    red donde sí salió, que es peor que no reintentarlo.
    """
    with _LOCK:
        store = load_store()
        for it in store["items"]:
            if it.get("id") != item_id:
                continue
            if it.get("status") == "parcial":
                fallaron = [red for red, r in (it.get("result") or {}).items()
                            if not (r or {}).get("ok")]
                if not fallaron:
                    return False
                it["targets"] = fallaron
                it["status"] = "pending"
                it["published_at"] = None
                it["error"] = None
                save_store(store)
                return True
            if it.get("status") == "failed":
                it["status"] = "pending"
                it["error"] = None
                save_store(store)
                return True
        return False


def summary() -> Dict[str, Any]:
    store = load_store()
    return {
        "pending": pending_count(store),
        "published_today": published_today_count(store),
        "stories_today": stories_published_today(store),
        "max_stories_per_day": MAX_STORIES_PER_DAY,
        "max_pending": MAX_PENDING,
        # por carril: con el total solo no se ve CUÁL está lleno, y son topes distintos
        "pending_feed": pending_count(store, "feed"),
        "pending_story": pending_count(store, "story"),
        "max_pending_feed": MAX_PENDING_FEED,
        "max_pending_story": MAX_PENDING_STORY,
        "items": store["items"][:50],
    }
