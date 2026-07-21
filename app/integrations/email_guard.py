"""
email_guard — última barrera antes de mandar un cold-email.

POR QUÉ
-------
`outbound` valida el destinatario con un regex de FORMA (`_EMAIL_RE`). Eso deja
pasar cualquier cosa bien escrita: `info@adalmi.com.ar` inventado por el modelo
pasa igual que uno real. El 2026-07-21 se habrían enviado 8 así en una corrida.

Los rebotes no son un problema cosmético: son la métrica que más rápido quema la
reputación de un dominio de envío. Con Ventas@automiq.agency recién migrado a
Workspace, un lote con rebotes puede mandar a spam TODOS los envíos siguientes,
incluidos los buenos. El daño es acumulativo y lento de revertir.

CÓMO
----
Chequeo de MX por DNS-over-HTTPS (Google + Cloudflare). Sin dependencia nueva
(dnspython no está instalado) y sin API key. Si el dominio no tiene MX, NADIE
puede recibir mail ahí: el rebote es seguro.

Lo que este módulo NO hace: verificar que la CASILLA exista (SMTP RCPT TO). Los
proveedores de nube bloquean el puerto 25 saliente, así que no correría en
Railway, y además muchos servidores responden 250 a cualquier casilla
(catch-all) — daría una falsa sensación de seguridad. La validación de casilla
real la da el otro control: que el email esté PUBLICADO en el sitio de la
empresa (ver leadhunter._bloque_verificacion).
"""
from __future__ import annotations

import re
from typing import Dict, Tuple

import httpx

from ..log import get_logger

log = get_logger("email_guard")

_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")

_DOH = ("https://dns.google/resolve",
        "https://cloudflare-dns.com/dns-query")

# Cache en proceso: una corrida de outbound toca los mismos dominios varias veces
# (varios contactos de la misma empresa, follow-ups del mismo lote).
_CACHE_MX: Dict[str, bool] = {}

# Placeholders que escribe leadhunter cuando no encontró email real. Si esto
# llega hasta acá es que algo aguas arriba lo dejó pasar como si fuera un mail.
_PLACEHOLDERS = ("sin email", "needs verification", "no encontrado", "n/a",
                 "example.com", "empresa.com")


def tiene_mx(dominio: str) -> bool:
    """True si el dominio publica registros MX. Ante la duda, True.

    Preferimos un falso positivo (mandar a un dominio dudoso) antes que un falso
    negativo: si el DNS se cae o nos rate-limitean, frenar TODO el outbound sería
    peor que arriesgar un rebote.
    """
    dominio = (dominio or "").strip().lower()
    if not dominio:
        return False
    if dominio in _CACHE_MX:
        return _CACHE_MX[dominio]
    for url in _DOH:
        try:
            r = httpx.get(url, params={"name": dominio, "type": "MX"},
                          headers={"Accept": "application/dns-json"}, timeout=8.0)
            if r.status_code != 200:
                continue
            data = r.json()
            # Status 3 = NXDOMAIN: el dominio no existe (typo del modelo).
            if data.get("Status") == 3:
                _CACHE_MX[dominio] = False
                return False
            hay = any(a.get("type") == 15 for a in (data.get("Answer") or []))
            _CACHE_MX[dominio] = hay
            return hay
        except Exception:
            continue
    log.warning("mx_sin_respuesta", dominio=dominio)
    return True   # DNS caído → no frenamos el outbound entero


def es_enviable(email: str) -> Tuple[bool, str]:
    """(se_puede_enviar, motivo). El motivo se loguea para poder auditar."""
    e = (email or "").strip().lower()
    if not e:
        return False, "vacío"
    if any(p in e for p in _PLACEHOLDERS):
        return False, "placeholder, no es un email real"
    if not _RE.match(e):
        return False, "forma inválida"
    dominio = e.split("@")[1]
    if not tiene_mx(dominio):
        return False, f"el dominio {dominio} no tiene MX (rebote seguro)"
    return True, "ok"
