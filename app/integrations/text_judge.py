"""
text_judge — juez de calidad de TEXTO con Gemini (Vertex), el gemelo del QA visual.

El loop creativo ya hace QA de imágenes/shorts con Gemini y reinyecta las lecciones.
Esto lleva el mismo lazo al texto que más plata mueve: los cold-emails de outbound.
Gemini puntúa cada email contra una rúbrica dura y devuelve el ÚNICO fix de mayor
impacto; outbound lo registra como LECCION y lo aplica en la próxima corrida.

Reusa el auth de Vertex de `vision` (service account, SIN key nueva → sin costo extra
más allá de lo que ya pagamos). Best-effort: si Vertex no está o falla, devuelve {}.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List

from ..log import get_logger

log = get_logger("text_judge")


def enabled() -> bool:
    from . import vision
    return vision.enabled()


_EMAIL_RUBRIC = """
Sos un director de ventas B2B argentino, exigente. Puntuás cold-emails con esta rúbrica
(0-100 cada uno; penalizá fuerte lo que huela a plantilla o a bot):
1. Abre con una SEÑAL ESPECÍFICA del prospecto (su negocio/dolor), no con lo que vendemos.
2. Subject ≤45 caracteres, sin MAYÚSCULAS/"!!!"/"gratis"/"oferta", que no sea genérico.
3. UN beneficio medible y creíble (mejor con número).
4. CTA claro y de baja fricción (mirar demo / 15 min / ejemplo por WhatsApp).
5. Suena escrito por una persona 1-a-1, español rioplatense, sin "Estimado señor".

Te paso los emails redactados. Devolvé EXCLUSIVAMENTE un objeto JSON (sin texto ni ```):
{"avg": <promedio 0-100 entero>,
 "top_fix": "<el ÚNICO cambio de mayor impacto para subir la calidad del lote, 1 frase accionable>",
 "items": [{"company": "<empresa>", "score": <0-100>, "issue": "<el problema principal, corto>"}]}
""".strip()


def _parse_obj(text: str) -> Dict[str, Any]:
    """Extrae el primer objeto JSON del texto (Gemini a veces lo envuelve). {} si falla."""
    if not text:
        return {}
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\n?|\n?```$", "", t).strip()
    try:
        return json.loads(t)
    except Exception:
        pass
    m = re.search(r"\{.*\}", t, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            return {}
    return {}


def judge_emails(emails: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Puntúa una lista de emails [{company, subject, body, step}, ...].
    Devuelve {avg, top_fix, items} o {} si el juez no está disponible/falla."""
    if not enabled() or not emails:
        return {}
    from . import vision
    payload = "\n\n".join(
        f"### {e.get('company', '?')} (step {e.get('step', 0)})\n"
        f"Asunto: {e.get('subject', '')}\n{e.get('body', '')}"
        for e in emails[:8]
    )
    raw = vision.synthesize(payload, _EMAIL_RUBRIC, max_tokens=1200)
    obj = _parse_obj(raw)
    if not isinstance(obj, dict) or "avg" not in obj:
        log.warning("text_judge_no_parse", chars=len(raw or ""))
        return {}
    try:
        obj["avg"] = int(obj["avg"])
    except Exception:
        return {}
    log.info("text_judge_done", n=len(emails), avg=obj.get("avg"))
    return obj
