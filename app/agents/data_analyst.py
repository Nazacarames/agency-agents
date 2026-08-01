"""
Data Analyst — análisis de métricas (departamento Dirección).

Lee las series de métricas del negocio (snapshots) + finanzas + clientes y saca
TENDENCIAS y ALERTAS: qué sube, qué baja, qué está plano, qué se desvía. Corre
antes del cierre del Chief of Staff para que su brief salga con datos masticados.
Autonomía Dirección = "reversible": analiza y avisa, no acciona afuera.
"""
from .base import BaseAgent, AgentContext
from ._common import get_context_block
from ..log import get_logger

log = get_logger("data_analyst")

DA_INSTRUCTIONS = """
# Data Analyst — Automiq

## Quién sos
Sos el ANALISTA DE DATOS de Automiq. No opinás de contenido ni de ventas: mirás
los NÚMEROS a lo largo del tiempo y sacás conclusiones. Tu salida alimenta al
Chief of Staff y al dueño para decidir.

## Reglas de oro
1. **Tendencia, no foto**: comparás contra períodos anteriores. "Subió/bajó X%
   vs la semana pasada", no "está bien".
2. **Señal sobre ruido**: destacás lo que se MUEVE (crece, cae, se estanca).
   Lo estable no necesita párrafo.
3. **Causa probable + acción**: cada hallazgo relevante lleva una hipótesis de por
   qué y una sugerencia de qué hacer (para el chief/dueño).
4. **Alertas duras**: métrica en cero, caída fuerte, algo que no se movió en
   varios períodos → ARRIBA, con el número.
5. **Honestidad con los datos**: si faltan datos o la muestra es chica, decilo;
   no infles una conclusión.

## Formato de salida
- **Titulares**: 3-5 números que importan esta semana (con su variación).
- **Tendencias**: qué crece / qué cae / qué está plano, con causa probable.
- **Alertas**: lo que necesita atención ya.
- **Para el Chief**: 1-2 cosas que el cierre del día debería mirar.
"""


class DataAnalystAgent(BaseAgent):
    name = "data_analyst"
    description = "Analista: tendencias y alertas de las métricas del negocio"
    schedule = "30 20 * * mon-fri"  # días hábiles 20:30, antes del cierre del Chief (21:00)
    max_tokens = 5000
    llm_provider = "deepseek"       # razonamiento/números; fallback MiniMax

    @property
    def system_prompt(self) -> str:
        from .departments import autonomy_note
        return f"{get_context_block()}\n\n{autonomy_note(self.name)}\n\n{DA_INSTRUCTIONS}"

    def build_user_message(self, ctx: AgentContext) -> str:
        parts = ["Analizá las métricas del negocio con las series de abajo.\n"]
        try:
            from ..integrations import metrics_store as ms
            parts.append(f"## Series de métricas\n{ms.series()}\n")
        except Exception as e:
            log.warning("da_metrics_failed", error=str(e)[:150])
        try:
            from ..integrations import finance_store as fs, clients_store as cs
            parts.append(f"## Finanzas (6m)\n{fs.finance_summary(months=6)}\n")
            parts.append(f"## Clientes\nActivos: {cs.active_count()} · MRR: US$ {cs.mrr_usd():.0f}\n")
        except Exception as e:
            log.warning("da_finance_failed", error=str(e)[:150])
        if len(parts) == 1:
            parts.append("(Sin series de métricas todavía — decilo y listá qué métricas "
                         "habría que empezar a trackear para el próximo análisis.)")
        return "\n".join(parts)
