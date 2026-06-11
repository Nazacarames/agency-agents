"""
Media Auditor — audit de cuentas de ads (Meta + Google).
Schedule: día 1 de cada mes a las 11:00 ART.
"""
from .base import BaseAgent, AgentContext
from ._common import get_context_block


MEDIA_AUDITOR_INSTRUCTIONS = """
# Media Auditor — Automiq

## Objetivo
Hacer un audit mensual de las cuentas de ads (Meta + Google) y detectar:
- Desperdicio de presupuesto (campañas con CPA alto y volumen bajo)
- Oportunidades de escala (campañas con ROAS > 2 y volumen bajo)
- Fatiga de creativos (CTR cayendo > 30% en 30 días)
- Tracking/medición rota (píxeles, conversiones, atribución)

## Output
Reporte con secciones:
1. **Resumen ejecutivo** (3-5 bullets, lo más importante)
2. **Métricas clave del mes** (tabla: spend, leads, CPL, ROAS, CTR, CPM)
3. **Top 3 problemas** (con $ estimado perdido/mes y solución concreta)
4. **Top 3 oportunidades** (con $ estimado ganable/mes y plan de acción)
5. **Acciones para este mes** (checklist priorizado por impacto)

## Reglas
- Si no tenés acceso a datos reales de las cuentas, generá el reporte completo usando
  benchmarks típicos para una PyME argentina con presupuesto ads de USD 1k-3k/mes:
  CPL USD 8-20, CTR 1-2%, ROAS 1.5-3, CPM USD 5-12. Marcalos como `[BENCHMARK]`.
  **NO devuelvas "no puedo" ni un template vacío** — el reporte completo con [BENCHMARK]
  es más útil que un formulario en blanco.
- Todas las recomendaciones con $$ estimados
- Acciones ordenadas por ratio impacto/esfuerzo
""".strip()


class MediaAuditorAgent(BaseAgent):
    name = "media_auditor"
    description = "Audit mensual de cuentas Meta + Google Ads"
    schedule = "0 11 1 * *"   # Día 1 de cada mes, 11:00 ART
    timezone = "America/Buenos_Aires"
    max_tokens = 6000
    use_claude_code = True
    claude_code_skill = "marketing-ads"
    claude_code_timeout = 700

    @property
    def system_prompt(self) -> str:
        return f"{get_context_block()}\n\n{MEDIA_AUDITOR_INSTRUCTIONS}"

    def build_user_message(self, ctx: AgentContext) -> str:
        from datetime import datetime
        import pytz
        tz = pytz.timezone("America/Buenos_Aires")
        now = datetime.now(tz)
        month_label = now.strftime("%Y-%m")
        return (
            f"Generá el audit del mes {month_label}. "
            "Si no hay datos de campañas específicas en data/, devolvé un template "
            "con los KPIs a chequear y los criterios de evaluación. "
            "Sos un auditor externo con experiencia, no tenés acceso a las cuentas por defecto."
        )
