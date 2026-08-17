"""
comment_watch — vigía de comentarios en NUESTROS posts de Instagram.

Con la fórmula comment-gate ("Comentá DEMO y te mando...") los comentarios son leads:
hay que responderlos RÁPIDO (mismo principio que el speed-to-lead de WhatsApp). Este
job (cada 2h) trae los comentarios nuevos de los últimos posts vía la Graph API (mismo
token de publicación) y avisa a Discord con quién comentó qué y el link, marcando los
que matchean una keyword de gate (DEMO/STORY/GUIA/...) como 🔥 prioridad.

Dedup por comment_id en data/comment-watch.json. Best-effort.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, List

from ..log import get_logger
from .content_autopsy import _get, _our_media, enabled
from .jsonstore import write_json_atomic

log = get_logger("comment_watch")

_STATE = Path(__file__).resolve().parent.parent.parent / "data" / "comment-watch.json"
# Las keywords del gate ROTAN con cada tanda: en W34/W35 el CTA que plantamos es
# "comentá AGENTE" y las viejas (DEMO/GUIA) ya casi no aparecen. Un comentario que
# no matchea llega a Discord sin 🔥 y se atiende tarde — que es justo lo contrario
# del speed-to-lead que motiva este vigía.
_GATE_WORDS = re.compile(
    r"\b(demo|story|guia|guía|prompt|checklist|info|quiero|agente|agentes|automatiz\w+)\b",
    re.IGNORECASE)
_MAX_SEEN = 4000

# La palabra del gate la elige la pieza, y rota con cada tanda ("comentá AGENTE"
# en W34, once palabras distintas en W35). Mantener la lista a mano es una tarea
# semanal que se olvida y deja los comentarios sin marcar; la fuente de verdad es
# el CAPTION de nuestro propio post, así que se lee de ahí.
_CTA = re.compile(
    r"(?:coment[áa](?:me)?|escrib[íi]|pon[ée]|mand[áa])\s+"
    r"(?:la\s+palabra\s+|el\s+comentario\s+)?[\"'«“]?([A-Za-zÁÉÍÓÚÑáéíóúñ0-9]{3,20})",
    re.IGNORECASE)


def _palabras_del_post(caption: str) -> set:
    """La(s) palabra(s) de gate que pide ESTE post en su caption."""
    return {m.group(1).lower() for m in _CTA.finditer(caption or "")}


def mark_seen(comment_ids: List[str]) -> None:
    """Marca comment_ids como vistos (los usa comment_gate: el webhook ya los
    atendió en tiempo real → el vigía cada 2h no debe re-alertarlos)."""
    if not comment_ids:
        return
    try:
        st = json.loads(_STATE.read_text(encoding="utf-8"))
    except Exception:
        st = {"seen": []}
    seen = set(st.get("seen", []))
    st["seen"] = (list(st.get("seen", [])) +
                  [c for c in comment_ids if c not in seen])[-_MAX_SEEN:]
    write_json_atomic(_STATE, st)


def check(n_posts: int = 12) -> Dict[str, int]:
    """Revisa comentarios nuevos y alerta a Discord. Devuelve contadores."""
    if not enabled():
        return {"ok": False}
    try:
        st = json.loads(_STATE.read_text(encoding="utf-8"))
    except Exception:
        st = {"seen": []}
    seen_list = list(st.get("seen", []))
    seen = set(seen_list)
    new_items: List[Dict] = []
    for m in _our_media(n_posts):
        propias = _palabras_del_post(m.get("caption", ""))
        r = _get(f"{m['id']}/comments",
                 {"fields": "id,text,username,timestamp", "limit": 50})
        for c in (r.get("data") or []):
            cid = c.get("id", "")
            if not cid or cid in seen:
                continue
            seen.add(cid)
            seen_list.append(cid)
            texto = c.get("text") or ""
            new_items.append({"user": c.get("username", "?"),
                              "text": texto[:200],
                              "gate": bool(_GATE_WORDS.search(texto))
                                      or any(p in texto.lower() for p in propias),
                              "permalink": m.get("permalink", "")})
    first_run = not st.get("seeded")
    st["seeded"] = True
    st["seen"] = seen_list[-_MAX_SEEN:]
    write_json_atomic(_STATE, st)
    # La primera corrida solo siembra el estado (no spamear con el histórico).
    if new_items and not first_run:
        try:
            from ..config import get_settings
            from ..clients.discord import DiscordWebhook
            s = get_settings()
            if s.discord_configured:
                gate = [i for i in new_items if i["gate"]]
                rest = [i for i in new_items if not i["gate"]]
                lines = []
                for i in gate[:10]:
                    lines.append(f"🔥 **@{i['user']}**: \"{i['text']}\" — pidió el gate, "
                                 f"responder/DM YA → {i['permalink']}")
                for i in rest[:10]:
                    lines.append(f"· @{i['user']}: \"{i['text']}\" → {i['permalink']}")
                dw = DiscordWebhook(s)
                dw.send_agent_output(
                    agent_name="💬 Comentarios nuevos",
                    text="\n".join(lines)[:1800],
                    run_id="comment-watch",
                    url=s.discord_webhook_for("social"),
                    color=0xE67E22,
                )
                dw.close()
        except Exception as e:
            log.warning("comment_watch_notify_failed", error=str(e)[:150])
    log.info("comment_watch_done", nuevos=len(new_items),
             gate=sum(1 for i in new_items if i["gate"]), seed=first_run)
    return {"ok": True, "nuevos": len(new_items),
            "gate": sum(1 for i in new_items if i["gate"])}
