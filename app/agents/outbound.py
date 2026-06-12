"""
Outbound Strategist — secuencias B2B multistep.
Schedule: Lunes 10:00 ART.
"""
from .base import BaseAgent, AgentContext
from ._common import get_context_block, upstream_handoff_block


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
- **PROSPECCIÓN N3** (NUEVO 2026-06-12, de Claudio Conde V1): cada mensaje de la
  secuencia tiene que estar personalizado con datos REALES del prospecto, no con
  placeholders genéricos. Referí un post, un video, una tecnología que usa, un
  dolor específico. Si no podés personalizar, no mandes.
- **BIG DOMINO** (NUEVO 2026-06-12, de Visual Project V2): el mensaje inicial
  tiene que girar alrededor de un beneficio medible (no "te ayudo", sí "recuperá
  60% de la cobranza en 14 días"). Y siempre con CTA concreto (no "decime cuándo",
  sí "martes 10am o jueves 16pm, ¿cuándo te sirve?").
""".strip()


class OutboundAgent(BaseAgent):
    name = "outbound"
    description = "Secuencias B2B multistep (WhatsApp + Email + LinkedIn)"
    schedule = "0 10 * * 1"   # Lunes 10:00 ART
    timezone = "America/Buenos_Aires"
    max_tokens = 6000
    use_claude_code = True
    claude_code_skill = "cold-email"   # email marketing a los leads de leadhunter
    claude_code_timeout = 900

    @property
    def system_prompt(self) -> str:
        return f"{get_context_block()}\n\n{OUTBOUND_INSTRUCTIONS}"

    def build_user_message(self, ctx: AgentContext) -> str:
        vertical = ctx.args.get("vertical", "manufacturing") if isinstance(ctx.args, dict) else "manufacturing"
        # SINERGIA: si web_auditor auditó el sitio de un prospecto y detectó dolores,
        # los traemos como insumo para anclar el cold-email en ese dolor concreto (N3).
        pains = upstream_handoff_block(
            "web_auditor",
            titulo="Dolores detectados por la auditoría web (anclá el opening acá)",
            max_chars=5000,
        )
        return (
            "Tu trabajo es hacer EMAIL MARKETING (cold email) a los leads que generó el "
            "agente leadhunter.\n\n"
            "1. Buscá con Glob/Read el reporte de leads más reciente en `data/` "
            "(`data/leadhunter-report-*.md` o `data/leadhunter-leads-*.json`). Si existe, "
            "tomá los leads reales (empresa, decisor, contacto, rubro, señales) de ahí.\n"
            "2. Si NO hay archivo de leads disponible (disco efímero), generá la secuencia "
            f"para el perfil del vertical **{vertical}** de forma representativa.\n"
            "3. Si abajo viene un bloque de 'Dolores detectados por la auditoría web', usá ESOS "
            "dolores específicos como gancho del opening del cold-email (es personalización N3 real: "
            "el prospecto siente que entendiste su problema). Mapeá cada dolor a la oferta de Automiq "
            "que lo resuelve.\n"
            "4. Por cada lead, escribí una secuencia de cold-email personalizada siguiendo la "
            "skill `cold-email`: subject line, opening personalizado (basado en una señal/dolor real "
            "del lead), cuerpo breve orientado a valor, CTA claro, y 2-3 follow-ups con timing. "
            "Español argentino, tono humano (no plantilla). Personalizá con datos reales del lead.\n\n"
            "Devolvé, por lead: empresa + la secuencia completa lista para enviar."
            f"{pains}"
        )
