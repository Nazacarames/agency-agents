"""
lead_enrich — enriquece leads sin email buscando uno PUBLICADO en su propio sitio.

Técnica portada de Scout (github.com/kiryano/Scout, MIT): scraping del sitio del lead
para sacar contacto. PERO adaptada a nuestra realidad de deliverability:

  - NO adivina casillas ni verifica por SMTP. El puerto 25 saliente está bloqueado en
    Railway y el probing/guessing genera rebotes, que es lo que más rápido quema la
    reputación del dominio (justo lo que `email_guard` protege). Ver email_guard.py.
  - Solo toma emails que están LITERALMENTE publicados en el sitio de la empresa
    (bajo riesgo de rebote: si lo publican, lo leen) y los pasa por el MX-check.

Así, un lead que tenía web pero no email (hoy va solo a la cola de WhatsApp) puede
pasar a ser contactable por mail. Best-effort: si algo falla, el lead queda igual.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Optional

import httpx

from ..log import get_logger
from . import email_guard

log = get_logger("lead_enrich")

_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
# Basura típica que aparece en el HTML y NO es un contacto real.
_JUNK = ("sentry", "wixpress", "wix.com", "example.", "yourdomain", "domain.com",
         "email.com", "tuempresa", "@2x", ".png", ".jpg", ".jpeg", ".gif", ".webp",
         "godaddy", "cloudflare", "sentry.io", "schema.org", "w3.org")
_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Automiq/1.0"
_PATHS = ("", "/contacto")   # home + contacto; suficiente para PyMEs, acota latencia


def _domain_of(url: str) -> str:
    m = re.sub(r"^https?://", "", (url or "").strip().lower())
    return m.split("/")[0].replace("www.", "")


def find_published_email(web: str) -> Optional[str]:
    """Devuelve un email publicado y con MX válido del sitio, o None."""
    web = (web or "").strip()
    if not web:
        return None
    if not web.startswith("http"):
        web = "https://" + web
    site_dom = _domain_of(web)
    found: Dict[str, bool] = {}   # email -> es del mismo dominio del sitio
    for path in _PATHS:
        url = web.rstrip("/") + path
        try:
            r = httpx.get(url, timeout=6.0, follow_redirects=True,
                          headers={"User-Agent": _UA})
            if r.status_code != 200 or not r.text:
                continue
        except Exception:
            continue
        for m in _EMAIL.findall(r.text):
            e = m.lower().strip(".")
            if len(e) > 80 or any(j in e for j in _JUNK):
                continue
            found.setdefault(e, e.split("@")[-1] == site_dom)
        if found:
            break   # ya encontramos en el home: no pegamos /contacto de gusto
    if not found:
        return None
    # Preferir el email del mismo dominio del sitio; gatear TODOS por MX (email_guard).
    for e, _same in sorted(found.items(), key=lambda kv: (not kv[1],)):
        ok, _motivo = email_guard.es_enviable(e)
        if ok:
            return e
    return None


def enrich_missing_emails(store: Dict[str, Any], limit: int = 4) -> int:
    """Para leads con `web` y sin `email`, busca un email publicado y lo setea.
    Marca `_enrich_tried` para no re-scrapear el mismo sitio cada corrida.
    Muta el store in-place. Devuelve cuántos enriqueció."""
    leads = store.get("leads", {}) or {}
    n = 0
    for key, l in leads.items():
        if n >= limit:
            break
        if l.get("email") or not l.get("web") or l.get("_enrich_tried"):
            continue
        l["_enrich_tried"] = True   # un intento por lead (aunque falle) → no hostiga sitios
        try:
            e = find_published_email(l.get("web"))
        except Exception as ex:
            log.warning("lead_enrich_failed", key=key, error=str(ex)[:100])
            continue
        if e:
            l["email"] = e
            l["channel"] = "email"
            n += 1
            log.info("lead_email_enriched", key=key, dom=e.split("@")[-1])
    return n
