"""
finance_store — gastos de la agencia y resumen de finanzas (ingresos/gastos/ganancia).

Los GASTOS se cargan acá (categoría + monto + moneda + fecha). Los INGRESOS salen de
los fees de los clientes activos (clients_store), convertidos a USD vía fx_store.
Ganancia = ingresos − gastos. Todo se totaliza en USD; las series son por mes.
Persistencia: JSON en el volume (data/finance-store.json).
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytz

CATEGORIES = ["sueldos", "herramientas", "infra", "ads", "impuestos", "otros"]
MAX_ITEMS = 2000
_TZ = pytz.timezone("America/Buenos_Aires")


def _data_dir() -> Path:
    return Path(__file__).resolve().parent.parent.parent / "data"


def _store_path() -> Path:
    return _data_dir() / "finance-store.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today() -> str:
    return datetime.now(_TZ).strftime("%Y-%m-%d")


def _month_of(date_str: str) -> str:
    return (date_str or "")[:7]  # YYYY-MM


def load_store() -> Dict[str, Any]:
    p = _store_path()
    if not p.exists():
        return {"expenses": []}
    try:
        with p.open("r", encoding="utf-8") as f:
            data = json.load(f)
        data.setdefault("expenses", [])
        return data
    except Exception:
        return {"expenses": []}


def save_store(store: Dict[str, Any]) -> None:
    p = _store_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(store, f, ensure_ascii=False, indent=2)
    os.replace(tmp, p)


def add_expense(category: str, label: str, amount: Any, currency: str = "USD",
                date: str = "", recurring: bool = False) -> Dict[str, Any]:
    store = load_store()
    cat = (category or "otros").lower().strip()
    if cat not in CATEGORIES:
        cat = "otros"
    try:
        amt = float(amount or 0)
    except (TypeError, ValueError):
        amt = 0.0
    item = {
        "id": uuid.uuid4().hex[:12],
        "category": cat,
        "label": (label or "").strip() or cat.capitalize(),
        "amount": amt,
        "currency": (currency or "USD").upper().strip(),
        "date": (date or _today())[:10],
        "recurring": bool(recurring),
        "created_at": _now(),
    }
    store["expenses"].insert(0, item)
    store["expenses"] = store["expenses"][:MAX_ITEMS]
    save_store(store)
    return item


def list_expenses(limit: int = 500) -> List[Dict[str, Any]]:
    items = load_store().get("expenses", [])
    items = sorted(items, key=lambda e: e.get("date", ""), reverse=True)
    return items[:limit]


def delete_expense(expense_id: str) -> bool:
    store = load_store()
    before = len(store["expenses"])
    store["expenses"] = [e for e in store["expenses"] if e.get("id") != expense_id]
    save_store(store)
    return len(store["expenses"]) < before


def _expense_usd(e: Dict[str, Any]) -> float:
    from . import fx_store
    return fx_store.to_usd(e.get("amount", 0), e.get("currency", "USD"))


def expenses_by_category(month: Optional[str] = None) -> Dict[str, float]:
    out: Dict[str, float] = {c: 0.0 for c in CATEGORIES}
    for e in load_store().get("expenses", []):
        if month and _month_of(e.get("date", "")) != month:
            continue
        out[e.get("category", "otros")] = out.get(e.get("category", "otros"), 0.0) + _expense_usd(e)
    return {k: round(v, 2) for k, v in out.items() if v or not month}


def expenses_by_month(months: int = 12) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for e in load_store().get("expenses", []):
        m = _month_of(e.get("date", ""))
        if not m:
            continue
        out[m] = out.get(m, 0.0) + _expense_usd(e)
    return {k: round(v, 2) for k, v in out.items()}


def _recent_months(n: int) -> List[str]:
    now = datetime.now(_TZ)
    out = []
    y, m = now.year, now.month
    for _ in range(n):
        out.append(f"{y:04d}-{m:02d}")
        m -= 1
        if m == 0:
            m = 12
            y -= 1
    return list(reversed(out))


def finance_summary(months: int = 12) -> Dict[str, Any]:
    """Ingresos (MRR de clientes activos), gastos y ganancia. Totales USD + serie mensual."""
    from . import clients_store as cs
    mrr = cs.mrr_usd()                         # ingreso recurrente mensual actual (USD)
    by_month_exp = expenses_by_month()
    this_month = _recent_months(1)[0]
    exp_this = round(by_month_exp.get(this_month, 0.0), 2)

    series_months = _recent_months(months)
    # Ingresos por mes: clientes activos cuyo start_date cae en/antes del mes.
    rev_series = []
    for m in series_months:
        rev_series.append(round(cs.mrr_usd_for_month(m), 2))
    exp_series = [round(by_month_exp.get(m, 0.0), 2) for m in series_months]
    profit_series = [round(r - e, 2) for r, e in zip(rev_series, exp_series)]

    return {
        "currency": "USD",
        "mrr_usd": round(mrr, 2),
        "expenses_month_usd": exp_this,
        "profit_month_usd": round(mrr - exp_this, 2),
        "months": series_months,
        "revenue_series": rev_series,
        "expenses_series": exp_series,
        "profit_series": profit_series,
        "by_category": expenses_by_category(this_month),
        "categories": CATEGORIES,
    }
