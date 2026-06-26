"""
meta_ads — lee campañas reales de Meta Ads (Graph API) y las normaliza al formato
del panel de Ads (gasto, resultados, ingreso → ROAS/CPL en USD).

Requiere `META_AD_ACCOUNT_ID` (ej. act_1001254446126619) y un token con `ads_read`
(`META_ADS_TOKEN`, cae a `META_PAGE_TOKEN`). Best-effort: si falla, devuelve [].
"""
from __future__ import annotations

from typing import Any, Dict, List

import httpx

from ..config import get_settings
from ..log import get_logger

log = get_logger("meta_ads")
_GRAPH = "https://graph.facebook.com"

# Acciones que cuentan como "resultado" (en orden de prioridad).
_RESULT_ACTIONS = [
    "lead", "onsite_conversion.lead_grouped", "offsite_conversion.fb_pixel_lead",
    "purchase", "offsite_conversion.fb_pixel_purchase", "onsite_conversion.purchase",
    "omni_purchase", "messaging_conversation_started_7d",
    "onsite_conversion.messaging_conversation_started_7d",
    "link_click", "landing_page_view",
]
_REVENUE_ACTIONS = ["purchase", "offsite_conversion.fb_pixel_purchase", "omni_purchase"]
_STATUS_MAP = {"ACTIVE": "activa", "PAUSED": "pausada", "ARCHIVED": "finalizada",
               "DELETED": "finalizada", "CAMPAIGN_PAUSED": "pausada",
               "ADSET_PAUSED": "pausada", "IN_PROCESS": "borrador", "WITH_ISSUES": "activa"}


def _token() -> str:
    s = get_settings()
    return s.meta_ads_token or s.meta_page_token


def account_id() -> str:
    aid = (get_settings().meta_ad_account_id or "").strip()
    if aid and not aid.startswith("act_"):
        aid = "act_" + aid
    return aid


def enabled() -> bool:
    return bool(account_id() and _token())


def _graph(path: str) -> str:
    v = get_settings().meta_graph_version or "v21.0"
    return f"{_GRAPH}/{v}/{path}"


def _pick_results(actions: List[Dict[str, Any]]) -> float:
    by_type = {a.get("action_type"): float(a.get("value", 0) or 0) for a in (actions or [])}
    for t in _RESULT_ACTIONS:
        if by_type.get(t):
            return by_type[t]
    return 0.0


def _pick_revenue(action_values: List[Dict[str, Any]]) -> float:
    by_type = {a.get("action_type"): float(a.get("value", 0) or 0) for a in (action_values or [])}
    for t in _REVENUE_ACTIONS:
        if by_type.get(t):
            return by_type[t]
    return 0.0


def _account_currency(c: httpx.Client, aid: str, tok: str) -> str:
    try:
        r = c.get(_graph(aid), params={"fields": "currency", "access_token": tok})
        return (r.json() or {}).get("currency", "USD") if r.content else "USD"
    except Exception:
        return "USD"


def live_campaigns(date_preset: str = "maximum") -> List[Dict[str, Any]]:
    """Campañas reales con sus insights, normalizadas. Best-effort → [] si falla."""
    if not enabled():
        return []
    from . import fx_store
    aid, tok = account_id(), _token()
    try:
        with httpx.Client(timeout=40) as c:
            cur = _account_currency(c, aid, tok)
            # metadatos de campañas
            rc = c.get(_graph(f"{aid}/campaigns"),
                       params={"fields": "name,objective,effective_status,status", "limit": 100, "access_token": tok})
            meta = {}
            for camp in (rc.json().get("data", []) if rc.content else []):
                meta[camp["id"]] = camp
            # insights por campaña
            ri = c.get(_graph(f"{aid}/insights"),
                       params={"level": "campaign",
                               "fields": "campaign_id,campaign_name,spend,impressions,clicks,actions,action_values",
                               "date_preset": date_preset, "limit": 100, "access_token": tok})
            di = ri.json() if ri.content else {}
            if di.get("error"):
                log.warning("meta_ads_insights_error", msg=di["error"].get("message"))
            out: List[Dict[str, Any]] = []
            seen = set()
            for row in di.get("data", []):
                cid = row.get("campaign_id")
                seen.add(cid)
                m = meta.get(cid, {})
                spend = float(row.get("spend", 0) or 0)
                spend_usd = fx_store.to_usd(spend, cur)
                results = _pick_results(row.get("actions"))
                rev = _pick_revenue(row.get("action_values"))
                rev_usd = fx_store.to_usd(rev, cur)
                out.append(_normalize_row(cid, row.get("campaign_name") or m.get("name"), m,
                                          spend_usd, results, rev_usd, row))
            # campañas sin insights todavía (recién creadas, gasto 0)
            for cid, m in meta.items():
                if cid in seen:
                    continue
                out.append(_normalize_row(cid, m.get("name"), m, 0.0, 0.0, 0.0, {}))
            return out
    except Exception as e:
        log.warning("meta_ads_failed", error=str(e)[:200])
        return []


def _normalize_row(cid, name, meta, spend_usd, results, rev_usd, row) -> Dict[str, Any]:
    status = _STATUS_MAP.get((meta.get("effective_status") or meta.get("status") or "").upper(), "activa")
    return {
        "id": cid, "name": name or "Campaña", "platform": "Meta",
        "objective": (meta.get("objective") or "").replace("OUTCOME_", "").replace("_", " ").title(),
        "status": status, "currency": "USD",
        "spend": round(spend_usd, 2), "spend_usd": round(spend_usd, 2),
        "results": results, "revenue": round(rev_usd, 2), "revenue_usd": round(rev_usd, 2),
        "roas": round(rev_usd / spend_usd, 2) if spend_usd else 0.0,
        "cpl_usd": round(spend_usd / results, 2) if results else 0.0,
        "impressions": int(float(row.get("impressions", 0) or 0)),
        "clicks": int(float(row.get("clicks", 0) or 0)),
        "client_name": "", "source": "meta", "live": True,
    }


def summary() -> Dict[str, Any]:
    camps = live_campaigns()
    spend = sum(c["spend_usd"] for c in camps)
    rev = sum(c["revenue_usd"] for c in camps)
    results = sum(c.get("results", 0) or 0 for c in camps)
    return {
        "connected": True, "account_id": account_id(),
        "spend_usd": round(spend, 2), "revenue_usd": round(rev, 2), "results": results,
        "roas": round(rev / spend, 2) if spend else 0.0,
        "cpl_usd": round(spend / results, 2) if results else 0.0,
        "active": sum(1 for c in camps if c.get("status") == "activa"),
        "total": len(camps),
    }
