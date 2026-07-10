"""
ceo_planner — la "capa CEO" inteligente.

En vez de mandar el MISMO objetivo a todos los agentes (fan-out), el CEO
DESCOMPONE el objetivo en sub-tareas concretas y le asigna a CADA agente
relevante SU parte. Usa el LLM (MiniMax, vía el cliente síncrono) para producir
un plan JSON: [{agent, task, why}]. Best-effort: si el LLM falla o no devuelve
JSON válido, el caller cae al fan-out clásico.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from ..config import get_settings
from ..log import get_logger

log = get_logger("ceo_planner")

_SYSTEM = (
    "Sos el CEO de Automiq, una agencia de automatización con IA para PyMEs "
    "hispanohablantes. Coordinás a un equipo de agentes especializados. Tu trabajo "
    "es DESCOMPONER un objetivo en sub-tareas CONCRETAS y accionables, y asignarle "
    "a cada agente relevante SU parte específica (no la misma tarea a todos).\n\n"
    "Reglas:\n"
    "- Elegí SOLO agentes del roster que recibís. No inventes nombres.\n"
    "- Asigná a un agente sólo si su rol aporta de verdad al objetivo. Mejor 3 "
    "sub-tareas filosas que 8 genéricas.\n"
    "- Cada sub-tarea es una instrucción directa, específica y medible para ese "
    "agente (qué entregar, para qué, con qué foco). Nada de 'ayudá con el objetivo'.\n"
    "- Pensá el orden lógico (quién produce insumos para quién) y reflejalo en el "
    "campo 'order'.\n"
    "- Respondé EXCLUSIVAMENTE con un array JSON, sin texto adicional, con la forma:\n"
    '[{"agent":"<nombre exacto del roster>","task":"<sub-tarea concreta>",'
    '"why":"<por qué este agente>","order":<entero>}]'
)


def _extract_json_array(text: str) -> Optional[list]:
    """Parser robusto único (_common): tolera narración, fences, \\n crudos y
    arrays rotos — el parse frágil de acá devolvía None y el plan caía al
    fan-out genérico en silencio."""
    from ..agents._common import extract_json_array
    items = extract_json_array(text, required_key="agent")
    return items or None


def plan_objective(objective: str, roster: List[Dict[str, str]],
                   client_ctx: str = "", max_steps: int = 8) -> List[Dict[str, Any]]:
    """Devuelve [{agent, task, why, order}] descompuesto. [] si no se pudo."""
    objective = (objective or "").strip()
    if not objective or not roster:
        return []
    names = {a["name"] for a in roster}
    roster_txt = "\n".join(f"- {a['name']}: {a.get('description', '')}" for a in roster)
    user = (
        f"OBJETIVO DEL CEO:\n{objective}\n\n"
        f"ROSTER DE AGENTES DISPONIBLES:\n{roster_txt}\n"
        + (f"\nCONTEXTO DEL CLIENTE OBJETIVO:\n{client_ctx}\n" if client_ctx else "")
        + "\nDescomponé el objetivo en sub-tareas por agente. Devolvé sólo el array JSON."
    )
    try:
        from ..clients.minimax import MiniMaxClient
        with MiniMaxClient(get_settings()) as mm:
            resp = mm.complete(system=_SYSTEM,
                               messages=[{"role": "user", "content": user}],
                               max_tokens=2000, temperature=0.4)
        steps = _extract_json_array(resp.text) or []
    except Exception as e:
        log.warning("ceo_plan_failed", error=str(e)[:200])
        return []

    out: List[Dict[str, Any]] = []
    for s in steps:
        if not isinstance(s, dict):
            continue
        agent = str(s.get("agent", "")).strip()
        task = str(s.get("task", "")).strip()
        if agent in names and len(task) >= 8:
            out.append({"agent": agent, "task": task,
                        "why": str(s.get("why", "")).strip(),
                        "order": s.get("order", len(out) + 1)})
    out.sort(key=lambda x: (x.get("order") or 99))
    # dedup por agente (quedarse con la primera sub-tarea de cada uno)
    seen, deduped = set(), []
    for s in out:
        if s["agent"] in seen:
            continue
        seen.add(s["agent"])
        deduped.append(s)
    return deduped[:max_steps]
