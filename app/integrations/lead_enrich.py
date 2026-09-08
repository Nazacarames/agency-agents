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
import time
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
# Rutas donde una PyME argentina publica el mail. Eran sólo ("", "/contacto") y con eso
# los 102 leads que tenían web sin email fallaron TODOS y quedaron marcados como
# imposibles para siempre — 21% del pipeline dado de baja por mirar dos páginas.
# El corte es barato: se para en la primera que devuelve un mail (ver el break), así
# que en el caso bueno sigue siendo 1 request.
_PATHS = ("", "/contacto", "/contacto.html", "/contactanos", "/contactenos",
          "/institucional", "/nosotros", "/quienes-somos", "/empresa")

# Versión de la estrategia de búsqueda. Cuando cambia (más rutas, mejor parseo), los
# leads que fallaron con la estrategia vieja vuelven a ser candidatos: marcarlos como
# "imposible" para siempre por un intento con menos herramientas es tirar pipeline.
_ESTRATEGIA = 2

# Segundos como mucho por lead (todas sus rutas juntas).
_PRESUPUESTO_LEAD = 15.0

# Casillas gratuitas: media PyME argentina publica su contacto en Gmail, asi que
# un mail de estos dominios SI puede ser el del lead aunque no coincida con su web.
_GRATUITOS = {"gmail.com", "hotmail.com", "hotmail.com.ar", "yahoo.com",
              "yahoo.com.ar", "outlook.com", "outlook.com.ar", "live.com",
              "icloud.com", "fibertel.com.ar", "speedy.com.ar"}


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
    # Presupuesto por lead. Con 9 rutas y 6 s cada una, un sitio que cuelga se comía
    # casi un minuto él solo y la corrida entera se iba de tiempo. Se prueban rutas
    # hasta encontrar o hasta agotar el presupuesto, lo que pase primero.
    arranque = time.monotonic()
    for path in _PATHS:
        if time.monotonic() - arranque > _PRESUPUESTO_LEAD:
            log.info("lead_enrich_sin_tiempo", web=web[:60], probadas=_PATHS.index(path))
            break
        url = web.rstrip("/") + path
        try:
            r = httpx.get(url, timeout=4.0, follow_redirects=True,
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
    for e, mismo in sorted(found.items(), key=lambda kv: (not kv[1],)):
        # Un mail de OTRA organización que aparece en la página no es el contacto del
        # lead: el 2026-09-08 la búsqueda devolvió comercializacion@industria.misiones
        # .gob.ar para una maderera privada — escribirle a un organismo público
        # creyendo que es el prospecto es peor que no encontrar nada. Se acepta el
        # dominio propio y las casillas gratuitas (media PyME argentina usa Gmail),
        # pero NO el dominio de un tercero.
        if not mismo and e.split("@")[-1] not in _GRATUITOS:
            log.info("lead_enrich_descartado_dominio_ajeno", email=e, sitio=site_dom)
            continue
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
        if l.get("email") or not l.get("web"):
            continue
        # Un intento por lead POR ESTRATEGIA (no uno para toda la vida): si mejoró la
        # búsqueda, se le da otra oportunidad. Sigue sin hostigar: una vez por versión.
        if int(l.get("_enrich_tried") or 0) >= _ESTRATEGIA:
            continue
        l["_enrich_tried"] = _ESTRATEGIA
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
