"""
Discovery AR — candidatos de empresas desde fuentes públicas (HTTP-only, cheerio).

Estrategias (todas HTTP requests, sin Playwright, sin browser):
  - google_maps_public: scrape del HTML público de búsqueda de Google Maps
    (www.google.com/maps). Frágil, pero sirve para descubrir empresas por
    rubro + ciudad. Devuelve nombre, snippet, link a la ficha.
  - linkedin_public: búsqueda pública de empresas en Google site:linkedin.com
    (no scrapeamos LinkedIn directamente: usamos Google CSE público).
  - site_contact: dado un dominio, scrape de /contact, /contacto, /about y
    extraction de emails, teléfonos y enlaces wa.me/WhatsApp Business.

Importante: ninguna estrategia bypassea login, CAPTCHA o rate-limit. Si la
fuente bloquea, la estrategia devuelve lista vacía y el agente sigue con
lo que tenga. Los resultados NO se asumen verificados: el reporte al final
marca `contacto_verified=false` y deja la verificación al SDR.
"""
from __future__ import annotations

import re
import time
import urllib.parse
from dataclasses import asdict, dataclass
from typing import Iterable, List, Optional

import httpx
from bs4 import BeautifulSoup

from ..log import get_logger

log = get_logger("discovery_ar")

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
DEFAULT_TIMEOUT = 15.0


@dataclass
class Candidate:
    empresa: str
    web: str
    fuente: str
    signal: str
    ciudad: Optional[str] = None
    telefono: Optional[str] = None
    email: Optional[str] = None
    whatsapp: Optional[str] = None
    extra: Optional[dict] = None

    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v is not None}


# ── helpers ──

def _http_get(url: str, timeout: float = DEFAULT_TIMEOUT) -> Optional[str]:
    try:
        r = httpx.get(
            url,
            headers={"User-Agent": USER_AGENT, "Accept-Language": "es-AR,es;q=0.9"},
            timeout=timeout,
            follow_redirects=True,
        )
        if r.status_code >= 400:
            log.warning("discovery_http_error", url=url, status=r.status_code)
            return None
        return r.text
    except Exception as e:
        log.warning("discovery_http_failed", url=url, error=str(e)[:200])
        return None


_PHONE_RE = re.compile(
    r"(\+?54\s?9?\s?\d{2,4}[\s\-]?\d{3,4}[\s\-]?\d{3,4})"
)
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_WA_RE = re.compile(r"(?:wa\.me/|whatsapp\.com/send\?phone=)(\+?\d+)", re.IGNORECASE)


def _extract_contacts(html: str) -> dict:
    """Extrae teléfono, email y whatsapp de un HTML."""
    text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
    phone = None
    m = _PHONE_RE.search(text)
    if m:
        phone = m.group(1).strip()
    email = None
    m = _EMAIL_RE.search(text)
    if m:
        email = m.group(0).strip()
    wa = None
    m = _WA_RE.search(html)  # wa.me aparece en hrefs, no en texto
    if m:
        wa = m.group(1).strip()
    return {"telefono": phone, "email": email, "whatsapp": wa}


# ── estrategia 1: Google Maps público (search results HTML) ──

def _google_maps_search(query: str, ciudad: str) -> List[Candidate]:
    """Scrape la página pública de Google Maps search (sin auth).

    Devuelve una lista de candidatos con nombre + link a la ficha de Maps.
    No entra a cada ficha: solo captura lo que aparece en el listado.
    """
    q = f"{query} en {ciudad}, Argentina"
    url = "https://www.google.com/maps/search/" + urllib.parse.quote(q)
    html = _http_get(url)
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    cands: List[Candidate] = []
    # Google Maps SSR markup: anchors con href que apuntan a /maps/place/...
    for a in soup.select("a[href*='/maps/place/']"):
        href = a.get("href", "")
        name = a.get_text(" ", strip=True) or a.get("aria-label", "")
        if not name or len(name) < 3:
            continue
        if len(cands) >= 5:
            break
        cands.append(Candidate(
            empresa=name[:120],
            web=("https://www.google.com" + href) if href.startswith("/") else href,
            fuente="google_maps_public",
            signal=f"listed_in_maps_search:{q}",
            ciudad=ciudad,
        ))
    log.info("discovery_google_maps", ciudad=ciudad, query=query, hits=len(cands))
    return cands


# ── estrategia 2: LinkedIn público vía Google search (site:linkedin.com) ──

