"""
validate_site — extrae email + teléfono con prefijo +54 de un sitio.

Recorre /, /contacto, /contact, /quienes-somos, /about y devuelve el
primer contacto útil.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Optional
from urllib.parse import urlparse

from . import _http

_PHONE_RE = re.compile(
    r"(?:\+?54[\s\-]?)?(?:0?11[\s\-]?)?(?:15[\s\-]?)?(\(?\d{2,4}\)?[\s\-]?\d{3,4}[\s\-]?\d{3,4})"
)
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_BAD_EMAIL = ("example.com", "noreply", "no-reply", "sentry.io", "wixpress",
              "wordpress", ".png", ".jpg", ".svg")


def _normalize(raw: str) -> Optional[str]:
    digits = re.sub(r"[^\d+]", "", raw or "")
    if not digits or "*" in raw:
        return None
    if digits.startswith("+54"):
        return digits
    if digits.startswith("54") and len(digits) >= 10:
        return "+" + digits
    if len(digits) >= 10 and not digits.startswith("0"):
        return "+549" + digits if not digits.startswith("549") else digits
    return None


def _is_email(addr: str) -> bool:
    a = (addr or "").lower()
    return a and "@" in a and not any(b in a for b in _BAD_EMAIL)


def _try(url: str, timeout: float) -> Optional[str]:
    try:
        r = _http.get(url, timeout=timeout)
        return None if r.status_code >= 400 else r.text
    except Exception:
        return None


def validate_site(domain_or_url: str, timeout: float = 20.0) -> Dict[str, Any]:
    if not domain_or_url:
        return {"error": "empty_domain"}
    url = domain_or_url.strip()
    if not url.startswith("http://") and not url.startswith("https://"):
        url = "https://" + url
    parsed = urlparse(url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    paths = ["", "/contacto", "/contact", "/contactanos", "/quienes-somos", "/about"]

    for path in paths[:4]:
        target = base + path
        html = _try(target, timeout)
        if not html:
            continue
        try:
            from bs4 import BeautifulSoup
            text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
        except Exception:
            continue

        email = None
        for m in _EMAIL_RE.finditer(text):
            if _is_email(m.group(0)):
                email = m.group(0)
                break
        phone = None
        for m in _PHONE_RE.finditer(text):
            norm = _normalize(m.group(0))
            if not norm:
                continue
            d = re.sub(r"[^\d]", "", norm)
            if 10 <= len(d) <= 13 and "*" not in norm:
                phone = norm
                break

        if email or phone:
            return {"telefono": phone, "email": email, "source_url": target}

    return {"error": "no_contact_found"}
