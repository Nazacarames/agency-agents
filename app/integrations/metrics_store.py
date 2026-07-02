"""
metrics_store — snapshots diarios de las métricas clave de la agencia.

Sirve para la línea de crecimiento del panel: MRR (USD), clientes activos, leads en
pipeline y ganancia del mes. Un job del scheduler appendea 1 snapshot/día; en lectura,
si falta el de hoy se calcula y se persiste. Persistencia: JSON en el volume.
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

import pytz

MAX_POINTS = 400  # ~13 meses de snapshots diarios
_LOCK = threading.Lock()  # serializa leer→modificar→guardar (job diario + lecturas del panel)
_TZ = pytz.timezone("America/Buenos_Aires")


def _data_dir() -> Path:
    return Path(__file__).resolve().parent.parent.parent / "data"


def _store_path() -> Path:
    return _data_dir() / "metrics-store.json"


def _today() -> str:
    return datetime.now(_TZ).strftime("%Y-%m-%d")


def load_store() -> Dict[str, Any]:
    p = _store_path()
    if not p.exists():
        return {"points": []}
    try:
        with p.open("r", encoding="utf-8") as f:
            data = json.load(f)
        data.setdefault("points", [])
        return data
    except Exception:
        return {"points": []}


def save_store(store: Dict[str, Any]) -> None:
    p = _store_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(store, f, ensure_ascii=False, indent=2)
    os.replace(tmp, p)


def _compute_today() -> Dict[str, Any]:
    """Snapshot del momento. Best-effort: cada métrica protegida por su try."""
    mrr = active = leads = profit = 0.0
    try:
        from . import clients_store as cs
        mrr = round(cs.mrr_usd(), 2)
        active = cs.active_count()
    except Exception:
        pass
    try:
        from . import leads_store as ls
        leads = ls.summary_counts(ls.load_store()).get("total", 0)
    except Exception:
        pass
    try:
        from . import finance_store as fs
        s = fs.finance_summary(1)
        profit = s.get("profit_month_usd", 0.0)
    except Exception:
        pass
    return {"date": _today(), "mrr_usd": mrr, "active_clients": active,
            "leads_total": leads, "profit_month_usd": profit}


def snapshot(force: bool = False) -> Dict[str, Any]:
    """Guarda (o refresca) el snapshot de hoy y lo devuelve."""
    pt = _compute_today()
    with _LOCK:
        store = load_store()
        points = [p for p in store["points"] if p.get("date") != pt["date"]]
        points.append(pt)
        points.sort(key=lambda p: p.get("date", ""))
        store["points"] = points[-MAX_POINTS:]
        save_store(store)
    return pt


def series() -> Dict[str, Any]:
    """Serie para los charts. Garantiza que el punto de hoy exista."""
    store = load_store()
    today = _today()
    if not any(p.get("date") == today for p in store["points"]):
        snapshot()
        store = load_store()
    pts = store["points"]
    return {
        "dates": [p.get("date") for p in pts],
        "mrr_usd": [p.get("mrr_usd", 0) for p in pts],
        "active_clients": [p.get("active_clients", 0) for p in pts],
        "leads_total": [p.get("leads_total", 0) for p in pts],
        "profit_month_usd": [p.get("profit_month_usd", 0) for p in pts],
    }
