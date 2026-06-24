"""
clients_store — CRM mínimo de CLIENTES de la agencia (no leads de ventas).

Registro de clientes/cuentas de Automiq para el dashboard operativo: alta,
edición, estado y notas. Backend: Postgres (Supabase, schema `agency`) si
`DATABASE_URL` está configurada; si no, JSON en el volume (fallback).

Al crear un cliente se siembra automáticamente su "perfil" en la memoria por
cliente (`client_memory`), de modo que cualquier agente que trabaje sobre él
arranca con su contexto. El provisioning del CRM por cliente (futuro agente
generador) se engancha sobre estos registros.
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import db

# Funnel de la agencia. 'oferta' = preparás la propuesta/oferta para conseguir la
# reunión (primera etapa, default). 'descartado' es TERMINAL: congela la memoria
# del cliente (los agentes dejan de leerla y de escribirle).
STAGES = ["oferta", "reunión", "negociación", "cliente", "descartado"]
FROZEN_STAGES = {"descartado"}
DEFAULT_STAGE = "oferta"

_COLS = ["id", "name", "vertical", "contact_name", "contact_phone",
         "contact_email", "stage", "notes", "created_at", "updated_at"]


# ───────────────────────── helpers ─────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


def _normalize(data: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "name": (data.get("name") or "").strip() or "Cliente sin nombre",
        "vertical": (data.get("vertical") or "").strip(),
        "contact_name": (data.get("contact_name") or "").strip(),
        "contact_phone": (data.get("contact_phone") or "").strip(),
        "contact_email": (data.get("contact_email") or "").strip(),
        "stage": data.get("stage") if data.get("stage") in STAGES else DEFAULT_STAGE,
        "notes": (data.get("notes") or "").strip(),
    }


def _row_to_dict(row: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(row)
    for k in ("created_at", "updated_at"):
        v = out.get(k)
        if v is not None and not isinstance(v, str):
            out[k] = v.isoformat()
    return out


def _seed_profile(client_id: str, c: Dict[str, Any]) -> None:
    """Siembra el perfil del cliente en su memoria (best-effort)."""
    try:
        from . import client_memory_store as cms
        body = (
            f"Cliente: {c.get('name')}\n"
            f"Vertical: {c.get('vertical') or '—'}\n"
            f"Etapa: {c.get('stage')}\n"
            f"Contacto: {c.get('contact_name') or '—'} · "
            f"{c.get('contact_phone') or ''} {c.get('contact_email') or ''}\n"
            f"Notas: {c.get('notes') or '—'}"
        )
        cms.add_memory(client_id, kind="profile", agent="", title="Perfil del cliente", content=body)
    except Exception:
        pass


# ───────────────────────── modo JSON (fallback) ─────────────────────────

def _data_dir() -> Path:
    return Path(__file__).resolve().parent.parent.parent / "data"


def _store_path() -> Path:
    return _data_dir() / "clients-store.json"


def _json_load() -> Dict[str, Any]:
    p = _store_path()
    if not p.exists():
        return {"clients": []}
    try:
        with p.open("r", encoding="utf-8") as f:
            data = json.load(f)
        data.setdefault("clients", [])
        return data
    except Exception:
        return {"clients": []}


def _json_save(store: Dict[str, Any]) -> None:
    p = _store_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(store, f, ensure_ascii=False, indent=2)
    os.replace(tmp, p)


# ───────────────────────── migración JSON → DB ─────────────────────────

_MIGRATED = False


def _migrate_json_if_needed() -> None:
    """Si hay DB y la tabla está vacía pero existe el JSON del volume, importarlo."""
    global _MIGRATED
    if _MIGRATED or not db.enabled():
        return
    _MIGRATED = True
    try:
        row = db.fetchone("SELECT count(*) AS n FROM clients")
        if row and row.get("n", 0) > 0:
            return
        legacy = _json_load().get("clients", [])
        for c in legacy:
            cid = c.get("id") or _new_id()
            n = _normalize(c)
            db.execute(
                "INSERT INTO clients (id,name,vertical,contact_name,contact_phone,"
                "contact_email,stage,notes,created_at,updated_at) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,COALESCE(%s,now()),now()) "
                "ON CONFLICT (id) DO NOTHING",
                (cid, n["name"], n["vertical"], n["contact_name"], n["contact_phone"],
                 n["contact_email"], n["stage"], n["notes"], c.get("created_at")),
            )
            _seed_profile(cid, n)
    except Exception:
        pass


# ───────────────────────── API pública ─────────────────────────

def list_clients() -> List[Dict[str, Any]]:
    if db.enabled():
        _migrate_json_if_needed()
        rows = db.fetchall(f"SELECT {','.join(_COLS)} FROM clients ORDER BY created_at DESC")
        return [_row_to_dict(r) for r in rows]
    return _json_load().get("clients", [])


def get_client(client_id: str) -> Optional[Dict[str, Any]]:
    if db.enabled():
        row = db.fetchone(f"SELECT {','.join(_COLS)} FROM clients WHERE id=%s", (client_id,))
        return _row_to_dict(row) if row else None
    for c in _json_load().get("clients", []):
        if c.get("id") == client_id:
            return c
    return None


def create_client(data: Dict[str, Any]) -> Dict[str, Any]:
    cid = _new_id()
    n = _normalize(data)
    if db.enabled():
        _migrate_json_if_needed()
        db.execute(
            "INSERT INTO clients (id,name,vertical,contact_name,contact_phone,"
            "contact_email,stage,notes) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
            (cid, n["name"], n["vertical"], n["contact_name"], n["contact_phone"],
             n["contact_email"], n["stage"], n["notes"]),
        )
        client = get_client(cid) or {"id": cid, **n}
    else:
        store = _json_load()
        client = {"id": cid, **n, "created_at": _now(), "updated_at": _now()}
        store["clients"].insert(0, client)
        _json_save(store)
    _seed_profile(cid, n)
    return client


def update_client(client_id: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    fields = {}
    for k in ("name", "vertical", "contact_name", "contact_phone", "contact_email", "notes"):
        if k in data and data[k] is not None:
            fields[k] = str(data[k]).strip()
    if data.get("stage") in STAGES:
        fields["stage"] = data["stage"]
    if not fields:
        return get_client(client_id)

    before = get_client(client_id)
    if db.enabled():
        sets = ", ".join(f"{k}=%s" for k in fields) + ", updated_at=now()"
        params = list(fields.values()) + [client_id]
        db.execute(f"UPDATE clients SET {sets} WHERE id=%s", params)
        updated = get_client(client_id)
    else:
        store = _json_load()
        updated = None
        for c in store["clients"]:
            if c.get("id") == client_id:
                c.update(fields)
                c["updated_at"] = _now()
                _json_save(store)
                updated = c
                break
    _learn_from_stage(before, updated)
    return updated


def _learn_from_stage(before: Optional[Dict[str, Any]], after: Optional[Dict[str, Any]]) -> None:
    """Aprendizaje automático: si un cliente pasó a etapa 'cliente' (cerrado/ganado),
    registrar qué vertical convirtió como lección para prospecting y ventas."""
    if not after or not before:
        return
    if before.get("stage") != "cliente" and after.get("stage") == "cliente":
        try:
            from . import memory_store as ms
            vertical = (after.get("vertical") or "sin vertical").strip() or "sin vertical"
            lesson = (f"Venta cerrada en el vertical '{vertical}'. Es un nicho que convierte: "
                      f"buscá más prospectos parecidos y reusá el enfoque que funcionó.")
            ms.record_outcome("leadhunter", lesson, weight=3)
            ms.record_outcome("growth_hacker", lesson, weight=2)
        except Exception:
            pass


def delete_client(client_id: str) -> bool:
    if db.enabled():
        before = get_client(client_id)
        db.execute("DELETE FROM clients WHERE id=%s", (client_id,))  # client_memory cae por FK cascade
        return before is not None
    store = _json_load()
    before = len(store["clients"])
    store["clients"] = [c for c in store["clients"] if c.get("id") != client_id]
    if len(store["clients"]) != before:
        _json_save(store)
        return True
    return False


def is_frozen(client_id: str) -> bool:
    """True si el cliente está en una etapa terminal (descartado) → su memoria se
    congela: los agentes no la leen ni le escriben."""
    c = get_client(client_id)
    return bool(c and c.get("stage") in FROZEN_STAGES)


def summary_counts() -> Dict[str, int]:
    counts = {s: 0 for s in STAGES}
    if db.enabled():
        for r in db.fetchall("SELECT stage, count(*) AS n FROM clients GROUP BY stage"):
            counts[r["stage"]] = r["n"]
        total = db.fetchone("SELECT count(*) AS n FROM clients")
        counts["total"] = total["n"] if total else 0
        return counts
    clients = _json_load().get("clients", [])
    for c in clients:
        st = c.get("stage", "prospecto")
        counts[st] = counts.get(st, 0) + 1
    counts["total"] = len(clients)
    return counts
