"""
Outbound Strategist — secuencias B2B multistep.
Schedule: Lunes 10:00 ART.
"""
from .base import BaseAgent
from ._common import get_context_block


OUTBOUND_INSTRUCTIONS = """
# Outbound Strategist — Automiq

## Objetivo
Diseñar (o mejorar) una secuencia de outreach B2B para prospectos calificados
de Automiq. La secuencia es multi-canal y multi-step.

## Canales disponibles
1. **WhatsApp** (primario en Argentina)
2. **Email** (secundario, solo para follow-up formal)
3. **LinkedIn** (terciario, para casos específicos)

## Estructura de la secuencia
Por cada step entregar:
- **Día** (relativo al día 0 del primer contacto)
- **Canal**
- **Mensaje** completo, listo para enviar (NO placeholders tipo "[nombre]")
- **Por qué este mensaje** (ángulo psicológico)
- **Trigger** (cuándo enviar — manualmente, en respuesta, etc.)
- **Exit condition** (cuándo dejar de seguir a este prospecto)

## Reglas
- Max 5-7 steps en total
- WhatsApp: mensajes cortos (max 300 chars), 1 idea por mensaje
- Email: subject que NO parezca spam, cuerpo de max 150 palabras
- Entre step y step: mínimo 2 días hábiles
- No ser insistente: si no responde en 3 touchpoints, parar
- Personalización: el campo [nombre] es el ÚNICO placeholder permitido
""".strip()


class OutboundAgent(BaseAgent):
    name = "outbound"
    description = "Secuencias B2B multistep (WhatsApp + Email + LinkedIn)"
    schedule = "0 10 * * 1"   # Lunes 10:00 ART
    timezone = "America/Buenos_Aires"
    max_tokens = 6000

    @property
    def system_prompt(self) -> str:
        return f"{get_context_block()}\n\n{OUTBOUND_INSTRUCTIONS}"

    def build_user_message(self, ctx: AgentContext) -> str:
        # Si vienen args (de un webhook), usar el vertical específico
        vertical = ctx.args.get("vertical", "manufacturing")
        return (
            f"Diseñá una secuencia de outbound nueva para prospectos del vertical **{vertical}**. "
            "Revisá data/outbound-sequences/ por secuencias existentes para no duplicar. "
            "Devolvé la secuencia completa, paso por paso, lista para que el SDR la cargue."
        )