def _linkedin_public(query: str, ciudad: str) -> List[Candidate]:
    """Busca empresas en Google con site:linkedin.com (no entra a LinkedIn)."""
    q = f'site:linkedin.com/company "{query}" "{ciudad}"'
    url = "https://www.google.com/search?" + urllib.parse.quote(q, safe="=:/&?")
    html = _http_get(url)
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    cands: List[Candidate] = []
    for a in soup.select("a[href*='linkedin.com/company']"):
        href = a.get("href", "")
        # Google wraps URLs en /url?q=...
        if "/url?q=" in href:
            try:
                href = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)["q"][0]
            except Exception:
                pass
        # nombre suele estar en el texto del anchor
        name = a.get_text(" ", strip=True)
        if not name or len(name) < 3 or "linkedin" in name.lower():
            # intentar con el h3 cercano
            h3 = a.find_parent().find("h3") if a.find_parent() else None
            if h3:
                name = h3.get_text(" ", strip=True)
        if not name or len(name) < 3:
            continue
        if len(cands) >= 5:
            break
        cands.append(Candidate(
            empresa=name[:120],
            web=href,
            fuente="linkedin_public_google",
            signal=f"linkedin_company_search:{q}",
            ciudad=ciudad,
        ))
    log.info("discovery_linkedin", ciudad=ciudad, query=query, hits=len(cands))
    return cands


# ── estrategia 3: extractor de contacto desde sitio propio ──

def _site_contact(domain: str) -> dict:
    """Scrapea / /contacto /contact /about de un dominio y extrae contactos."""
    if not domain.startswith("http"):
        domain = "https://" + domain
    paths = ["", "/contacto", "/contact", "/contactanos", "/contacto.html",
             "/quienes-somos", "/about", "/empresa"]
    for path in paths:
        url = domain.rstrip("/") + path
        html = _http_get(url, timeout=10.0)
        if not html:
            continue
        contacts = _extract_contacts(html)
        if any(contacts.values()):
            return {"url": url, **contacts}
    return {}


# ── API pública ──

def discover(vertical: str, ciudad: str = "Buenos Aires",
             max_results: int = 12) -> List[Candidate]:
    """Pipeline de discovery para un vertical + ciudad.

    Devuelve hasta `max_results` candidatos únicos. No es exhaustivo: es
    una primera pasada para darle al agente señales reales en vez de
    placeholders inventados.
    """
    out: List[Candidate] = []
    seen = set()

    # Google Maps público
    try:
        for c in _google_maps_search(vertical, ciudad):
            if c.empresa.lower() in seen:
                continue
            seen.add(c.empresa.lower())
            out.append(c)
            if len(out) >= max_results:
                break
    except Exception as e:
        log.warning("discovery_gmaps_failed", error=str(e)[:200])

    # LinkedIn público
    if len(out) < max_results:
        try:
            for c in _linkedin_public(vertical, ciudad):
                if c.empresa.lower() in seen:
                    continue
                seen.add(c.empresa.lower())
                out.append(c)
                if len(out) >= max_results:
                    break
        except Exception as e:
            log.warning("discovery_linkedin_failed", error=str(e)[:200])

    # Para los primeros 4 candidatos, intentar extraer contacto del sitio propio
    enriched = 0
    for c in out[:4]:
        try:
            # intentar derivar dominio del web
            domain = c.web
            if "google.com/maps/place/" in domain:
                # no tenemos URL directa, saltar
                continue
            if "linkedin.com" in domain:
                # no scrapeamos linkedin directamente
                continue
            contacts = _site_contact(domain)
            if contacts:
                c.telefono = contacts.get("telefono")
                c.email = contacts.get("email")
                c.whatsapp = contacts.get("whatsapp")
                c.extra = {"scraped_url": contacts.get("url")}
                enriched += 1
            time.sleep(0.5)  # gentil
        except Exception as e:
            log.warning("site_contact_failed", web=c.web, error=str(e)[:200])
    log.info("discovery_done", vertical=vertical, ciudad=ciudad,
             total=len(out), enriched=enriched)
    return out


def candidates_to_prompt_block(candidates: Iterable[Candidate]) -> str:
    """Formatea candidatos como bloque Markdown para inyectar en el prompt."""
    lines = ["=== EVIDENCIA RECOLECTADA POR DISCOVERY (HTTP público) ===",
             "Usá estos datos como punto de partida REAL. NO inventes leads que no estén aquí.",
             "Si la lista tiene menos de 10, completá con el resto del análisis pero marcá explícitamente `[PENDIENTE discovery]`.",
             ""]
    cands = list(candidates)
    if not cands:
        lines.append("(discovery no devolvió candidatos — el reporte será con placeholders honestos)")
        return "\n".join(lines)
    for i, c in enumerate(cands, 1):
        lines.append(f"### Candidato {i}")
        lines.append(f"- empresa: {c.empresa}")
        if c.ciudad:
            lines.append(f"- ciudad: {c.ciudad}")
        lines.append(f"- web: {c.web}")
        lines.append(f"- fuente: {c.fuente}")
        if c.signal:
            lines.append(f"- signal: {c.signal}")
        if c.telefono:
            lines.append(f"- telefono: {c.telefono}")
        if c.email:
            lines.append(f"- email: {c.email}")
        if c.whatsapp:
            lines.append(f"- whatsapp: {c.whatsapp}")
        if c.extra:
            lines.append(f"- extra: {c.extra}")
        lines.append("")
    return "\n".join(lines)
