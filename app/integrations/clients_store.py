"""
clients_store — CRM mínimo de CLIENTES de la agencia (no leads de ventas).

Es el registro de clientes/cuentas de Automiq para el dashboard operativo: alta,
edición, estado y notas. Persistencia: JSON en el volume (data/clients-store.json),
mismo patrón atómico que leads_store. El provisioning del CRM por cliente (futuro
agente generador) se enganchará sobre estos registros.
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

STAGES = ["prospecto", "contactado", "reunión", "propuesta", "cliente", "perdido"]


def _data_dir() -> Path:
    return Path(__file__).resolve().parent.parent.parent / "data"


def _store_path() -> Path:
    return _data_dir() / "clients-store.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_store() -> Dict[str, Any]:
    p = _store_path()
    if not p.exists():
        return {"clients": []}
    try:
        with p.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if "clients" not in data:
            data["clients"] = []
        return data
    except Exception:
        return {"clients": []}


def save_store(store: Dict[str, Any]) -> None:
    p = _store_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(store, f, ensure_ascii=False, indent=2)
    os.replace(tmp, p)


def list_clients() -> List[Dict[str, Any]]:
    return load_store().get("clients", [])


def get_client(client_id: str) -> Optional[Dict[str, Any]]:
    for c in list_clients():
        if c.get("id") == client_id:
            return c
    return None


def create_client(data: Dict[str, Any]) -> Dict[str, Any]:
    store = load_store()
    client = {
        "id": uuid.uuid4().hex[:12],
        "name": (data.get("name") or "").strip() or "Cliente sin nombre",
        "vertical": (data.get("vertical") or "").strip(),
        "contact_name": (data.get("contact_name") or "").strip(),
        "contact_phone": (data.get("contact_phone") or "").strip(),
        "contact_email": (data.get("contact_email") or "").strip(),
        "stage": data.get("stage") if data.get("stage") in STAGES else "prospecto",
        "notes": (data.get("notes") or "").strip(),
        "created_at": _now(),
        "updated_at": _now(),
    }
    store["clients"].insert(0, client)
    save_store(store)
    return client


def update_client(client_id: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    store = load_store()
    for c in store["clients"]:
        if c.get("id") == client_id:
            for k in ("name", "vertical", "contact_name", "contact_phone", "contact_email", "notes"):
                if k in data and data[k] is not None:
                    c[k] = str(data[k]).strip()
            if data.get("stage") in STAGES:
                c["stage"] = data["stage"]
            c["updated_at"] = _now()
            save_store(store)
            return c
    return None


def delete_client(client_id: str) -> bool:
    store = load_store()
    before = len(store["clients"])
    store["clients"] = [c for c in store["clients"] if c.get("id") != client_id]
    if len(store["clients"]) != before:
        save_store(store)
        return True
    return False


def summary_counts() -> Dict[str, int]:
    counts = {s: 0 for s in STAGES}
    for c in list_clients():
        st = c.get("stage", "prospecto")
        counts[st] = counts.get(st, 0) + 1
    counts["total"] = len(list_clients())
    return counts
