"""
competitor_study — refresca el playbook de competencia con research REAL.

Corre semanal (scheduler) + on-demand (POST /api/competitor/refresh). Hace búsquedas
reales (Tavily vía web_search) sobre qué contenido rinde en agencias/servicios de IA,
y le pide a MiniMax que las destile en el formato del playbook. Best-effort: si algo
falla, deja el playbook anterior intacto.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

from ..config import get_settings
from ..log import get_logger
from . import competitor_playbook as cp

log = get_logger("competitor_study")

# Competidores de referencia (CRM/IA/automatización en español) a estudiar por nombre.
# Editable: agregá los que el usuario quiera vigilar.
COMPETITORS = [
    "Kommo CRM WhatsApp", "Zolutium IA", "ManyChat español",
    "Leadsales CRM", "Cliengo chatbot", "Tidio IA",
]

_QUERIES = [
    "viral hooks AI agency short form content 2026 what works",
    "best performing reels tiktok AI automation agency 2026 formats",
    "high converting meta ads AI chatbot whatsapp automation 2026 creative",
    "reels tiktok shorts agencias IA automatización español formato viral 2026",
    "contenido IA automatización mercado latino argentina redes que funciona 2026",
]


def _competitor_queries():
    return [f"{c} anuncios reels contenido marketing que usa" for c in COMPETITORS[:6]]


_DISTILL_SYSTEM = (
    "Sos un estratega de contenido para una agencia argentina de automatización con IA. "
    "Te paso resultados de búsqueda REALES sobre qué contenido/anuncios rinden HOY en "
    "agencias y servicios de IA (incluidos competidores concretos como Kommo, Zolutium, "
    "ManyChat). Destilá TODO en un playbook accionable en español rioplatense, con "
    "EXACTAMENTE estas secciones (mismo formato markdown): "
    "'## Regla de los primeros 2 segundos', '## Hooks que más convierten (rankeados por data)', "
    "'## Formatos y duración', '## Video / Shorts (lo que hacen los que la rompen)', "
    "'## Qué hacen los competidores en español (Kommo, Zolutium y afines)', "
    "'## Meta Ads (paid)', '## Estrategia de producción', '## Clichés visuales a EVITAR'. "
    "En la sección de competidores, nombralos y decí qué táctica concreta les funciona "
    "(hook, formato, prueba social, oferta) y cómo diferenciarnos. Tené en cuenta que el "
    "mercado ARGENTINO está MENOS desarrollado en redes que el resto → podemos usar "
    "formatos y calidad más avanzados que la competencia local todavía no usa (ventaja). "
    "Sé concreto y cuantitativo (retención %, duración en s, nº de variantes). NADA de "
    "relleno ni disclaimers. Empezá con el título "
    "'# Playbook de competencia — contenido que funciona (agencias/servicios de IA)' y "
    "una línea con la fecha."
)


def refresh() -> Dict[str, Any]:
    """Re-investiga y reescribe el playbook. Devuelve {ok, chars, queries}."""
    s = get_settings()
    try:
        from packs.automiq.tools.web_search import web_search
    except Exception as e:
        log.warning("competitor_refresh_no_search", error=str(e)[:150])
        return {"ok": False, "reason": "web_search no disponible"}

    blocks: List[str] = []
    for q in _QUERIES + _competitor_queries():
        try:
            for r in (web_search(q, 5) or [])[:5]:
                t = (r.get("title") or "").strip()
                sn = (r.get("snippet") or "").strip()
                if t or sn:
                    blocks.append(f"- {t}: {sn}")
        except Exception as e:
            log.warning("competitor_search_failed", q=q, error=str(e)[:120])
    if len(blocks) < 4:
        log.warning("competitor_refresh_thin", found=len(blocks))
        return {"ok": False, "reason": f"búsqueda devolvió poco ({len(blocks)})"}

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    user = (f"Fecha: {today}. Resultados de búsqueda reales:\n\n" + "\n".join(blocks[:40])
            + "\n\nDestilá el playbook con las secciones pedidas.")
    try:
        from ..clients.minimax import MiniMaxClient
        with MiniMaxClient(s) as mc:
            resp = mc.complete(_DISTILL_SYSTEM, [{"role": "user", "content": user}],
                               max_tokens=2000, temperature=0.4)
        text = (resp.text or "").strip()
    except Exception as e:
        log.warning("competitor_distill_failed", error=str(e)[:150])
        return {"ok": False, "reason": "distill falló"}

    if len(text) < 400 or "Hooks" not in text:
        log.warning("competitor_distill_thin", chars=len(text))
        return {"ok": False, "reason": "destilado pobre"}

    cp.save_playbook(text + f"\n\n_Refrescado automáticamente el {today} desde research en vivo._\n")
    log.info("competitor_refresh_ok", chars=len(text), queries=len(_QUERIES))
    return {"ok": True, "chars": len(text), "queries": len(_QUERIES)}
