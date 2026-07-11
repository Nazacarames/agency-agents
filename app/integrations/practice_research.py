"""
practice_research — aprendizaje constante DESDE INTERNET (pedido del usuario
2026-07-11: "busca estrategias en internet que puedan ayudarnos, mejora
constante y aprendizaje constante del sistema").

Job mensual: busca en la web las mejores prácticas vigentes de los frentes que
mueven el negocio (cold email, WhatsApp B2B LATAM, contenido corto), un LLM
(DeepSeek) destila los hallazgos en lecciones CONCRETAS con números, y esas
lecciones entran al loop de aprendizaje (memory_store.record_outcome → se
inyectan al agente correspondiente en cada corrida, con refuerzo de peso).

Usa el mismo web_search resiliente del pack (Serper/Brave/Tavily). Best-effort:
sin resultados de búsqueda o sin LLM, no escribe nada.
"""
from __future__ import annotations

from typing import Dict, List

from ..config import get_settings
from ..log import get_logger

log = get_logger("practice_research")

# frente → (queries de búsqueda, agentes que aprenden las lecciones)
_FRONTS: Dict[str, Dict] = {
    "cold_email": {
        "queries": ["cold email B2B reply rate benchmarks what works",
                    "cold email personalization video demo meetings booked data"],
        "agents": ["outbound", "growth_hacker"],
    },
    "whatsapp_b2b": {
        "queries": ["WhatsApp B2B outreach pymes latinoamerica mejores practicas conversion"],
        "agents": ["outbound", "inbox_assistant"],
    },
    "short_video": {
        "queries": ["short form video hooks retention best practices data"],
        "agents": ["tiktok_creator", "content_creator"],
    },
}

_SYSTEM = (
    "Sos un analista de growth. Te paso resultados de búsqueda web (títulos + snippets) "
    "sobre un frente de marketing. Destilá SOLO lo accionable y respaldado por datos en "
    "1 a 3 lecciones para un equipo de agentes de IA de una agencia argentina.\n"
    "Reglas: cada lección UNA frase autosuficiente, con el número/benchmark si lo hay, "
    "en español rioplatense, sin fuentes ni URLs. Nada genérico ('personalizá más'): "
    "solo lo específico. Respondé EXCLUSIVAMENTE una línea por lección con el formato:\n"
    "LECCION: <texto>"
)


def refresh() -> Dict:
    """Corre la investigación de todos los frentes. Devuelve {front: n_lecciones}."""
    import re
    from packs.automiq.tools.web_search import web_search
    from ..clients.nvidia import complete_with_provider
    from . import memory_store as ms

    s = get_settings()
    out: Dict[str, int] = {}
    for front, cfg in _FRONTS.items():
        results: List[str] = []
        for q in cfg["queries"]:
            try:
                for r in web_search(q, n=6):
                    results.append(f"- {r.get('title', '')}: {r.get('snippet', '')}")
            except Exception as e:
                log.warning("practice_search_failed", front=front, error=str(e)[:120])
        if not results:
            out[front] = 0
            continue
        user = (f"FRENTE: {front}\n\nRESULTADOS DE BÚSQUEDA (hoy):\n"
                + "\n".join(results[:18])
                + "\n\nDestilá las lecciones (máx 3, formato LECCION: ...).")
        try:
            resp = complete_with_provider("deepseek", s, _SYSTEM, user, 800, 0.3)
            text = resp.text or ""
        except Exception as e:
            log.warning("practice_llm_failed", front=front, error=str(e)[:150])
            out[front] = 0
            continue
        n = 0
        for m in re.finditer(r"^[\s>*`\-]*LECCI[OÓ]N\s*[:：]\s*(.+)$", text,
                             re.IGNORECASE | re.MULTILINE):
            lesson = m.group(1).strip().strip("`*")
            if 20 <= len(lesson) <= 300 and n < 3:
                for agent in cfg["agents"]:
                    ms.record_outcome(agent, lesson)
                n += 1
        out[front] = n
        log.info("practice_front_done", front=front, lessons=n)
    log.info("practice_research_done", **out)
    return out
