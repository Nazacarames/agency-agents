"""
agent_inbox — notas asíncronas ENTRE agentes (colaboración bidireccional).

El handoff viejo (upstream_handoff_block) era unidireccional y hardcodeado por
pares. Esto lo generaliza: cualquier agente deja en su corrida una línea
`NOTA_PARA(<agente>): <texto>` y el destinatario la recibe inyectada en su
próximo prompt (una sola vez). Así web_auditor le pasa un opener a outbound,
content_creator le pide un dato a growth_hacker, etc., sin cablear pares.

Store JSON en data/ (atómico). TTL 7 días, tope por destinatario.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List

from ..log import get_logger
from .jsonstore import write_json_atomic

log = get_logger("agent_inbox")

_FILE = Path(__file__).resolve().parent.parent.parent / "data" / "agent-notes.json"
TTL_DAYS = 7
MAX_PER_RECIPIENT = 10


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load() -> Dict[str, Any]:
    try:
        data = json.loads(_FILE.read_text(encoding="utf-8"))
        data.setdefault("notes", [])
        return data
    except Exception:
        return {"notes": []}


def _save(data: Dict[str, Any]) -> None:
    write_json_atomic(_FILE, data, indent=1)


def _fresh(n: Dict[str, Any]) -> bool:
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(days=TTL_DAYS)
        return datetime.fromisoformat(n["created_at"]) > cutoff
    except Exception:
        return False


def leave(from_agent: str, to_agent: str, note: str) -> bool:
    """Deja una nota para otro agente. Dedup exacto pendiente + tope por destinatario."""
    note = (note or "").strip()
    if not note or from_agent == to_agent:
        return False
    data = _load()
    pending = [n for n in data["notes"]
               if n["to"] == to_agent and not n.get("delivered") and _fresh(n)]
    if any(n["note"] == note for n in pending):
        return False
    if len(pending) >= MAX_PER_RECIPIENT:
        log.warning("agent_inbox_full", to=to_agent, dropped_from=from_agent)
        return False
    data["notes"] = [n for n in data["notes"] if _fresh(n)]   # poda TTL de paso
    data["notes"].append({"from": from_agent, "to": to_agent, "note": note[:500],
                          "created_at": _now(), "delivered": False})
    _save(data)
    log.info("agent_note_left", src=from_agent, to=to_agent, chars=len(note))
    return True


def pop_for(agent: str, max_n: int = 6) -> List[Dict[str, Any]]:
    """Notas pendientes para `agent` (las marca entregadas — se inyectan UNA vez)."""
    data = _load()
    out = []
    for n in data["notes"]:
        if n["to"] == agent and not n.get("delivered") and _fresh(n) and len(out) < max_n:
            n["delivered"] = True
            out.append(n)
    if out:
        _save(data)
    return out


def peek_all() -> List[Dict[str, Any]]:
    """Todas las notas vigentes (para el panel / debug)."""
    return [n for n in _load()["notes"] if _fresh(n)]
