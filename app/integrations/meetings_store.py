"""
meetings_store — agenda de reuniones de la agencia.

El operador agenda reuniones (cliente + día + hora) y el agente meeting_prep las
prepara con toda la memoria del cliente. Backend: Postgres (schema `agency`) con
fallback JSON en el volume.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import db

STATUSES = ["programada", "realizada", "cancelada"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _iso(v: Any) -> Any:
    return v.isoformat() if v is not None and not isinstance(v, str) else v


def _data_dir() -> Path:
    return Path(__file__).resolve().parent.parent.parent / "data"


def _json_path() -> Path:
    return _data_dir() / "meetings-store.json"


def _json_load() -> Dict[str, Any]:
    p = _json_path()
    if not p.exists():
        return {"meetings": []}
    try:
        data = json.load(p.open(encoding="utf-8"))
        data.setdefault("meetings", [])
        return data
    except Exception:
        return {"meetings": []}


def _json_save(store: Dict[str, Any]) -> None:
    p = _json_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    json.dump(store, tmp.open("w", encoding="utf-8"), ensure_ascii=False, indent=2)
    os.replace(tmp, p)


def _row(r: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(r)
    for k in ("scheduled_at", "created_at", "updated_at"):
        if k in out:
            out[k] = _iso(out[k])
    return out


_COLS = "id,client_id,client_name,title,scheduled_at,status,location,notes,prep_ready,created_at,updated_at"


def list_meetings(upcoming_only: bool = False) -> List[Dict[str, Any]]:
    if db.enabled():
        where = "WHERE status='programada'" if upcoming_only else ""
        rows = db.fetchall(f"SELECT {_COLS} FROM meetings {where} ORDER BY scheduled_at ASC")
        return [_row(r) for r in rows]
    items = sorted(_json_load()["meetings"], key=lambda m: m.get("scheduled_at", ""))
    return [m for m in items if not upcoming_only or m.get("status") == "programada"]


def get_meeting(meeting_id: Any) -> Optional[Dict[str, Any]]:
    if db.enabled():
        r = db.fetchone(f"SELECT {_COLS} FROM meetings WHERE id=%s", (meeting_id,))
        return _row(r) if r else None
    return next((m for m in _json_load()["meetings"] if str(m.get("id")) == str(meeting_id)), None)


def create_meeting(client_id: Optional[str], client_name: str, title: str,
                   scheduled_at: str, location: str = "", notes: str = "") -> Dict[str, Any]:
    if db.enabled():
        r = db.fetchone(
            "INSERT INTO meetings (client_id,client_name,title,scheduled_at,location,notes) "
            "VALUES (%s,%s,%s,%s,%s,%s) RETURNING " + _COLS,
            (client_id or None, client_name or "", title or "Reunión", scheduled_at,
             location or "", notes or ""))
        return _row(r) if r else {}
    store = _json_load()
    mid = (max([int(m.get("id", 0)) for m in store["meetings"]], default=0)) + 1
    m = {"id": mid, "client_id": client_id, "client_name": client_name, "title": title or "Reunión",
         "scheduled_at": scheduled_at, "status": "programada", "location": location, "notes": notes,
         "prep_ready": False, "created_at": _now(), "updated_at": _now()}
    store["meetings"].append(m)
    _json_save(store)
    return m


def update_meeting(meeting_id: Any, fields: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    allowed = {k: v for k, v in fields.items()
               if k in ("title", "scheduled_at", "status", "location", "notes", "prep_ready") and v is not None}
    if not allowed:
        return get_meeting(meeting_id)
    if db.enabled():
        sets = ", ".join(f"{k}=%s" for k in allowed) + ", updated_at=now()"
        r = db.fetchone(f"UPDATE meetings SET {sets} WHERE id=%s RETURNING " + _COLS,
                        list(allowed.values()) + [meeting_id])
        return _row(r) if r else None
    store = _json_load()
    for m in store["meetings"]:
        if str(m.get("id")) == str(meeting_id):
            m.update(allowed); m["updated_at"] = _now()
            _json_save(store)
            return m
    return None


def delete_meeting(meeting_id: Any) -> bool:
    if db.enabled():
        db.execute("DELETE FROM meetings WHERE id=%s", (meeting_id,))
        return True
    store = _json_load()
    before = len(store["meetings"])
    store["meetings"] = [m for m in store["meetings"] if str(m.get("id")) != str(meeting_id)]
    if len(store["meetings"]) != before:
        _json_save(store)
        return True
    return False
