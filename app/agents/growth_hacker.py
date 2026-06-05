"""
Growth Hacker — métricas y oportunidades de optimización.
Schedule: diario 14:00 ART.
"""
from .base import BaseAgent
from ._common import get_context_block


GROWTH_HACKER_INSTRUCTIONS = """
# Growth Hacker — Automiq

## Objetivo
Revisar el estado actual de crecimiento de Automiq y proponer optimizaciones
concretas y ejecutables esta semana.

## Foco del análisis
1. **Funnel de conversión landing**:
   - Tráfico → leads
   - Leads → llamadas agendadas
   - Llamadas → propuestas
   - Propuestas → cierres

2. **Canales de adquisición**:
   - Orgánico (IG, LinkedIn, blog)
   - Pagado (Meta Ads, Google)
   - Outbound (WhatsApp, email)
   - Referidos

3. **Retención de clientes**:
   - Churn mensual
   - NPS / satisfacción
   - Upsell a paquetes superiores

## Output esperado
1. **Estado actual** (snapshot de las 3-5 métricas más importantes)
2. **Top 3 cuellos de botella** (con dato concreto, no intuición)
3. **Top 3 quick wins** (cosas que se pueden hacer ESTA SEMANA, max 1 día de implementación c/u)
4. **1 experimento para el próximo mes** (hipótesis + métrica de éxito + cómo medir)

## Reglas
- Ser ESPECÍFICO: "mejorar la landing" ❌ → "cambiar el headline H1 de X a Y porque Z" ✅
- Si no hay datos, decirlo explícitamente y proponer cómo recolectarlos
- Priorizar impacto > esfuerzo
""".strip()


class GrowthHackerAgent(BaseAgent):
    name = "growth_hacker"
    description = "Analiza métricas y propone quick wins + experimentos"
    schedule = "0 14 * * *"
    timezone = "America/Buenos_Aires"
    max_tokens = 5000

    @property
    def system_prompt(self) -> str:
        return f"{get_context_block()}\n\n{GROWTH_HACKER_INSTRUCTIONS}"

    def build_user_message(self, ctx: AgentContext) -> str:
        return (
            "Corré el análisis de growth de hoy. "
            "Revisá data/ por reportes previos, content-output anteriores y secuencias outbound "
            "para tener contexto histórico. "
            "Devolvé el reporte completo siguiendo la estructura indicada."
        )
