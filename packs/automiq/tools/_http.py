"""GET compartido por scrape_url y validate_site.

Muchas PyMEs argentinas tienen el certificado vencido o mal encadenado. Con
verificación estricta esos sitios fallaban y el lead quedaba sin contacto
(validate_site se come la excepción y devuelve None). Acá se intenta primero
CON verificación y sólo se reintenta sin ella cuando el fallo es de TLS: los
sitios sanos conservan la validación completa.
"""
from __future__ import annotations

import ssl

import httpx

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

_HEADERS = {"User-Agent": UA, "Accept-Language": "es-AR,es;q=0.9"}


def _is_tls_error(exc: BaseException | None) -> bool:
    """httpx envuelve el error de TLS, así que hay que recorrer las causas."""
    for _ in range(5):
        if exc is None:
            return False
        if isinstance(exc, ssl.SSLError) or "certificate" in str(exc).lower():
            return True
        exc = exc.__cause__ or exc.__context__
    return False


def get(url: str, timeout: float = 20.0) -> httpx.Response:
    """GET normal; ante un error de certificado reintenta sin verificar TLS.

    Cualquier otro fallo se propaga tal cual.
    """
    try:
        return httpx.get(url, headers=_HEADERS, timeout=timeout, follow_redirects=True)
    except Exception as e:
        if not _is_tls_error(e):
            raise
        return httpx.get(url, headers=_HEADERS, timeout=timeout,
                         follow_redirects=True, verify=False)
