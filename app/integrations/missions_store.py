"""
missions_store — misiones del CEO.

Una misión = un objetivo del operador que se reparte a varios agentes de una.
El operador (o yo como CEO) define el objetivo + a qué agentes mandárselo; cada
agente lo recibe como tarea prioritaria. Backend: Postgres (schema `agency`) con
fallback JSON.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import db


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _iso(v: Any) -> Any:
    return v.isoformat() if v is not None and not isinstance(v, str) else v


def _data_dir() -> Path:
    return Path(__file__).resolve().parent.parent.parent / "data"


def _json_path() -> Path:
    return _data_dir() / "missions-store.json"


def _json_load() -> Dict[str, Any]:
    p = _json_path()
    if not p.exists():
        return {"missions": []}
    try:
        data = json.load(p.open(encoding="utf-8"))
        data.setdefault("missions", [])
        return data
    except Exception:
        return {"missions": []}


def _json_save(store: Dict[str, Any]) -> None:
    p = _json_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    json.dump(store, tmp.open("w", encoding="utf-8"), ensure_ascii=False, indent=2)
    os.replace(tmp, p)


def _row(r: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(r)
    for k in ("created_at", "updated_at"):
        if k in out:
            out[k] = _iso(out[k])
    return out


_COLS = "id,objective,agents,client_id,status,run_ids,plan,notes,created_at,updated_at"


def create_mission(objective: str, agents: List[str], client_id: Optional[str] = None,
                   run_ids: Optional[Dict[str, str]] = None, notes: str = "",
                   plan: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    run_ids = run_ids or {}
    plan = plan or []
    if db.enabled():
        r = db.fetchone(
            "INSERT INTO missions (objective,agents,client_id,run_ids,plan,notes) "
            "VALUES (%s,%s,%s,%s,%s,%s) RETURNING " + _COLS,
            (objective, agents, client_id or None, json.dumps(run_ids), json.dumps(plan), notes or ""))
        return _row(r) if r else {}
    store = _json_load()
    mid = (max([int(m.get("id", 0)) for m in store["missions"]], default=0)) + 1
    m = {"id": mid, "objective": objective, "agents": agents, "client_id": client_id,
         "status": "lanzada", "run_ids": run_ids, "plan": plan, "notes": notes,
         "created_at": _now(), "updated_at": _now()}
    store["missions"].insert(0, m)
    _json_save(store)
    return m


def list_missions(limit: int = 50) -> List[Dict[str, Any]]:
    if db.enabled():
        rows = db.fetchall(f"SELECT {_COLS} FROM missions ORDER BY created_at DESC LIMIT %s", (limit,))
        return [_row(r) for r in rows]
    return _json_load()["missions"][:limit]


def update_mission(mission_id: Any, fields: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    allowed = {k: v for k, v in fields.items() if k in ("status", "notes") and v is not None}
    if not allowed:
        return None
    if db.enabled():
        sets = ", ".join(f"{k}=%s" for k in allowed) + ", updated_at=now()"
        r = db.fetchone(f"UPDATE missions SET {sets} WHERE id=%s RETURNING " + _COLS,
                        list(allowed.values()) + [mission_id])
        return _row(r) if r else None
    store = _json_load()
    for m in store["missions"]:
        if str(m.get("id")) == str(mission_id):
            m.update(allowed); m["updated_at"] = _now()
            _json_save(store)
            return m
    return None


def delete_mission(mission_id: Any) -> bool:
    if db.enabled():
        db.execute("DELETE FROM missions WHERE id=%s", (mission_id,))
        return True
    store = _json_load()
    before = len(store["missions"])
    store["missions"] = [m for m in store["missions"] if str(m.get("id")) != str(mission_id)]
    if len(store["missions"]) != before:
        _json_save(store)
        return True
    return False
