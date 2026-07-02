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

_COLS = ["id", "name", "vertical", "country", "contact_name", "contact_phone",
         "contact_email", "stage", "notes",
         "currency", "monthly_fee", "services", "status", "start_date",
         "created_at", "updated_at"]

# Estado de la RELACIÓN comercial / facturación (distinto del `stage` del funnel).
# Default "onboarding": un registro nuevo suele ser un PROSPECTO, no un cliente
# facturando. "activo" se setea a mano cuando empieza a pagar (si no, los prospectos
# inflaban `active_count`/ARPU y el auto-archive nunca los tocaba).
BILLING_STATUSES = ["activo", "onboarding", "pausado", "baja"]
DEFAULT_BILLING_STATUS = "onboarding"


# ───────────────────────── helpers ─────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


def _currency_for(country_code: str, given: Any) -> str:
    """Moneda del cliente: la dada, o la default de su país."""
    cur = (str(given or "")).upper().strip()
    if cur:
        return cur
    try:
        from . import localization as loc
        return (loc.get(country_code) or {}).get("currency") or "USD"
    except Exception:
        return "USD"


def _num(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _normalize(data: Dict[str, Any]) -> Dict[str, Any]:
    from . import localization as loc
    country = loc.normalize(data.get("country"))
    status = (data.get("status") or "").lower().strip()
    return {
        "name": (data.get("name") or "").strip() or "Cliente sin nombre",
        "vertical": (data.get("vertical") or "").strip(),
        "country": country,
        "contact_name": (data.get("contact_name") or "").strip(),
        "contact_phone": (data.get("contact_phone") or "").strip(),
        "contact_email": (data.get("contact_email") or "").strip(),
        "stage": data.get("stage") if data.get("stage") in STAGES else DEFAULT_STAGE,
        "notes": (data.get("notes") or "").strip(),
        "currency": _currency_for(country, data.get("currency")),
        "monthly_fee": _num(data.get("monthly_fee")),
        "services": (data.get("services") or "").strip(),
        "status": status if status in BILLING_STATUSES else DEFAULT_BILLING_STATUS,
        "start_date": (str(data.get("start_date") or "")[:10]) or None,
    }


def _row_to_dict(row: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(row)
    for k in ("created_at", "updated_at", "start_date"):
        v = out.get(k)
        if v is not None and not isinstance(v, str):
            out[k] = v.isoformat()
    if out.get("monthly_fee") is not None:
        out["monthly_fee"] = float(out["monthly_fee"])
    return out


def _seed_profile(client_id: str, c: Dict[str, Any]) -> None:
    """Siembra el perfil del cliente en su memoria (best-effort)."""
    try:
        from . import client_memory_store as cms, localization as loc
        fee = c.get("monthly_fee") or 0
        body = (
            f"Cliente: {c.get('name')}\n"
            f"Vertical: {c.get('vertical') or '—'}\n"
            f"País: {loc.label(c.get('country'))}\n"
            f"Etapa: {c.get('stage')}\n"
            f"Estado: {c.get('status') or '—'}\n"
            f"Paga: {fee} {c.get('currency') or ''}/mes · Servicios: {c.get('services') or '—'}\n"
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
                "INSERT INTO clients (id,name,vertical,country,contact_name,contact_phone,"
                "contact_email,stage,notes,currency,monthly_fee,services,status,start_date,"
                "created_at,updated_at) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,COALESCE(%s,now()),now()) "
                "ON CONFLICT (id) DO NOTHING",
                (cid, n["name"], n["vertical"], n["country"], n["contact_name"], n["contact_phone"],
                 n["contact_email"], n["stage"], n["notes"], n["currency"], n["monthly_fee"],
                 n["services"], n["status"], n["start_date"], c.get("created_at")),
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
            "INSERT INTO clients (id,name,vertical,country,contact_name,contact_phone,"
            "contact_email,stage,notes,currency,monthly_fee,services,status,start_date) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (cid, n["name"], n["vertical"], n["country"], n["contact_name"], n["contact_phone"],
             n["contact_email"], n["stage"], n["notes"], n["currency"], n["monthly_fee"],
             n["services"], n["status"], n["start_date"]),
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
    for k in ("name", "vertical", "contact_name", "contact_phone", "contact_email",
              "notes", "services"):
        if k in data and data[k] is not None:
            fields[k] = str(data[k]).strip()
    if data.get("country"):
        from . import localization as loc
        fields["country"] = loc.normalize(data.get("country"))
    if data.get("stage") in STAGES:
        fields["stage"] = data["stage"]
    if data.get("currency"):
        fields["currency"] = str(data["currency"]).upper().strip()
    if "monthly_fee" in data and data["monthly_fee"] is not None and data["monthly_fee"] != "":
        fields["monthly_fee"] = _num(data["monthly_fee"])
    if (data.get("status") or "").lower().strip() in BILLING_STATUSES:
        fields["status"] = data["status"].lower().strip()
    if data.get("start_date"):
        fields["start_date"] = str(data["start_date"])[:10]
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
            # stages legacy fuera de STAGES no deben tirar KeyError → 500 en /api/clients
            counts[r.get("stage") or "?"] = r["n"]
        total = db.fetchone("SELECT count(*) AS n FROM clients")
        counts["total"] = total["n"] if total else 0
        return counts
    clients = _json_load().get("clients", [])
    for c in clients:
        st = c.get("stage", "prospecto")
        counts[st] = counts.get(st, 0) + 1
    counts["total"] = len(clients)
    return counts


# ───────────────────────── facturación / ingresos ─────────────────────────

def _start_month(c: Dict[str, Any]) -> str:
    """Mes de alta del cliente (YYYY-MM). Cae a created_at si no hay start_date."""
    sd = c.get("start_date") or c.get("created_at") or ""
    return str(sd)[:7]


def active_count() -> int:
    """Clientes FACTURANDO: status activo Y fee cargado (un prospecto con status
    'activo' heredado y fee 0 no es un cliente activo del panel)."""
    return sum(1 for c in list_clients()
               if c.get("status") == "activo" and _num(c.get("monthly_fee")) > 0)


def mrr_usd() -> float:
    """Ingreso recurrente mensual (USD) = suma de fees de clientes ACTIVOS."""
    from . import fx_store
    total = 0.0
    for c in list_clients():
        if c.get("status") == "activo":
            total += fx_store.to_usd(c.get("monthly_fee", 0), c.get("currency", "USD"))
    return round(total, 2)


def mrr_usd_for_month(month: str) -> float:
    """MRR (USD) de los clientes activos cuyo mes de alta es <= `month` (YYYY-MM)."""
    from . import fx_store
    total = 0.0
    for c in list_clients():
        if c.get("status") != "activo":
            continue
        if _start_month(c) and _start_month(c) > month:
            continue
        total += fx_store.to_usd(c.get("monthly_fee", 0), c.get("currency", "USD"))
    return round(total, 2)


def revenue_by_client() -> List[Dict[str, Any]]:
    """Lista de clientes con su aporte: fee nativo + USD. Ordenada por USD desc."""
    from . import fx_store
    out = []
    for c in list_clients():
        usd = fx_store.to_usd(c.get("monthly_fee", 0), c.get("currency", "USD"))
        out.append({
            "id": c.get("id"), "name": c.get("name"), "country": c.get("country"),
            "currency": c.get("currency", "USD"), "monthly_fee": c.get("monthly_fee", 0),
            "monthly_fee_usd": usd, "status": c.get("status", "activo"),
            "services": c.get("services", ""), "vertical": c.get("vertical", ""),
        })
    out.sort(key=lambda x: x["monthly_fee_usd"], reverse=True)
    return out


def auto_archive(days: int = 10) -> Dict[str, Any]:
    """Archiva (stage='descartado' → memoria congelada) los clientes/prospectos que
    NO son activos pagos y llevan > `days` días sin movimiento (proxy: updated_at).
    Pensado para correr a diario: libera memoria de los leads/prospectos fríos.
    Los clientes 'activo' (facturando) o ya en 'cliente'/'descartado' NO se tocan."""
    from datetime import timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    archived = []
    for c in list_clients():
        if c.get("stage") in ("cliente", "descartado"):
            continue
        # Sólo protege a los que FACTURAN. Antes se salteaba a todo status "activo",
        # y como ese era el default de cualquier prospecto, el job no archivaba nada.
        if c.get("status") == "activo" and _num(c.get("monthly_fee")) > 0:
            continue
        ts = c.get("updated_at") or c.get("created_at") or ""
        try:
            dt = datetime.fromisoformat(str(ts))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        except Exception:
            continue
        if dt < cutoff:
            update_client(c["id"], {"stage": "descartado"})
            archived.append(c.get("name"))
    return {"archived": len(archived), "names": archived, "days": days}


def summary_billing() -> Dict[str, Any]:
    clients = list_clients()
    by_status = {s: 0 for s in BILLING_STATUSES}
    for c in clients:
        st = c.get("status", "activo")
        by_status[st] = by_status.get(st, 0) + 1
    return {
        "mrr_usd": mrr_usd(),
        "active": active_count(),
        "total": len(clients),
        "by_status": by_status,
        "arpu_usd": round(mrr_usd() / max(active_count(), 1), 2),
    }
