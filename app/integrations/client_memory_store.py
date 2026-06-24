"""
client_memory_store — memoria POR CLIENTE de la agencia.

Cada registro es un trozo de conocimiento sobre un cliente: su perfil, un report
de un agente (auditoría web, leads, creatividades…), info recaudada o una nota
del CEO. Todos los agentes pueden LEER la memoria del cliente sobre el que
trabajan y ESCRIBIR de vuelta sus hallazgos.

Backend: Postgres (schema `agency`, tabla `client_memory`) si hay DATABASE_URL;
si no, JSON en el volume (data/client-memory.json) como fallback.
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import db

KINDS = ["profile", "report", "audit", "gathered", "note"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _data_dir() -> Path:
    return Path(__file__).resolve().parent.parent.parent / "data"


def _store_path() -> Path:
    return _data_dir() / "client-memory.json"


def _json_load() -> Dict[str, Any]:
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


def _json_save(store: Dict[str, Any]) -> None:
    p = _store_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(store, f, ensure_ascii=False, indent=2)
    os.replace(tmp, p)


def _row_to_dict(row: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(row)
    v = out.get("created_at")
    if v is not None and not isinstance(v, str):
        out["created_at"] = v.isoformat()
    return out


def add_memory(client_id: str, kind: str = "note", agent: str = "",
               title: str = "", content: str = "",
               meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    kind = kind if kind in KINDS else "note"
    meta = meta or {}
    if db.enabled():
        row = db.fetchone(
            "INSERT INTO client_memory (client_id,kind,agent,title,content,meta) "
            "VALUES (%s,%s,%s,%s,%s,%s) "
            "RETURNING id,client_id,kind,agent,title,content,meta,created_at",
            (client_id, kind, agent or "", title or "", content or "", json.dumps(meta)),
        )
        return _row_to_dict(row) if row else {}
    store = _json_load()
    item = {
        "id": uuid.uuid4().hex[:12], "client_id": client_id, "kind": kind,
        "agent": agent or "", "title": title or "", "content": content or "",
        "meta": meta, "created_at": _now(),
    }
    store["items"].insert(0, item)
    _json_save(store)
    return item


def list_memory(client_id: str, kind: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
    if db.enabled():
        if kind:
            rows = db.fetchall(
                "SELECT id,client_id,kind,agent,title,content,meta,created_at "
                "FROM client_memory WHERE client_id=%s AND kind=%s "
                "ORDER BY created_at DESC LIMIT %s", (client_id, kind, limit))
        else:
            rows = db.fetchall(
                "SELECT id,client_id,kind,agent,title,content,meta,created_at "
                "FROM client_memory WHERE client_id=%s "
                "ORDER BY created_at DESC LIMIT %s", (client_id, limit))
        return [_row_to_dict(r) for r in rows]
    items = [i for i in _json_load().get("items", []) if i.get("client_id") == client_id]
    if kind:
        items = [i for i in items if i.get("kind") == kind]
    return items[:limit]


def delete_memory(memory_id: Any) -> bool:
    if db.enabled():
        db.execute("DELETE FROM client_memory WHERE id=%s", (memory_id,))
        return True
    store = _json_load()
    before = len(store["items"])
    store["items"] = [i for i in store["items"] if str(i.get("id")) != str(memory_id)]
    if len(store["items"]) != before:
        _json_save(store)
        return True
    return False


def context_digest(client_id: str, max_items: int = 12, max_chars: int = 4000) -> str:
    """Bloque de texto compacto con la memoria del cliente para inyectar en el prompt."""
    items = list_memory(client_id, limit=max_items)
    if not items:
        return ""
    lines: List[str] = []
    for it in items:
        head = f"[{it.get('kind')}" + (f"·{it.get('agent')}" if it.get("agent") else "") + "]"
        title = it.get("title") or ""
        content = (it.get("content") or "").strip()
        block = f"{head} {title}\n{content}".strip()
        lines.append(block)
    digest = "\n\n".join(lines)
    return digest[:max_chars]
