"""
comment_gate — auto-respuesta al comment-gate de Instagram (estilo ManyChat).

Cierra el loop de la fórmula @ai._kid: el post dice "comentá DEMO y te mando...",
Meta nos avisa por webhook (POST /webhook/meta) en tiempo real, y acá:
  1. si el comentario matchea una keyword de gate → DM (private reply de IG,
     válido hasta 7 días después del comentario) con el entregable + reply
     público "te lo mandé por DM" (los replies también alimentan el algoritmo);
  2. avisa a Discord (canal social) SIEMPRE, con qué se respondió.

Permisos que necesita el Page token: instagram_manage_comments (reply público)
+ instagram_manage_messages (private reply). Dedup por comment_id en
data/comment-gate.json. Best-effort: cualquier fallo se loguea y no rompe nada.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Dict, Optional

from ..config import get_settings
from ..log import get_logger
from .comment_watch import _GATE_WORDS, mark_seen
from .jsonstore import write_json_atomic

log = get_logger("comment_gate")

_GRAPH = "https://graph.facebook.com/v21.0"
_STATE = Path(__file__).resolve().parent.parent.parent / "data" / "comment-gate.json"
_MAX_SEEN = 4000

_PUBLIC_REPLY = "¡Te lo mandé por DM! 📩 Si no te llega, revisá las solicitudes de mensaje."


def _post(path: str, payload: Dict) -> Dict:
    s = get_settings()
    url = f"{_GRAPH}/{path}?access_token={urllib.parse.quote(s.meta_page_token)}"
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        return json.load(urllib.request.urlopen(req, timeout=30))
    except urllib.error.HTTPError as e:
        try:
            err = json.load(e)
        except Exception:
            err = {}
        log.warning("gate_graph_error", path=path,
                    error=str((err.get("error") or {}).get("message", ""))[:200])
        return err
    except Exception as ex:
        log.warning("gate_http_failed", path=path, error=str(ex)[:150])
        return {}


def _dm_text(username: str) -> str:
    s = get_settings()
    demo = ""
    try:
        from . import lead_demo
        url = lead_demo.ensure_demo(
            {"company": "tu negocio", "key": "ig-comment-gate", "industria": "distribucion"})
        if url and s.public_base_url:
            demo = s.public_base_url.rstrip("/") + url
    except Exception as e:
        log.warning("gate_demo_failed", error=str(e)[:150])
    lines = [f"¡Hola{' @' + username if username else ''}! 👋 Acá va lo que pediste."]
    if demo:
        lines.append(f"Mirá cómo un agente de IA atiende un negocio real las 24 hs: {demo}")
    lines.append("Si comentaste por una guía/prompt puntual del post, respondeme acá "
                 "y te lo paso al toque. Y si querés esto andando en tu negocio, "
                 "escribime y lo armamos 🙌")
    return "\n\n".join(lines)


def _notify(items: list) -> None:
    try:
        from ..clients.discord import DiscordWebhook
        s = get_settings()
        if not s.discord_configured:
            return
        dw = DiscordWebhook(s)
        dw.send_agent_output(
            agent_name="⚡ Comment-gate (webhook)",
            text="\n".join(items)[:1800],
            run_id="comment-gate",
            url=s.discord_webhook_for("social"),
            color=0x2ECC71,
        )
        dw.close()
    except Exception as e:
        log.warning("gate_notify_failed", error=str(e)[:150])


def handle_event(payload: Dict) -> Dict[str, int]:
    """Procesa un webhook de Meta (object=instagram, field=comments)."""
    if (payload or {}).get("object") != "instagram":
        return {"handled": 0}
    s = get_settings()
    try:
        st = json.loads(_STATE.read_text(encoding="utf-8"))
    except Exception:
        st = {"seen": []}
    seen_list = list(st.get("seen", []))
    seen = set(seen_list)
    handled, alerts, new_cids = 0, [], []

    for entry in payload.get("entry", []) or []:
        for ch in entry.get("changes", []) or []:
            if ch.get("field") != "comments":
                continue
            v = ch.get("value") or {}
            cid = str(v.get("id") or "")
            text = (v.get("text") or "").strip()
            frm = v.get("from") or {}
            username = str(frm.get("username") or "")
            if not cid or cid in seen:
                continue
            seen.add(cid)
            seen_list.append(cid)
            new_cids.append(cid)
            # Nuestros propios comentarios/replies también disparan el webhook:
            # ignorarlos corta el loop infinito (reply → webhook → reply → ...).
            if str(frm.get("id") or "") == str(s.ig_business_id):
                continue
            handled += 1
            gate = bool(_GATE_WORDS.search(text))
            if gate and s.social_publish_configured:
                dm = _post("me/messages", {
                    "recipient": {"comment_id": cid},
                    "message": {"text": _dm_text(username)},
                })
                dm_ok = bool(dm.get("message_id") or dm.get("id"))
                pub_ok = False
                if dm_ok:
                    pub = _post(f"{cid}/replies", {"message": _PUBLIC_REPLY})
                    pub_ok = bool(pub.get("id"))
                alerts.append(
                    f"🔥 **@{username or '?'}**: \"{text[:150]}\" → "
                    f"auto-DM {'✅' if dm_ok else '❌ FALLÓ (revisar permisos del token)'}"
                    f"{' + reply ✅' if pub_ok else ''}")
            elif gate:
                alerts.append(f"🔥 **@{username or '?'}**: \"{text[:150]}\" — gate SIN "
                              f"responder (Meta no configurado): responder a mano")
            else:
                alerts.append(f"· @{username or '?'}: \"{text[:150]}\"")

    if new_cids:
        st["seen"] = seen_list[-_MAX_SEEN:]
        write_json_atomic(_STATE, st)
        mark_seen(new_cids)
    if alerts:
        _notify(alerts)
    log.info("comment_gate_done", handled=handled)
    return {"handled": handled}
