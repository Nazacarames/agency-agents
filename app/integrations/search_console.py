"""
search_console — datos reales de Google Search Console para el web_optimizer.

Sin MCP a propósito: los MCP de GSC son de terceros (npm), meterían otro proceso
Node en el container sosteniendo credenciales de Google, y el objetivo vigente es
no sumar gasto ni RAM. La API REST es una sola llamada y ya tenemos la credencial
(la service account de Vertex, GOOGLE_SERVICE_ACCOUNT_JSON).

⚠️ SETUP MANUAL: la service account tiene que estar agregada como usuario en la
propiedad de Search Console (Configuración → Usuarios y permisos → Agregar, con
el client_email del JSON, permiso "Restringido" alcanza). Sin eso la API
devuelve 403 y todo esto queda deshabilitado con un aviso claro.

Lo que devuelve `snapshot()` NO es el volcado crudo: es la comparación de dos
períodos de 28 días, que es lo único que permite decidir "esto funcionó / esto
no". Un ranking suelto de hoy no dice nada sobre qué mover.
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from ..config import get_settings
from ..log import get_logger

log = get_logger("search_console")

_SCOPE = "https://www.googleapis.com/auth/webmasters.readonly"
_API = "https://searchconsole.googleapis.com/webmasters/v3/sites"

# GSC publica los datos con 2-3 días de atraso; pedir hasta ayer devuelve
# períodos incompletos que parecen caídas de tráfico y no lo son.
_LAG_DAYS = 3
_WINDOW = 28


def enabled() -> bool:
    # GSC_SITE_URL es OPCIONAL: si no está, se descubre solo (ver _resolve_site).
    # Pedirla obligatoria hacía que el usuario tuviera que saber si su propiedad
    # es de dominio ("sc-domain:x") o de prefijo ("https://x/"), y errarle da un
    # 404 que parece problema de permisos.
    return bool(get_settings().google_service_account_json)


def list_sites() -> List[Dict[str, Any]]:
    """Propiedades a las que la service account tiene acceso. Vacío = todavía no
    la agregaste como usuario en Search Console."""
    try:
        r = _session().get(f"{_API}", timeout=30)
        if r.status_code >= 400:
            return []
        return r.json().get("siteEntry", []) or []
    except Exception as e:
        log.warning("gsc_list_sites_failed", error=str(e)[:150])
        return []


def _resolve_site(sess) -> str:
    """La propiedad a consultar: la configurada a mano, o la que se descubra.

    Al descubrir se prefiere la propiedad de DOMINIO: agrupa http/https y todos
    los subdominios, así que ve más datos que una de prefijo de URL.
    """
    manual = getattr(get_settings(), "gsc_site_url", "")
    if manual:
        return manual
    r = sess.get(f"{_API}", timeout=30)
    if r.status_code >= 400:
        raise RuntimeError(f"GSC sites.list {r.status_code}: {r.text[:150]}")
    entries = r.json().get("siteEntry", []) or []
    if not entries:
        raise PermissionError(
            "la service account no tiene ninguna propiedad: agregá su client_email "
            "como usuario en Search Console (Configuración → Usuarios y permisos)")
    urls = [e.get("siteUrl", "") for e in entries]
    dominio = [u for u in urls if u.startswith("sc-domain:")]
    elegida = (dominio or urls)[0]
    log.info("gsc_site_descubierta", elegida=elegida, disponibles=len(urls))
    return elegida


def _session():
    from google.oauth2 import service_account
    from google.auth.transport.requests import AuthorizedSession
    info = json.loads(get_settings().google_service_account_json)
    creds = service_account.Credentials.from_service_account_info(info, scopes=[_SCOPE])
    return AuthorizedSession(creds)


def _query(sess, site: str, start: date, end: date,
           dimensions: List[str], limit: int = 250) -> List[Dict[str, Any]]:
    url = f"{_API}/{quote(site, safe='')}/searchAnalytics/query"
    body = {"startDate": start.isoformat(), "endDate": end.isoformat(),
            "dimensions": dimensions, "rowLimit": limit}
    r = sess.post(url, json=body, timeout=60)
    if r.status_code == 403:
        raise PermissionError(
            "403 de Search Console: falta agregar el client_email de la service "
            "account como usuario en la propiedad")
    if r.status_code >= 400:
        raise RuntimeError(f"GSC {r.status_code}: {r.text[:200]}")
    return r.json().get("rows", []) or []


def _index(rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, float]]:
    return {r["keys"][0]: {"clicks": r.get("clicks", 0),
                           "impressions": r.get("impressions", 0),
                           "ctr": r.get("ctr", 0.0),
                           "position": r.get("position", 0.0)}
            for r in rows if r.get("keys")}


def _delta(now: Dict[str, Dict[str, float]],
           before: Dict[str, Dict[str, float]]) -> List[Dict[str, Any]]:
    """Variación por término entre los dos períodos, ordenada por cambio de
    impresiones. `nuevo` = no existía antes (señal fuerte de contenido que empezó
    a rankear)."""
    out = []
    for k, cur in now.items():
        prev = before.get(k)
        out.append({
            "termino": k,
            "clicks": round(cur["clicks"]),
            "impresiones": round(cur["impressions"]),
            "posicion": round(cur["position"], 1),
            "ctr_pct": round(cur["ctr"] * 100, 1),
            "impresiones_antes": round(prev["impressions"]) if prev else 0,
            "delta_impresiones": round(cur["impressions"] - (prev["impressions"] if prev else 0)),
            "delta_posicion": round((prev["position"] - cur["position"]), 1) if prev else None,
            "nuevo": prev is None,
        })
    out.sort(key=lambda r: r["delta_impresiones"], reverse=True)
    return out


def snapshot() -> Dict[str, Any]:
    """Foto comparada de los últimos 28 días vs los 28 anteriores.

    Best-effort: nunca lanza. Si falla devuelve {"ok": False, "error": ...} para
    que el agente lo lea y lo escriba en la bitácora en vez de inventar datos.
    """
    s = get_settings()
    if not enabled():
        return {"ok": False, "error": "sin GOOGLE_SERVICE_ACCOUNT_JSON"}
    end = date.today() - timedelta(days=_LAG_DAYS)
    start = end - timedelta(days=_WINDOW - 1)
    prev_end = start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=_WINDOW - 1)
    try:
        sess = _session()
        site = _resolve_site(sess)
        q_now = _index(_query(sess, site, start, end, ["query"]))
        q_before = _index(_query(sess, site, prev_start, prev_end, ["query"]))
        p_now = _index(_query(sess, site, start, end, ["page"]))
        p_before = _index(_query(sess, site, prev_start, prev_end, ["page"]))
    except Exception as e:
        log.warning("gsc_snapshot_failed", error=str(e)[:200])
        return {"ok": False, "error": str(e)[:300]}

    terminos = _delta(q_now, q_before)
    paginas = _delta(p_now, p_before)
    tot = lambda d, k: round(sum(v[k] for v in d.values()))  # noqa: E731

    return {
        "ok": True,
        "sitio": site,
        "periodo": f"{start} a {end}",
        "periodo_anterior": f"{prev_start} a {prev_end}",
        "totales": {
            "clicks": tot(q_now, "clicks"), "clicks_antes": tot(q_before, "clicks"),
            "impresiones": tot(q_now, "impressions"),
            "impresiones_antes": tot(q_before, "impressions"),
        },
        # Los 3 cortes que sirven para DECIDIR, no para mirar:
        "subiendo": [t for t in terminos if t["delta_impresiones"] > 0][:20],
        "cayendo": [t for t in terminos if t["delta_impresiones"] < 0][-15:],
        # Posición 8-20: ya rankea pero no entra en página 1. Es donde un empujón
        # de contenido/enlazado interno rinde más por unidad de esfuerzo.
        "a_tiro_de_pagina1": sorted(
            [t for t in terminos if 8 <= t["posicion"] <= 20 and t["impresiones"] >= 5],
            key=lambda t: t["impresiones"], reverse=True)[:20],
        "paginas": paginas[:20],
    }
