"""
hook_vault — el BAÚL DE GANCHOS persistente. Cada gancho que el scout/espía (o el
usuario) guarda queda como plantilla lista para reusar: buscable por nicho, tipo y
likes, con quién lo hizo primero y un "usar este" que lo tira derecho al guion
(tiktok_creator). A diferencia del visual-scout.md (que se REESCRIBE cada semana),
el baúl ACUMULA — es la biblioteca que crece.

Store: data/hook-vault.json  {"items": [...]}. Best-effort: si algo falla, [].
"""
from __future__ import annotations

import json
import random
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from ..log import get_logger

log = get_logger("hook_vault")

_DATA = Path(__file__).resolve().parent.parent.parent / "data"
_FILE = _DATA / "hook-vault.json"
_LOCK = threading.Lock()

TIPOS = ["negación", "curiosidad", "lista", "resultado", "miedo/urgencia",
         "contrarian", "nostalgia", "autoridad"]

# Plantillas semilla probadas (de mirar virales reales + el playbook). El baúl
# arranca con esto y crece solo con lo que el espía de competencia va guardando.
SEED = [
    {"hook": "[X] acaba de matar a [Y]", "tipo": "contrarian", "nicho": "general",
     "fuente": "plantilla viral"},
    {"hook": "Dejá de hacer [X]", "tipo": "negación", "nicho": "general",
     "fuente": "plantilla viral"},
    {"hook": "[NÚMERO] cosas que ojalá hubiera sabido antes de [X]", "tipo": "lista",
     "nicho": "general", "fuente": "plantilla viral"},
    {"hook": "La verdad incómoda de [X] es…", "tipo": "contrarian",
     "nicho": "saas/bots", "fuente": "ManyChat (mirado)"},
    {"hook": "Le puse un [X] a una [PyME] por 7 días y pasó esto", "tipo": "resultado",
     "nicho": "bots/pymes", "fuente": "playbook propio"},
    {"hook": "¿Te acordás cuando [AÑO/época]…?", "tipo": "nostalgia", "nicho": "marca",
     "fuente": "Mercado Libre (mirado)"},
    {"hook": "Si tenés un negocio y todavía hacés [X] a mano, mirá esto", "tipo": "miedo/urgencia",
     "nicho": "bots/pymes", "fuente": "playbook propio"},
    {"hook": "Nadie te cuenta esto de [X]", "tipo": "curiosidad", "nicho": "general",
     "fuente": "plantilla viral"},
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load() -> Dict:
    try:
        return json.loads(_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"items": []}


def _save(store: Dict) -> None:
    _DATA.mkdir(parents=True, exist_ok=True)
    _FILE.write_text(json.dumps(store, ensure_ascii=False, indent=1), encoding="utf-8")


def ensure_seed() -> None:
    """Siembra el baúl si está vacío (primera corrida / volume nuevo)."""
    with _LOCK:
        store = _load()
        if store["items"]:
            return
        for s in SEED:
            store["items"].append({"id": uuid.uuid4().hex[:10], "likes": 0, "uses": 0,
                                   "permalink": "", "added_at": _now(), **s})
        _save(store)


def add(hook: str, tipo: str = "", nicho: str = "", fuente: str = "",
        permalink: str = "", likes: int = 0) -> Optional[Dict]:
    """Guarda un gancho (dedupe por texto). Devuelve el item o None si ya existía."""
    hook = (hook or "").strip()
    if not hook:
        return None
    with _LOCK:
        store = _load()
        low = hook.lower()
        for it in store["items"]:
            if it["hook"].strip().lower() == low:
                # ya estaba: actualizamos likes/fuente si vienen mejores datos
                if likes and likes > it.get("likes", 0):
                    it["likes"] = likes
                    _save(store)
                return None
        item = {"id": uuid.uuid4().hex[:10], "hook": hook, "tipo": tipo or "curiosidad",
                "nicho": nicho or "general", "fuente": fuente, "permalink": permalink,
                "likes": int(likes or 0), "uses": 0, "added_at": _now()}
        store["items"].append(item)
        _save(store)
        log.info("hook_saved", hook=hook[:60], fuente=fuente[:40])
        return item


def list_hooks(q: str = "", tipo: str = "", nicho: str = "") -> List[Dict]:
    """Busca en el baúl. Ordena por likes desc y luego por más nuevo."""
    ensure_seed()
    items = _load()["items"]
    if q:
        ql = q.lower()
        items = [i for i in items if ql in i["hook"].lower() or ql in i.get("fuente", "").lower()]
    if tipo:
        items = [i for i in items if i.get("tipo") == tipo]
    if nicho:
        items = [i for i in items if nicho.lower() in i.get("nicho", "").lower()]
    return sorted(items, key=lambda i: (i.get("likes", 0), i.get("added_at", "")), reverse=True)


def delete(item_id: str) -> bool:
    with _LOCK:
        store = _load()
        before = len(store["items"])
        store["items"] = [i for i in store["items"] if i["id"] != item_id]
        if len(store["items"]) < before:
            _save(store)
            return True
    return False


def mark_used(item_id: str) -> Optional[Dict]:
    with _LOCK:
        store = _load()
        for it in store["items"]:
            if it["id"] == item_id:
                it["uses"] = it.get("uses", 0) + 1
                _save(store)
                return it
    return None


def block(n: int = 8) -> str:
    """Bloque para inyectar a los agentes de contenido: los mejores ganchos del baúl.
    Top 5 por likes + el resto al azar: sin el sampleo, las plantillas sin likes
    (la biblioteca curada) nunca rotarían en los prompts."""
    try:
        items = list_hooks()
        top, rest = items[:5], items[5:]
        if rest and n > len(top):
            top += random.sample(rest, min(n - len(top), len(rest)))
        items = top
        if not items:
            return ""
        lines = [f"- \"{i['hook']}\" (tipo {i.get('tipo','?')}"
                 + (f", visto en {i['fuente']}" if i.get("fuente") else "") + ")"
                 for i in items]
        return ("\n\n=== BAÚL DE GANCHOS (plantillas probadas — adaptá, no copies) ===\n"
                + "\n".join(lines) + "\n=== fin baúl ===\n")
    except Exception:
        return ""
