"""
landing_facts — los datos DUROS de la landing, medidos, para que las auditorías
no opinen sobre lo que no miraron.

Por qué existe: al 2026-08-12 las tres auditorías (web_auditor, seo_specialist,
growth_hacker) venían reportando hace 22 días que "el H1 del home está vacío".
Es falso: el H1 dice "Automatización con IA a medida que potencia tu empresa",
54 caracteres, y está en el HTML de producción. El hallazgo se repitió en cuatro
cierres del Chief y llegó a cargarse al backlog como si fuera un hecho.

Un hallazgo falso es peor que uno sin ejecutar: consume las tres acciones diarias
del dueño, y con un backlog que acumula edad, encima gana autoridad con el tiempo.

Esto no reemplaza la auditoría — mide lo que es objetivamente medible (qué dice el
H1, cuántos contadores están en cero, qué tags de medición hay) y se lo pone
adelante al agente para que su análisis arranque de los hechos.
"""
from __future__ import annotations

import re
import time
from typing import Any, Dict

from ..log import get_logger

log = get_logger("landing_facts")

URL_DEFECTO = "https://automiq.agency"
_TTL = 3600.0          # las 3 auditorías corren el mismo día: una sola bajada
_CACHE: Dict[str, Any] = {"t": 0.0, "url": "", "datos": {}}


def _texto(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", html)).strip()


def medir(url: str = URL_DEFECTO) -> Dict[str, Any]:
    """Baja el HTML servido y extrae lo verificable. Best-effort: nunca levanta."""
    out: Dict[str, Any] = {"ok": False, "url": url, "error": ""}
    try:
        import httpx
        r = httpx.get(url, timeout=15.0, follow_redirects=True,
                      headers={"User-Agent": "AutomiqAudit/1.0"})
        if r.status_code != 200:
            out["error"] = f"HTTP {r.status_code}"
            return out
        html = r.text
    except Exception as e:
        out["error"] = str(e)[:150]
        log.warning("landing_facts_fetch_failed", url=url, error=out["error"])
        return out

    h1s = [_texto(h) for h in re.findall(r"<h1\b.*?</h1>", html, re.S)]
    titulo = re.search(r"<title\b[^>]*>(.*?)</title>", html, re.S)
    desc = re.search(r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']*)', html, re.I)
    # Contadores en cero: el patrón del home son spans con el número suelto.
    ceros = len(re.findall(r'class="[^"]*(?:count|stat|metric)[^"]*"[^>]*>\s*0\s*<', html, re.I))
    out.update({
        "ok": True,
        "bytes": len(html),
        "h1": h1s[0] if h1s else "",
        "h1_cantidad": len(h1s),
        "title": _texto(titulo.group(1)) if titulo else "",
        "meta_description": (desc.group(1)[:200] if desc else ""),
        "contadores_en_cero": ceros,
        "google_ads": bool(re.search(r"AW-\d+", html)),
        "ga4": bool(re.search(r"G-[A-Z0-9]{6,}", html)),
        "meta_pixel": bool(re.search(r"fbq\(|connect\.facebook\.net", html)),
    })
    return out


def cached(url: str = URL_DEFECTO) -> Dict[str, Any]:
    now = time.time()
    if _CACHE["datos"] and _CACHE["url"] == url and now - float(_CACHE["t"]) < _TTL:
        return dict(_CACHE["datos"])
    datos = medir(url)
    if datos.get("ok"):
        _CACHE.update({"t": now, "url": url, "datos": datos})
    return datos


def bloque(url: str = URL_DEFECTO) -> str:
    """Los hechos medidos, para inyectar antes de que el agente audite."""
    d = cached(url)
    if not d.get("ok"):
        # Sin medición no afirmamos nada: es justo el vacío donde antes se colaba
        # el hallazgo inventado.
        return ("\n\n=== HECHOS DE LA LANDING ===\n"
                f"⚠️ No pude bajar {url} ({d.get('error') or 'sin detalle'}). "
                "NO afirmes nada sobre el HTML del sitio en este reporte: decí que no "
                "se pudo verificar.\n=== fin hechos ===\n")
    h1 = d["h1"]
    return (
        "\n\n=== HECHOS DE LA LANDING (medidos sobre el HTML servido — NO los contradigas) ===\n"
        f"URL: {d['url']} · {d['bytes']} bytes\n"
        f"H1 ({d['h1_cantidad']} en la página): "
        + (f"\"{h1}\" ({len(h1)} caracteres)" if h1 else "**NO HAY H1**") + "\n"
        f"<title>: \"{d['title']}\"\n"
        f"meta description: " + (f"\"{d['meta_description']}\"" if d["meta_description"]
                                 else "**FALTA**") + "\n"
        f"Contadores mostrando 0: {d['contadores_en_cero']}\n"
        f"Medición: Google Ads {'SÍ' if d['google_ads'] else 'NO'} · "
        f"GA4 {'SÍ' if d['ga4'] else 'NO'} · Meta Pixel {'SÍ' if d['meta_pixel'] else 'NO'}\n"
        "Esto está MEDIDO, no estimado. Si tu análisis contradice algo de acá, el "
        "equivocado sos vos: revisá antes de escribirlo. Un hallazgo falso se lleva una "
        "de las tres acciones del día del dueño (el 'H1 vacío' se reportó 22 días "
        "seguidos y el H1 nunca estuvo vacío).\n=== fin hechos ===\n")
