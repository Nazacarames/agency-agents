"""
learning — consolida lo aprendido por la agencia desde RESULTADOS REALES y lo
escribe como lecciones que se inyectan en los prompts de los agentes (memory_store).

Es el "aprendizaje con el tiempo": además de las lecciones puntuales que dispara
cada respuesta/venta, este digest mira el AGREGADO del pipeline (qué rubros
responden vs cuáles son tierra muerta) y refuerza/crea lecciones data-driven para
el leadhunter y outbound. Corre semanal (scheduler) y es determinístico (sin LLM,
sin costo de cuota). record_outcome deduplica y REFUERZA el peso al repetirse, así
las señales sostenidas en el tiempo suben de prioridad solas.
"""
from __future__ import annotations

from typing import Any, Dict

from ..log import get_logger

log = get_logger("learning")

MIN_CONTACTED = 3      # evidencia mínima para sacar conclusión de un rubro
GOOD_REPLY_RATE = 0.25  # >=25% respuestas = rubro caliente
DEAD_CONTACTED = 4      # contactados sin ninguna respuesta = rubro a despriorizar


def digest() -> Dict[str, Any]:
    """Lee el pipeline, agrega por rubro y escribe lecciones de outcome. Best-effort."""
    from . import leads_store as ls
    from . import memory_store as ms

    store = ls.load_store()
    agg = ls.outcomes_by_industry(store)
    written = {"hot": [], "dead": [], "total_industries": len(agg)}

    ranked = []
    for ind, a in agg.items():
        if ind == "(sin rubro)":
            continue
        contacted = a["contacted"]
        if contacted < MIN_CONTACTED:
            continue
        rate = a["replied"] / contacted if contacted else 0
        ranked.append((ind, a, rate))

    # Rubros CALIENTES → priorizar (peso escala con la evidencia).
    for ind, a, rate in sorted(ranked, key=lambda x: x[2], reverse=True):
        if rate >= GOOD_REPLY_RATE and a["replied"] >= 1:
            w = min(5, 2 + a["replied"] // 2)
            pct = round(rate * 100)
            lesson = (f"Por datos del pipeline: las PyMEs de '{ind}' responden "
                      f"{pct}% ({a['replied']}/{a['contacted']}). Es un rubro caliente — "
                      f"priorizá traer MÁS empresas de ese perfil.")
            ms.record_outcome("leadhunter", lesson, weight=w)
            ms.record_outcome("outbound", lesson, weight=2)
            written["hot"].append({"industria": ind, "reply_rate": pct, "n": a["contacted"]})

    # Rubros TIERRA MUERTA → despriorizar (mucho contacto, cero respuesta).
    for ind, a, rate in ranked:
        if a["replied"] == 0 and a["contacted"] >= DEAD_CONTACTED:
            lesson = (f"Por datos del pipeline: '{ind}' NO respondió en {a['contacted']} "
                      f"intentos. Bajá su prioridad (o cambiá el ángulo) y enfocate en "
                      f"rubros que sí convierten.")
            ms.record_outcome("leadhunter", lesson, weight=2)
            written["dead"].append({"industria": ind, "n": a["contacted"]})

    log.info("learning_digest_done",
             hot=len(written["hot"]), dead=len(written["dead"]),
             industries=written["total_industries"])
    return written
