"""
linkedin_leads — LinkedIn para el pipeline de ventas, SIN violar los ToS:

1. ENRIQUECIMIENTO: busca el perfil público del decisor de cada lead vía buscadores
   (`site:linkedin.com/in ...` con web_search/Tavily — perfiles públicos indexados,
   sin scraping de LinkedIn ni login).
2. OUTBOUND ASISTIDO: por cada lead con perfil, genera la nota de invitación (≤280
   chars, LinkedIn corta en 300) y el guion del primer DM (Gemini). El CLIC final lo
   da el humano desde el panel ("LinkedIn del día") → cero riesgo de ban.

Estados del lead (li_state): pending → invited → connected → replied (o skipped).
Best-effort en todo: si no hay búsqueda/Gemini, no rompe nada.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ..log import get_logger

log = get_logger("linkedin_leads")

_NOTE_DM_PROMPT = (
    "Sos SDR de Automiq (agencia argentina de IA: bots de WhatsApp que atienden, cotizan y "
    "cobran solos para PyMEs). Abajo van los datos de un lead. Escribí:\n"
    "NOTA: <nota de invitación de LinkedIn, máx 280 caracteres, español rioplatense, "
    "personalizada con su negocio/rubro, humana, sin humo ni 'espero que estés bien', "
    "termina con micro-CTA suave>\n"
    "DM: <primer mensaje para cuando acepte, 3-4 líneas, un dolor concreto de su rubro + "
    "cómo lo resolvemos + CTA de demo de 15 minutos>\n"
    "Nada más que esas 2 líneas (NOTA: y DM:). DATOS DEL LEAD:\n"
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _norm(s: str) -> str:
    """Minúsculas y sin acentos, para comparar nombres de empresa."""
    return "".join(c for c in unicodedata.normalize("NFD", (s or "").lower())
                   if unicodedata.category(c) != "Mn")


# Palabras que NO identifican a una empresa (aparecen en miles). Si de un nombre
# sólo quedan éstas, no hay con qué verificar el match y no arriesgamos.
_GENERIC = {
    "grupo", "distribuidora", "distribuciones", "distribucion", "comercial",
    "industrias", "industria", "manufacturas", "productos", "servicios", "empresa",
    "sociedad", "hermanos", "hnos", "srl", "sas", "cia", "compania", "argentina",
    "inmobiliaria", "propiedades", "transporte", "logistica", "mayorista", "del",
    "las", "los", "para",
    # rubros: describen a qué se dedica, no cuál empresa es
    "metalurgica", "metalurgia", "metalmecanica", "quimica", "quimicos", "plasticos",
    "alimentos", "alimenticia", "textil", "automotores", "repuestos", "ferreteria",
    "construcciones", "construccion", "ingenieria", "tecnologia", "sistemas",
    "soluciones", "insumos", "materiales", "equipos", "maquinarias", "envases",
}


def _company_tokens(company: str) -> List[str]:
    """Tokens que de verdad identifican a la empresa (su marca), sin genéricos."""
    raw = re.split(r"[^a-z0-9]+", _norm(company))
    return [t for t in raw if len(t) >= 3 and t not in _GENERIC]


def find_profile(company: str, decisor: str = "") -> Dict[str, str]:
    """Busca el perfil público de LinkedIn del decisor. {} si no hay match confiable.

    El buscador devuelve CUALQUIER perfil parecido, así que hay que verificarlo:
    sin esto "Distlook Tucumán" matcheaba con el socio gerente de "Tucumán Kiosco",
    y le habríamos mandado una invitación personalizada al tipo equivocado firmada
    con el nombre real del dueño. Exigimos que la marca aparezca en el resultado,
    o que coincida el nombre del decisor.
    """
    try:
        from packs.automiq.tools.web_search import web_search
    except Exception:
        return {}
    tokens = _company_tokens(company)
    if not tokens and not decisor:
        return {}  # sin nada verificable, no adivinamos
    queries = []
    if decisor and company:
        queries.append(f'site:linkedin.com/in "{decisor}" {company}')
    if company:
        queries.append(f'site:linkedin.com/in {company} dueño OR fundador OR gerente OR socio')
    for q in queries:
        try:
            for r in (web_search(q, 5) or []):
                url = (r.get("url") or "").split("?")[0]
                if "linkedin.com/in/" not in url:
                    continue
                title = (r.get("title") or "").replace("| LinkedIn", "").strip()
                # La marca tiene que estar en el TITULAR del perfil ("Gerente en X"),
                # no en el snippet: el snippet trae texto suelto de la página y hacía
                # pasar cualquier cosa. Preferimos perder leads antes que mandarle una
                # invitación personalizada al tipo equivocado con el nombre del dueño.
                ok = bool(tokens) and tokens[0] in _norm(title)
                # ...o si buscábamos por nombre y el nombre coincide.
                if not ok and decisor:
                    ok = _norm(decisor.split()[0]) in _norm(title)
                if not ok:
                    continue
                return {"url": url, "title": title[:120]}
        except Exception as e:
            log.warning("li_search_failed", q=q[:60], error=str(e)[:100])
    return {}


def craft_messages(lead: Dict[str, Any]) -> Dict[str, str]:
    """Nota de invitación + guion de DM personalizados (Gemini). Fallback a plantilla."""
    datos = (f"Empresa: {lead.get('company','')} · Rubro: {lead.get('industria','')} · "
             f"Decisor: {lead.get('decisor','')} · Web: {lead.get('web','')} · "
             f"Headline LinkedIn: {lead.get('li_headline','')}")
    try:
        from . import vision
        if vision.enabled():
            out = vision.synthesize(datos, _NOTE_DM_PROMPT, max_tokens=800) or ""
            note = dm = ""
            for line in out.splitlines():
                ls = line.strip()
                if ls.upper().startswith("NOTA:"):
                    note = ls[5:].strip()
                elif ls.upper().startswith("DM:"):
                    dm = ls[3:].strip()
            if note:
                return {"note": note[:280], "dm": dm[:900]}
    except Exception as e:
        log.warning("li_craft_failed", error=str(e)[:120])
    rubro = lead.get("industria") or "tu rubro"
    return {"note": (f"Hola! Trabajo con PyMEs de {rubro} automatizando la atención por "
                     f"WhatsApp con IA (cotizan y cobran solas). Vi {lead.get('company','tu empresa')} "
                     f"y me gustaría conectar.")[:280],
            "dm": (f"¡Gracias por conectar! Te cuento en una línea: armamos bots de WhatsApp "
                   f"con IA para negocios como {lead.get('company','el tuyo')} — atienden, "
                   f"cotizan y hacen seguimiento solos, 24/7. ¿Te muestro una demo de 15 "
                   f"minutos con un caso de {rubro}?")}


def enrich(limit: int = 10) -> Dict[str, int]:
    """Enriquece leads SIN perfil de LinkedIn (los más nuevos primero): busca el perfil
    y genera nota+DM. Corre tras el ingest de outbound y a demanda desde el panel."""
    from . import leads_store as ls
    # Si el buscador no está disponible (cuota agotada, sin key, DDG bloqueado),
    # web_search devuelve [] igual que si no hubiera resultados — y marcar
    # not_found es PERMANENTE: el lead queda excluido de futuros intentos. Antes
    # de concluir nada, comprobamos que el buscador realmente responda.
    try:
        from packs.automiq.tools.web_search import web_search as _ws
        if not _ws("site:linkedin.com/in gerente", 1):
            log.warning("li_enrich_sin_buscador")
            return {"revisados": 0, "con_perfil": 0, "sin_perfil": 0,
                    "error": "buscador sin respuesta (¿cuota agotada?) — no se marcó nada"}
    except Exception as e:
        log.warning("li_enrich_sin_buscador", error=str(e)[:120])
        return {"revisados": 0, "con_perfil": 0, "sin_perfil": 0, "error": "buscador no disponible"}
    store = ls.load_store()
    candidates = [l for l in store.get("leads", {}).values()
                  if not l.get("linkedin") and l.get("li_state") != "not_found"
                  and l.get("state") not in ("descartado", "cliente")]
    candidates.sort(key=lambda l: l.get("first_seen") or "", reverse=True)
    found = not_found = 0
    for lead in candidates[:max(1, limit)]:
        prof = find_profile(lead.get("company", ""), lead.get("decisor", ""))
        if not prof:
            ls.update_lead(lead["key"], {"li_state": "not_found"})
            not_found += 1
            continue
        lead["li_headline"] = prof.get("title", "")
        msgs = craft_messages(lead)
        ls.update_lead(lead["key"], {
            "linkedin": prof["url"], "li_headline": prof.get("title", ""),
            "li_note": msgs["note"], "li_dm": msgs["dm"],
            "li_state": "pending", "li_at": _now(),
        })
        found += 1
        log.info("li_enriched", company=lead.get("company", "")[:40], url=prof["url"][:80])
    return {"revisados": min(len(candidates), limit), "con_perfil": found,
            "sin_perfil": not_found}


def today_list(limit: int = 12) -> List[Dict[str, Any]]:
    """La lista 'LinkedIn del día': invitaciones pendientes + conexiones a las que
    mandarles el DM. Todo listo para copiar y pegar."""
    from . import leads_store as ls
    store = ls.load_store()
    rows = [l for l in store.get("leads", {}).values()
            if l.get("linkedin") and l.get("li_state") in ("pending", "invited", "connected")]
    order = {"connected": 0, "pending": 1, "invited": 2}
    rows.sort(key=lambda l: (order.get(l.get("li_state"), 3), l.get("li_at") or ""))
    return [{"key": l["key"], "company": l.get("company"), "decisor": l.get("decisor"),
             "industria": l.get("industria"), "linkedin": l.get("linkedin"),
             "headline": l.get("li_headline"), "note": l.get("li_note"),
             "dm": l.get("li_dm"), "li_state": l.get("li_state")}
            for l in rows[:limit]]


def mark(key: str, state: str) -> bool:
    """Marca el avance manual: invited / connected / replied / skipped."""
    if state not in ("pending", "invited", "connected", "replied", "skipped"):
        return False
    from . import leads_store as ls
    return ls.update_lead(key, {"li_state": state, "li_at": _now()}) is not None


def counts() -> Dict[str, int]:
    from . import leads_store as ls
    store = ls.load_store()
    out: Dict[str, int] = {}
    for l in store.get("leads", {}).values():
        st = l.get("li_state")
        if st:
            out[st] = out.get(st, 0) + 1
    return out
