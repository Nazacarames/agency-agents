"""
Customer Success — postventa/retención (departamento Customer Success).

Lee la cartera de clientes activos + su memoria y devuelve, por cliente, el plan
de seguimiento: onboarding pendiente, riesgos de churn, próximos toques y qué
hacer para que renueven/queden contentos. On-demand (sin schedule).
"""
from .base import BaseAgent, AgentContext
from ._common import get_context_block
from ..log import get_logger

log = get_logger("customer_success")

CS_INSTRUCTIONS = """
# Customer Success — Automiq

## Quién sos
Sos el responsable de POSTVENTA y RETENCIÓN de Automiq. Una vez que un lead se
convierte en cliente, es tuyo: que arranque bien (onboarding), que siga contento
y que renueve. Tu trabajo NO es conseguir clientes nuevos (eso es Comercial): es
cuidar a los que ya están.

## Reglas de oro
1. **Por cliente, no genérico**: cada cliente activo tiene su plan. Usá su
   memoria (lo que ya se hizo, lo que pidió, lo que pagó).
2. **Riesgo de churn**: marcá señales (no responde, no usa la plataforma, se
   quejó, vence el pago). Un cliente en riesgo va PRIMERO.
3. **Onboarding**: si un cliente arrancó hace poco, listá los pasos que faltan
   para que llegue a su primer valor.
4. **Próximo toque concreto**: fecha + canal + qué decirle. No "hacer seguimiento".
5. **Acciones del humano** = solo lo que un agente no puede (una llamada, una
   decisión, entregar algo). El resto, misión sugerida.

## Formato de salida
Un brief en markdown:
- **Cartera**: cuántos clientes activos, MRR.
- **Por cliente**: estado (contento/en riesgo/onboarding), último contacto,
  próximo toque (fecha + qué), riesgos.
- **Prioridad de la semana**: el cliente que más atención necesita y por qué.
- **Acciones del dueño (hoy)**: 1-3 concretas.
"""


class CustomerSuccessAgent(BaseAgent):
    name = "customer_success"
    description = "Postventa/retención: plan de seguimiento por cliente, riesgos de churn"
    schedule = None
    max_tokens = 5000
    llm_provider = "deepseek"

    @property
    def system_prompt(self) -> str:
        return f"{get_context_block()}\n\n{CS_INSTRUCTIONS}"

    def build_user_message(self, ctx: AgentContext) -> str:
        parts = ["Armá el brief de Customer Success con la cartera de abajo.\n"]
        try:
            from ..integrations import clients_store as cs, client_memory_store as cms
            clients = [c for c in cs.list_clients() if not cs.is_frozen(c.get("id", ""))]
            parts.append(f"## Cartera\nActivos: {cs.active_count()} · MRR: US$ {cs.mrr_usd():.0f}\n")
            for c in clients[:15]:
                cid = c.get("id", "")
                dig = cms.context_digest(cid, max_items=8, max_chars=1500) if cid else ""
                parts.append(f"### {c.get('name', cid)}\nEstado: {c.get('status', '?')} · "
                             f"MRR: {c.get('mrr', '?')}\nMemoria:\n{dig or '(sin notas)'}\n")
        except Exception as e:
            log.warning("cs_data_failed", error=str(e)[:150])
        if len(parts) == 1:
            parts.append("(Sin clientes activos cargados todavía — decilo y sugerí "
                         "cargar la cartera en el panel. Podés usar el pipeline de "
                         "propuestas abiertas como proto-cartera si aplica.)")
        return "\n".join(parts)
