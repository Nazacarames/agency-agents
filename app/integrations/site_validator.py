"""
Site validator — dado un dominio, scrapea páginas públicas de contacto y
extrae email + teléfono con prefijo +54.

Se usa desde post_process del agente LeadHunter para mejorar la columna
`contacto_verified` del MD: si encontramos un teléfono con prefijo +54 o
un email, marcamos verified=true con la URL como prueba.

Estrategia:
1. Intenta homepage, /contacto, /contact, /contactanos, /quienes-somos,
   /about, /empresa (en ese orden, con timeout corto).
2. Del HTML extrae: email (regex estándar) y teléfono con prefijo +54 o
   11/15 + código de área argentino.
3. Si no encuentra, devuelve dict vacío (caller decide qué hacer).

Importante: este módulo NO hace scraping de redes sociales ni de Google
Maps. Solo scrapea el sitio de la empresa que el agente ya提名. Es
legal (info pública de contacto), estable y respeta robots.txt básico
(no intenta evadir bloqueos).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from ..log import get_logger

log = get_logger("site_validator")

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
DEFAULT_TIMEOUT = 10.0
MAX_PAGES = 4


# Regex: prefijos argentinos (+54, 0xx, 011, 15, 11) y 8-12 dígitos
_PHONE_RE = re.compile(
    r"(?:\+?54[\s\-]?)?"
    r"(?:0?11[\s\-]?)?"
    r"(?:15[\s\-]?)?"
    r"(\(?\d{2,4}\)?[\s\-]?\d{3,4}[\s\-]?\d{3,4})"
)
_EMAIL_RE = re.compile(
    r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"
)
# Filtro: emails "trampa" típicos de sites (noreply, example, etc.)
_BAD_EMAIL_SUBSTR = ("example.com", "noreply", "no-reply", "sentry.io", "wixpress",
                     "wordpress", ".png", ".jpg", ".svg")


@dataclass
class SiteContact:
    telefono: Optional[str] = None
    email: Optional[str] = None
    source_url: Optional[str] = None
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if v is not None}


def _normalize_phone(raw: str) -> Optional[str]:
    """Limpia el match y devuelve formato +54 9 ... si parece argentino."""
    digits = re.sub(r"[^\d+]", "", raw or "")
    if not digits:
        return None
    if digits.startswith("+54"):
        return digits
    if digits.startswith("54") and len(digits) >= 10:
        return "+" + digits
    # 11 / 15 + 8 dígitos: agregar +54 9 ...
    if len(digits) >= 10 and not digits.startswith("0"):
        return "+549" + digits if not digits.startswith("549") else digits
    return None


def _is_real_email(addr: str) -> bool:
    a = (addr or "").lower()
    return a and not any(b in a for b in _BAD_EMAIL_SUBSTR) and "@" in a


def _try_fetch(url: str, timeout: float) -> Optional[str]:
    try:
        r = httpx.get(
            url,
            headers={"User-Agent": USER_AGENT, "Accept-Language": "es-AR,es;q=0.9"},
            timeout=timeout,
            follow_redirects=True,
        )
        if r.status_code >= 400:
            return None
        return r.text
    except Exception as e:
        log.warning("site_fetch_failed", url=url, error=str(e)[:160])
        return None


def site_phone_digits(domain_or_url: str, timeout: float = DEFAULT_TIMEOUT) -> set:
    """Todos los teléfonos que aparecen en el sitio, como strings de dígitos.

    Sirve para CONTRASTAR lo que el modelo escribió contra la realidad: si el
    número que reportó no está en este set, se lo inventó o lo transcribió mal
    (caso real 2026-07-21: reportó 291 411 1978 y el sitio decía 291 470 1978 —
    un WhatsApp a ese número no llega a nadie y nadie se entera).

    Mira el HTML CRUDO, no el texto visible: los WhatsApp viven en
    `href="https://wa.me/549..."` y `href="tel:+54..."`, que `get_text()` tira.
    """
    if not domain_or_url:
        return set()
    url = domain_or_url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    parsed = urlparse(url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    encontrados: set = set()
    for path in ("", "/contacto", "/contact", "/contactanos"):
        html = _try_fetch(base + path, timeout=timeout)
        if not html:
            continue
        for m in re.finditer(r"(?:wa\.me/|api\.whatsapp\.com/send\?phone=|tel:)\+?(\d{8,15})", html):
            encontrados.add(m.group(1))
        # Y cualquier +54 explícito del HTML crudo: muchos sitios guardan el
        # WhatsApp en un atributo `data-` o en config JS, donde no lo ve ni
        # get_text() ni el patrón wa.me (caso Laco). El "+54" literal es señal
        # suficiente para no traer ruido.
        for m in re.finditer(r"\+54[\s\-]?[\d\s\-]{8,16}", html):
            d = re.sub(r"[^\d]", "", m.group(0))
            if 10 <= len(d) <= 13:
                encontrados.add(d)
        try:
            texto = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
        except Exception:
            texto = html
        for m in _PHONE_RE.finditer(texto):
            d = re.sub(r"[^\d]", "", m.group(0))
            # 10-13 dígitos: abajo de eso son precios, CUITs partidos y años que
            # el regex de teléfono levanta del texto visible.
            if 10 <= len(d) <= 13:
                encontrados.add(d)
    # Sin `break`: el WhatsApp real suele estar en /contacto, no en el home.
    # Cortar en la primera página con algún número escondía el bueno detrás de
    # un teléfono fijo del header (caso Laco).
    return encontrados


def validate_site(domain_or_url: str, timeout: float = DEFAULT_TIMEOUT) -> SiteContact:
    """Scrapea el sitio y devuelve el primer contacto útil encontrado.

    `domain_or_url` puede ser un dominio (example.com) o una URL completa.
    Si la URL no tiene esquema, se le antepone https://.
    """
    if not domain_or_url:
        return SiteContact(error="empty_domain")
    url = domain_or_url.strip()
    if not url.startswith("http://") and not url.startswith("https://"):
        url = "https://" + url
    parsed = urlparse(url)
    base = f"{parsed.scheme}://{parsed.netloc}"

    paths = [
        "",                    # homepage
        "/contacto",
        "/contact",
        "/contactanos",
        "/contacto.html",
        "/quienes-somos",
        "/about",
        "/empresa",
    ][:MAX_PAGES]

    for path in paths:
        target = base + path
        html = _try_fetch(target, timeout=timeout)
        if not html:
            continue
        try:
            soup = BeautifulSoup(html, "html.parser")
        except Exception:
            continue
        text = soup.get_text(" ", strip=True)

        # Email
        email = None
        for m in _EMAIL_RE.finditer(text):
            if _is_real_email(m.group(0)):
                email = m.group(0)
                break
        # Teléfono
        telefono = None
        for m in _PHONE_RE.finditer(text):
            norm = _normalize_phone(m.group(0))
            if not norm:
                continue
            digits = re.sub(r"[^\d]", "", norm)
            # Filtrar falsos positivos: 10-13 dígitos, sin asteriscos/letras
            if "*" in norm or len(digits) < 10 or len(digits) > 13:
                continue
            telefono = norm
            break

        if email or telefono:
            return SiteContact(
                telefono=telefono,
                email=email,
                source_url=target,
            )

    return SiteContact(error="no_contact_found")
