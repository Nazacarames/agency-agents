"""
meta_ad_library — trae creativos REALES de la Biblioteca de Anuncios de Meta
(Graph API `ads_archive`). Fuente primaria del estudio de competencia cuando está
configurado el token.

⚠️ La Ad Library API NO funciona con el system-user token de publicación: Meta exige
un token de USUARIO INDIVIDUAL con "confirmación de identidad" completada
(facebook.com/ads/library/api, proceso manual con documento). Por eso va en su propia
env var `META_AD_LIBRARY_TOKEN` y es best-effort: si no está o falla, devuelve [] y el
estudio cae a las búsquedas web.

Nota de cobertura: para países de la UE (p.ej. ES) la API devuelve TODOS los anuncios
(por la DSA); fuera de la UE (AR) solo devuelve los de temas sociales/políticos. Por eso
para competidores comerciales (Kommo, Zolutium) conviene consultar su versión de España.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

import httpx

from ..config import get_settings
from ..log import get_logger

log = get_logger("meta_ad_library")

_GRAPH = "https://graph.facebook.com/v21.0/ads_archive"
_FIELDS = ("page_name,ad_creative_bodies,ad_creative_link_titles,"
           "ad_creative_link_descriptions,ad_snapshot_url")


def enabled() -> bool:
    return bool(getattr(get_settings(), "meta_ad_library_token", ""))


def search_ads(terms: str, countries=("ES",), limit: int = 8) -> List[Dict[str, Any]]:
    """Devuelve anuncios reales [{page_name, body, title, desc, snapshot_url}] para un
    término. countries: ISO-2 (ES=UE→todos los ads; AR→solo sociales/políticos)."""
    s = get_settings()
    tok = getattr(s, "meta_ad_library_token", "")
    if not tok or not (terms or "").strip():
        return []
    params = {
        "search_terms": terms,
        "ad_reached_countries": json.dumps(list(countries)),
        "ad_type": "ALL",
        "ad_active_status": "ALL",
        "fields": _FIELDS,
        "limit": str(limit),
        "access_token": tok,
    }
    try:
        with httpx.Client(timeout=40) as c:
            r = c.get(_GRAPH, params=params)
            if r.status_code >= 400:
                log.warning("ad_library_error", status=r.status_code, body=r.text[:200])
                return []
            out = []
            for a in (r.json().get("data") or []):
                out.append({
                    "page_name": a.get("page_name", ""),
                    "body": (a.get("ad_creative_bodies") or [""])[0],
                    "title": (a.get("ad_creative_link_titles") or [""])[0],
                    "desc": (a.get("ad_creative_link_descriptions") or [""])[0],
                    "snapshot_url": a.get("ad_snapshot_url", ""),
                })
            log.info("ad_library_ok", terms=terms, n=len(out))
            return out
    except Exception as e:
        log.warning("ad_library_failed", error=str(e)[:200])
        return []
