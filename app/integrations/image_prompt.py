"""
image_prompt — refina el prompt de imagen ANTES de generarla, con el know-how del
subagente `image-prompt-engineer` (que no corre en completion directa / sin Claude Code).

El agente de contenido escribe una idea cruda de imagen; acá un LLM la convierte en un
prompt FOTOGRÁFICO estructurado (sujeto, entorno, luz, cámara/lente, estilo) para Imagen 4,
respetando las reglas de Automiq (escena real de distribuidora argentina, sin texto/UI en
la imagen, aire para el titular, paleta navy como acento). Best-effort: si falla, devuelve
el prompt crudo. Preferentemente GLM (NVIDIA); fallback MiniMax.
"""
from __future__ import annotations

import re

from ..config import get_settings
from ..log import get_logger

log = get_logger("image_prompt")

_SYSTEM = (
    "Sos un Image Prompt Engineer experto en fotografía para generación con IA (Google "
    "Imagen 4). Trabajás para Automiq, una agencia ARGENTINA de automatización con IA para "
    "distribuidoras y PyMEs. Recibís una idea de imagen CRUDA y la reescribís en UN prompt "
    "fotográfico profesional EN INGLÉS, estructurado por capas: sujeto (una persona o escena "
    "CONCRETA y real del rubro argentino), entorno, ILUMINACIÓN con terminología real "
    "(golden hour, soft window light, Rembrandt, f/1.8 shallow depth of field), cámara y "
    "lente (35/50/85mm, ángulo, DOF), estilo (editorial/documentary, film emulation tipo "
    "Kodak Portra 400, color grade) y mood.\n\n"
    "REGLAS DURAS:\n"
    "1. Escena FOTORREALISTA y específica. NADA de abstracciones ('businessman with laptop') "
    "ni clichés de IA (robots, cerebros con circuitos, hologramas, manos tocando pantallas "
    "flotantes, render 3D azul genérico).\n"
    "2. PROHIBIDO texto, letras, números, logos, UI, capturas de chat, dashboards, gráficos o "
    "carteles DENTRO de la imagen (el titular se compone aparte por encima).\n"
    "3. Composición con AIRE / espacio negativo limpio para poder poner un titular encima "
    "(típicamente dejando la zona inferior o un lateral despejado).\n"
    "4. La paleta navy + royal blue de Automiq va como ACENTO dentro de la escena real "
    "(una remera, un detalle, la luz), NO como fondo plano de color.\n"
    "5. Gente argentina real y creíble para el rubro (no modelos de stock genéricos).\n\n"
    "Devolvé SOLO el prompt final en inglés, en UN párrafo, sin comillas, sin títulos, sin "
    "explicaciones ni la palabra 'Prompt:'."
)


def _clean(t: str) -> str:
    t = (t or "").strip()
    # sacar prefijos tipo "Prompt:" / markdown / comillas envolventes
    t = re.sub(r"^\s*(prompt|final prompt|imagen)\s*[:：]\s*", "", t, flags=re.IGNORECASE)
    t = t.strip().strip('"').strip("`").strip()
    # quedarnos con el primer bloque (si devolvió varias líneas de explicación)
    parts = [p.strip() for p in t.split("\n\n") if p.strip()]
    if parts:
        t = parts[0]
    return t.replace("\n", " ").strip()[:1500]


def refine(raw_prompt: str, formato: str = "post") -> str:
    """Devuelve un prompt fotográfico mejorado (o el crudo si el refinamiento falla)."""
    raw = (raw_prompt or "").strip()
    s = get_settings()
    if len(raw) < 8 or not getattr(s, "image_prompt_refine", True):
        return raw_prompt
    user = (f"Idea cruda ({formato}) para una imagen de Automiq:\n{raw}\n\n"
            "Devolvé el prompt fotográfico final en inglés (un párrafo).")

    # 1) GLM vía NVIDIA (mejor redactor, gratis)
    if getattr(s, "nvidia_api_key", ""):
        try:
            from ..clients.nvidia import NvidiaClient
            with NvidiaClient(s) as c:
                r = c.complete(_SYSTEM, [{"role": "user", "content": user}],
                               provider="glm", max_tokens=400, temperature=0.7)
            out = _clean(r.text)
            if len(out) >= 40:
                log.info("image_prompt_refined", provider="glm", chars=len(out))
                return out
        except Exception as e:
            log.warning("refine_glm_failed", error=str(e)[:150])

    # 2) Fallback MiniMax
    try:
        from ..clients.minimax import MiniMaxClient
        with MiniMaxClient(s) as mc:
            r = mc.complete(_SYSTEM, [{"role": "user", "content": user}],
                            max_tokens=400, temperature=0.7)
        out = _clean(r.text)
        if len(out) >= 40:
            log.info("image_prompt_refined", provider="minimax", chars=len(out))
            return out
    except Exception as e:
        log.warning("refine_minimax_failed", error=str(e)[:150])

    return raw_prompt
