"""
Meeting Prep — copiloto de reuniones de venta de Automiq.

Prepara a fondo una reunion con un cliente/prospecto usando TODA su memoria y
contexto (perfil, reports de auditoria, leads, notas — inyectados por base.py a
partir de args.client_id) + el contexto de la empresa. Entrega un brief
accionable: dolores→solucion, preguntas de discovery, que mostrar (incluido un
agente de WhatsApp de TEST a medida y los productos a mostrar), pricing,
objeciones y cierre.

No tiene schedule: se dispara on-demand (desde la Agenda o como tarea). El output
queda guardado en la memoria del cliente automaticamente (base.py).
"""
from .base import BaseAgent, AgentContext
from ._common import get_context_block, official_site_directive


MEETING_PREP_INSTRUCTIONS = """
# Meeting Prep — Automiq

Sos el copiloto de reuniones de venta de Automiq. Preparas al operador para entrar a una
reunion con un cliente/prospecto y cerrar, usando la memoria real que tenemos de el.

Segui la skill `marketing-reunion`: entregas un brief con (1) resumen de 30s, (2) dolores
y como los resuelve Automiq, (3) preguntas de discovery, (4) que mostrar en la reunion
—incluido un AGENTE DE WHATSAPP DE TEST a medida para ese cliente (con un system prompt
base listo) y los productos del catalogo que encajan—, (5) propuesta y pricing por
vertical, (6) objeciones probables + respuestas, (7) cierre y proximos pasos.

Reglas: espanol argentino, directo y comercial. Apoyate en la memoria del cliente; marca
lo que sea supuesto con "Para confirmar en la reunion". No prometas resultados
garantizados. Si el operador pide algo puntual (armar el agente de test, listar productos,
redactar la propuesta), priorizalo y entregalo completo ademas del brief.
""".strip()


class MeetingPrepAgent(BaseAgent):
    name = "meeting_prep"
    description = "Prepara reuniones con la memoria del cliente: brief, agente de test, demo, objeciones"
    schedule = None  # on-demand (desde la Agenda o como tarea)
    timezone = "America/Buenos_Aires"
    max_tokens = 12000
    use_claude_code = True
    claude_code_skill = "marketing-reunion"
    claude_code_timeout = 700

    @property
    def system_prompt(self) -> str:
        return f"{get_context_block()}\n\n{MEETING_PREP_INSTRUCTIONS}"

    def build_user_message(self, ctx: AgentContext) -> str:
        meeting = ctx.args.get("meeting") if isinstance(ctx.args, dict) else None
        extra = ""
        if isinstance(meeting, dict):
            extra = (
                f"\n\n## Datos de la reunion\n"
                f"- Cliente: {meeting.get('client_name') or '—'}\n"
                f"- Cuando: {meeting.get('scheduled_at') or '—'}\n"
                f"- Modalidad: {meeting.get('location') or '—'}\n"
                f"- Titulo/objetivo: {meeting.get('title') or 'Reunion comercial'}\n"
                f"- Notas: {meeting.get('notes') or '—'}\n"
            )
        return (
            "Prepara la reunion comercial con este cliente. Usa toda su memoria y contexto "
            "(ya te lo paso arriba). Entrega el brief completo segun la skill `marketing-reunion`: "
            "resumen 30s, dolores→solucion, preguntas de discovery, que mostrar (incluido un "
            "AGENTE DE WHATSAPP DE TEST a medida con system prompt base + productos a mostrar), "
            "pricing por vertical, objeciones + respuestas, y cierre con proximos pasos. "
            "Que quede 100% listo para entrar a la reunion."
            + extra
            + official_site_directive()
        )
