"""
Finance Officer — el CFO de Automiq (departamento Finanzas/Admin).

Lee el estado financiero duro (gastos por categoría, suscripciones, MRR de
clientes) y devuelve un brief financiero: en qué se está yendo la plata, MRR vs
gastos, qué facturar/cobrar y las decisiones de plata que el dueño tiene que
tomar. On-demand (sin schedule) para no sumar carga a la cuota diaria.
"""
from datetime import datetime
from zoneinfo import ZoneInfo

from .base import BaseAgent, AgentContext
from ._common import get_context_block
from ..log import get_logger

log = get_logger("finance_officer")

FINANCE_INSTRUCTIONS = """
# Finance Officer (CFO) — Automiq

## Quién sos
Sos el DIRECTOR FINANCIERO de Automiq (una agencia de agentes de IA operada por
una sola persona). Tu trabajo NO es vender ni producir: es cuidar la plata.
Traducís los números crudos en un brief que el dueño usa para decidir.

## Reglas de oro
1. **Números concretos siempre** (montos, moneda, categoría, mes). Nada de "los
   gastos están controlados".
2. **Restricción vigente del negocio: modo orgánico** — no se gasta más que
   hosting + Workspace. Si detectás un gasto nuevo o una suscripción que se puede
   cortar, decilo con el monto.
3. **MRR vs gastos**: comparé el MRR de clientes contra los gastos mensuales
   recurrentes. Decí si el negocio cubre sus costos y por cuánto.
4. **Cobranzas**: si hay clientes/propuestas con plata pendiente (ej: anticipos),
   marcá qué falta facturar o cobrar y a quién.
5. **Acciones del humano** = solo lo que un agente no puede: pagar, cobrar,
   cortar una suscripción, decidir un precio. Cortas y accionables.

## Formato de salida
Un brief en markdown, corto y directo:
- **Estado**: MRR, gastos mensuales, si cubre costos.
- **En qué se va la plata**: top categorías del mes.
- **Alertas**: suscripciones cortables, gastos fuera del modo orgánico.
- **A cobrar / facturar**: pendientes con monto y cliente.
- **Decisiones del dueño (hoy)**: 1-3 acciones concretas.
"""


class FinanceOfficerAgent(BaseAgent):
    name = "finance_officer"
    description = "CFO: brief financiero (gastos, MRR, cobranzas, decisiones de plata)"
    schedule = None            # on-demand (no suma a la cuota diaria)
    max_tokens = 5000
    llm_provider = "deepseek"  # razonamiento/finanzas; fallback MiniMax

    @property
    def system_prompt(self) -> str:
        from .departments import autonomy_note
        return f"{get_context_block()}\n\n{autonomy_note(self.name)}\n\n{FINANCE_INSTRUCTIONS}"

    def build_user_message(self, ctx: AgentContext) -> str:
        month = datetime.now(ZoneInfo(self.timezone)).strftime("%Y-%m")
        parts = ["Armá el brief financiero de Automiq con los números de abajo.\n"]
        try:
            from ..integrations import finance_store as fs
            summ = fs.finance_summary(months=6)
            cats = fs.expenses_by_category(month=month)
            parts.append(f"## Resumen financiero (6m)\n{summ}\n")
            if cats:
                parts.append(f"## Gastos por categoría — {month}\n{cats}\n")
        except Exception as e:
            log.warning("finance_data_failed", error=str(e)[:150])
        try:
            from ..integrations import clients_store as cs
            parts.append(f"## Clientes\nActivos: {cs.active_count()} · "
                         f"MRR: US$ {cs.mrr_usd():.0f}\nPor cliente: {cs.revenue_by_client()}\n")
        except Exception as e:
            log.warning("finance_clients_failed", error=str(e)[:150])
        if len(parts) == 1:
            parts.append("(Sin datos financieros cargados todavía — decilo y sugerí "
                         "cargar gastos/clientes en el panel.)")
        return "\n".join(parts)
