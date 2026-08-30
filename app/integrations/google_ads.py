"""
google_ads — lee campañas reales de Google Ads (API REST) y las normaliza al MISMO
formato que meta_ads (gasto, resultados, ingreso → ROAS/CPL en USD), para que
media_auditor las inyecte igual que las de Meta.

Requiere (env, ver config.Settings): developer token + OAuth client (id/secret) +
refresh_token + customer_id (cuenta a leer, dígitos sin guiones). login_customer_id
solo si se accede vía una cuenta Manager (MCC). Best-effort: si falta config o algo
falla, devuelve [] y el audit cae a [BENCHMARK] como antes.

El refresh_token se saca UNA vez con scripts/google_ads_oauth.py.
"""
from __future__ import annotations

from typing import Any, Dict, List

import httpx

from ..config import get_settings
from ..log import get_logger

log = get_logger("google_ads")

# La API versiona seguido y las viejas se deprecan (~1/año). Si un día responde
# "invalid version", subí este número (v18 vigente al 2026-08). ponytail: knob.
API_VERSION = "v18"
_TOKEN_URL = "https://oauth2.googleapis.com/token"

_STATUS_MAP = {"ENABLED": "activa", "PAUSED": "pausada",
               "REMOVED": "finalizada", "UNKNOWN": "activa", "UNSPECIFIED": "activa"}

# Métricas por campaña de los últimos 30 días (igual ventana que el benchmark del audit).
_GAQL = (
    "SELECT campaign.id, campaign.name, campaign.status, "
    "campaign.advertising_channel_type, metrics.cost_micros, metrics.impressions, "
    "metrics.clicks, metrics.conversions, metrics.conversions_value "
    "FROM campaign WHERE segments.date DURING LAST_30_DAYS"
)


def _cid() -> str:
    return (get_settings().google_ads_customer_id or "").replace("-", "").strip()


def enabled() -> bool:
    s = get_settings()
    return bool(s.google_ads_developer_token and s.google_ads_client_id
               and s.google_ads_client_secret and s.google_ads_refresh_token and _cid())


def _access_token(c: httpx.Client) -> str:
    """Access token efímero a partir del refresh_token. '' si falla."""
    s = get_settings()
    try:
        r = c.post(_TOKEN_URL, data={
            "client_id": s.google_ads_client_id,
            "client_secret": s.google_ads_client_secret,
            "refresh_token": s.google_ads_refresh_token,
            "grant_type": "refresh_token",
        })
        return (r.json() or {}).get("access_token", "") if r.content else ""
    except Exception as e:                                   # noqa: BLE001
        log.warning("google_ads_token_failed", error=str(e)[:200])
        return ""


def _headers(access: str) -> Dict[str, str]:
    s = get_settings()
    h = {"developer-token": s.google_ads_developer_token,
         "Authorization": f"Bearer {access}", "Content-Type": "application/json"}
    lcid = (s.google_ads_login_customer_id or "").replace("-", "").strip()
    if lcid:
        h["login-customer-id"] = lcid                       # solo si se accede vía MCC
    return h


def _search(c: httpx.Client, access: str, query: str) -> List[Dict[str, Any]]:
    """searchStream → lista plana de `results`. [] si falla. Devuelve dicts camelCase."""
    url = f"https://googleads.googleapis.com/{API_VERSION}/customers/{_cid()}/googleAds:searchStream"
    r = c.post(url, headers=_headers(access), json={"query": query})
    if r.status_code != 200:
        log.warning("google_ads_search_error", status=r.status_code, body=r.text[:200])
        return []
    out: List[Dict[str, Any]] = []
    for chunk in (r.json() or []):                          # el stream viene como array de chunks
        out += chunk.get("results", []) or []
    return out


def _currency(c: httpx.Client, access: str) -> str:
    rows = _search(c, access, "SELECT customer.currency_code FROM customer LIMIT 1")
    if rows:
        return ((rows[0].get("customer") or {}).get("currencyCode")) or "USD"
    return "USD"


def live_campaigns(date_preset: str = "maximum") -> List[Dict[str, Any]]:
    """Campañas reales con métricas, normalizadas al formato del panel. [] si falla."""
    if not enabled():
        return []
    from . import fx_store
    try:
        with httpx.Client(timeout=40) as c:
            access = _access_token(c)
            if not access:
                return []
            cur = _currency(c, access)
            rows = _search(c, access, _GAQL)
            out: List[Dict[str, Any]] = []
            for row in rows:
                camp = row.get("campaign") or {}
                m = row.get("metrics") or {}
                spend = int(m.get("costMicros", 0) or 0) / 1_000_000      # micros → moneda cuenta
                spend_usd = fx_store.to_usd(spend, cur)
                results = float(m.get("conversions", 0) or 0)
                rev_usd = fx_store.to_usd(float(m.get("conversionsValue", 0) or 0), cur)
                out.append(_normalize_row(
                    camp.get("id"), camp.get("name"), camp.get("status"),
                    camp.get("advertisingChannelType"), spend_usd, results, rev_usd,
                    int(float(m.get("impressions", 0) or 0)),
                    int(float(m.get("clicks", 0) or 0))))
            return out
    except Exception as e:                                   # noqa: BLE001
        log.warning("google_ads_failed", error=str(e)[:200])
        return []


def _normalize_row(cid, name, status, channel, spend_usd, results, rev_usd,
                   impressions, clicks) -> Dict[str, Any]:
    return {
        "id": str(cid or ""), "name": name or "Campaña", "platform": "Google",
        "objective": (channel or "").replace("_", " ").title(),
        "status": _STATUS_MAP.get((status or "").upper(), "activa"), "currency": "USD",
        "spend": round(spend_usd, 2), "spend_usd": round(spend_usd, 2),
        "results": results, "revenue": round(rev_usd, 2), "revenue_usd": round(rev_usd, 2),
        "roas": round(rev_usd / spend_usd, 2) if spend_usd else 0.0,
        "cpl_usd": round(spend_usd / results, 2) if results else 0.0,
        "impressions": impressions, "clicks": clicks,
        "client_name": "", "source": "google", "live": True,
    }


def summary() -> Dict[str, Any]:
    camps = live_campaigns()
    spend = sum(c["spend_usd"] for c in camps)
    rev = sum(c["revenue_usd"] for c in camps)
    results = sum(c.get("results", 0) or 0 for c in camps)
    return {
        "connected": enabled(), "customer_id": _cid(),
        "spend_usd": round(spend, 2), "revenue_usd": round(rev, 2), "results": results,
        "roas": round(rev / spend, 2) if spend else 0.0,
        "cpl_usd": round(spend / results, 2) if results else 0.0,
        "active": sum(1 for c in camps if c.get("status") == "activa"),
        "total": len(camps),
    }


if __name__ == "__main__":                                  # self-check sin red
    r = _normalize_row("123", "Search AR", "ENABLED", "SEARCH",
                       spend_usd=100.0, results=5.0, rev_usd=300.0,
                       impressions=2000, clicks=80)
    assert r["platform"] == "Google" and r["source"] == "google"
    assert r["status"] == "activa" and r["objective"] == "Search"
    assert r["roas"] == 3.0 and r["cpl_usd"] == 20.0
    z = _normalize_row(None, None, "PAUSED", "PERFORMANCE_MAX", 0.0, 0.0, 0.0, 0, 0)
    assert z["status"] == "pausada" and z["roas"] == 0.0 and z["cpl_usd"] == 0.0
    print("ok google_ads self-check")
