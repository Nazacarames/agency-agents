"""
Creative Strategist — copy para ads de Meta + headlines landing.
Schedule: Martes y Jueves 14:00 ART.
"""
from .base import BaseAgent, AgentContext
from ._common import get_context_block, upstream_handoff_block


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
- **BIG DOMINO** (NUEVO 2026-06-12, de Visual Project V2): cada copy tiene que
  girar alrededor del Big Domino de Automiq. El "primary text" arranca con el
  problema del cliente, después el resultado, después el vehículo. NO al revés.
- **Vertical prioritario** (NUEVO 2026-06-12): las variantes tienen que apuntar
  al vertical distribución, no a "PyMEs en general". El "audience hint" tiene
  que ser específico (ej: "dueños de distribuidoras en CABA/GBA, 25-100 empleados").
- **Empresa → Oferta → Tecnología** (NUEVO 2026-06-12): la copy no arranca
  mencionando "agente de IA" o "WhatsApp" — eso viene al final. Arranca por
  el dolor (ej: "Dejás de perder 30% de tu cartera por mora").
""".strip()


class CreativeStrategistAgent(BaseAgent):
    name = "creative_strategist"
    description = "Genera copy para ads de Meta + headlines landing"
    schedule = "0 14 * * 2,4"
    timezone = "America/Buenos_Aires"
    max_tokens = 5000
    use_claude_code = True
    claude_code_skill = "marketing-ads"
    claude_code_timeout = 700

    @property
    def system_prompt(self) -> str:
        return f"{get_context_block()}\n\n{CREATIVE_STRATEGIST_INSTRUCTIONS}"

    def build_user_message(self, ctx: AgentContext) -> str:
        # SINERGIA: los dolores reales que detectó web_auditor son el mejor
        # insumo para el "primary text" de los ads (ángulo dolor, N3).
        pains = upstream_handoff_block(
            "web_auditor",
            titulo="Dolores reales detectados por la auditoría web (usalos como ángulo de los ads)",
            max_chars=4000,
        )
        return (
            "Generá las variantes de hoy. "
            "Revisá data/leadhunter-* para entender qué tipo de empresas estamos atacando "
            "y ajustar el tono. Si abajo viene un bloque de 'Dolores reales detectados', usá "
            "esos dolores como ángulo del 'primary text' (arrancá por el problema concreto). "
            "Que sean testeables — el equipo las va a poner en Meta Ads Manager directamente."
            f"{pains}"
        )
