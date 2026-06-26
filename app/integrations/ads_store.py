"""
ads_store — campañas de ads (Meta/Google/…) que la agencia corre para clientes.

Tracker manual de campañas: presupuesto, gasto, resultados (leads/conversiones),
ingreso atribuido → ROAS y CPL. Todo se totaliza en USD vía fx_store.
Persistencia: JSON en el volume (data/ads-store.json). El gasto de ads NO se mezcla
con finance_store (P&L de la agencia); es una vista aparte de performance.
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

PLATFORMS = ["Meta", "Google", "TikTok", "LinkedIn", "Otro"]
STATUSES = ["activa", "pausada", "finalizada", "borrador"]
MAX_ITEMS = 1000


def _data_dir() -> Path:
    return Path(__file__).resolve().parent.parent.parent / "data"


def _store_path() -> Path:
    return _data_dir() / "ads-store.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _num(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def load_store() -> Dict[str, Any]:
    p = _store_path()
    if not p.exists():
        return {"campaigns": []}
    try:
        with p.open("r", encoding="utf-8") as f:
            data = json.load(f)
        data.setdefault("campaigns", [])
        return data
    except Exception:
        return {"campaigns": []}


def save_store(store: Dict[str, Any]) -> None:
    p = _store_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(store, f, ensure_ascii=False, indent=2)
    os.replace(tmp, p)


def _normalize(data: Dict[str, Any]) -> Dict[str, Any]:
    plat = (data.get("platform") or "Meta")
    plat = plat if plat in PLATFORMS else "Meta"
    status = (data.get("status") or "activa").lower()
    status = status if status in STATUSES else "activa"
    return {
        "name": (data.get("name") or "").strip() or "Campaña sin nombre",
        "client_id": (data.get("client_id") or "").strip(),
        "client_name": (data.get("client_name") or "").strip(),
        "platform": plat,
        "objective": (data.get("objective") or "").strip(),
        "status": status,
        "currency": (data.get("currency") or "USD").upper().strip(),
        "budget": _num(data.get("budget")),
        "spend": _num(data.get("spend")),
        "results": _num(data.get("results")),
        "revenue": _num(data.get("revenue")),
        "start_date": (str(data.get("start_date") or "")[:10]) or None,
        "notes": (data.get("notes") or "").strip(),
    }


def add_campaign(data: Dict[str, Any]) -> Dict[str, Any]:
    store = load_store()
    item = {"id": uuid.uuid4().hex[:12], **_normalize(data), "created_at": _now()}
    store["campaigns"].insert(0, item)
    store["campaigns"] = store["campaigns"][:MAX_ITEMS]
    save_store(store)
    return item


def update_campaign(cid: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    store = load_store()
    for c in store["campaigns"]:
        if c.get("id") == cid:
            c.update(_normalize({**c, **data}))
            save_store(store)
            return c
    return None


def delete_campaign(cid: str) -> bool:
    store = load_store()
    before = len(store["campaigns"])
    store["campaigns"] = [c for c in store["campaigns"] if c.get("id") != cid]
    save_store(store)
    return len(store["campaigns"]) < before


def _view(c: Dict[str, Any]) -> Dict[str, Any]:
    from . import fx_store
    spend_usd = fx_store.to_usd(c.get("spend", 0), c.get("currency", "USD"))
    rev_usd = fx_store.to_usd(c.get("revenue", 0), c.get("currency", "USD"))
    results = c.get("results", 0) or 0
    out = dict(c)
    out["spend_usd"] = round(spend_usd, 2)
    out["revenue_usd"] = round(rev_usd, 2)
    out["roas"] = round(rev_usd / spend_usd, 2) if spend_usd else 0.0
    out["cpl_usd"] = round(spend_usd / results, 2) if results else 0.0
    return out


def list_campaigns() -> List[Dict[str, Any]]:
    return [_view(c) for c in load_store().get("campaigns", [])]


def summary() -> Dict[str, Any]:
    camps = list_campaigns()
    spend = sum(c["spend_usd"] for c in camps)
    rev = sum(c["revenue_usd"] for c in camps)
    results = sum(c.get("results", 0) or 0 for c in camps)
    active = sum(1 for c in camps if c.get("status") == "activa")
    by_platform: Dict[str, float] = {}
    for c in camps:
        by_platform[c["platform"]] = by_platform.get(c["platform"], 0.0) + c["spend_usd"]
    return {
        "spend_usd": round(spend, 2),
        "revenue_usd": round(rev, 2),
        "results": results,
        "roas": round(rev / spend, 2) if spend else 0.0,
        "cpl_usd": round(spend / results, 2) if results else 0.0,
        "active": active,
        "total": len(camps),
        "by_platform": {k: round(v, 2) for k, v in by_platform.items()},
        "platforms": PLATFORMS,
        "statuses": STATUSES,
    }
