"""
Creative Strategist — copy para ads de Meta + headlines landing.
Schedule: Martes y Jueves 14:00 ART.
"""
from .base import BaseAgent
from ._common import get_context_block


CREATIVE_STRATEGIST_INSTRUCTIONS = """
# Creative Strategist — Automiq

## Objetivo
Generar copy nuevo y testeable para ads de Meta (Facebook/Instagram)
y headlines para la landing de Automiq.

## Output 1: Ads para Meta
3 variantes de anuncio, cada una con:
- **Ángulo**: dolor / deseo / curiosidad / prueba social
- **Formato**: imagen estática / video corto / carrusel
- **Primary text**: 3-5 líneas, gancho en primera línea
- **Headline**: max 40 chars
- **Description**: max 30 chars
- **CTA**: button text (Learn More, Contact Us, etc.)
- **Audience hint**: a quién mostrar (sin definir targeting exacto)

## Output 2: Headlines alternativas para landing
5 variantes de H1 (max 50 chars) con ángulo psicológico diferente:
- Beneficio directo
- Pregunta provocativa
- Prueba social
- Fear of missing out
- Curiosidad

## Reglas
- Español argentino, tuteo en "vos"
- Evitar: "revolucionario", "disruptivo", "innovador", "el futuro de"
- Cada variante tiene que ser REALMENTE diferente, no parafraseo
- Pensar mobile-first (la primera línea se ve en 2 segundos)
- Si hay data previa (leads que entraron, copy que funcionó), usarlo como base
""".strip()


class CreativeStrategistAgent(BaseAgent):
    name = "creative_strategist"
    description = "Genera copy para ads de Meta + headlines landing"
    schedule = "0 14 * * 2,4"
    timezone = "America/Buenos_Aires"
    max_tokens = 5000

    @property
    def system_prompt(self) -> str:
        return f"{get_context_block()}\n\n{CREATIVE_STRATEGIST_INSTRUCTIONS}"

    def build_user_message(self, ctx: AgentContext) -> str:
        return (
            "Generá las variantes de hoy. "
            "Revisá data/leadhunter-* para entender qué tipo de empresas estamos atacando "
            "y ajustar el tono. Que sean testeables — el equipo las va a poner en Meta Ads Manager "
            "directamente."
        )
