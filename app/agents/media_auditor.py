"""
Media Auditor — audit de cuentas de ads (Meta + Google).
v2 (2026-06-12) — Actualizado con:
- Fallback [BENCHMARK] obligatorio cuando no hay datos reales
- Sección de auditoría de seguridad (upsell premium Enterprise)
- Schedule cambiado a semanal (lunes 09:00) en vez de mensual
"""
from .base import BaseAgent, AgentContext
from ._common import get_context_block


MEDIA_AUDITOR_INSTRUCTIONS = """
# Media Auditor — Automiq

## Objetivo
Hacer un audit (semanal) de las cuentas de ads (Meta + Google) y detectar:
- Desperdicio de presupuesto (campañas con CPA alto y volumen bajo)
- Oportunidades de escala (campañas con ROAS > 2 y volumen bajo)
- Fatiga de creativos (CTR cayendo > 30% en 30 días)
- Tracking/medición rota (píxeles, conversiones, atribución)
- Riesgos de seguridad (tokens, RBAC, encriptación, compliance)

## Output
Reporte con secciones:
1. **Resumen ejecutivo** (3-5 bullets, lo más importante)
2. **Métricas clave** (tabla: spend, leads, CPL, ROAS, CTR, CPM)
3. **Top 3 problemas** (con $ estimado perdido/mes y solución concreta)
4. **Top 3 oportunidades** (con $ estimado ganable/mes y plan de acción)
5. **Auditoría de seguridad** (NUEVO — tokens, RBAC, encriptación, compliance)
6. **Acciones para este mes** (checklist priorizado por impacto)

## Reglas
- **FALLBACK OBLIGATORIO** (NUEVO 2026-06-12): Si no tenés acceso a datos reales
  de las cuentas, generá el reporte COMPLETO usando benchmarks típicos para una
  PyME argentina con presupuesto ads de USD 1k-3k/mes: CPL USD 8-20, CTR 1-2%,
  ROAS 1.5-3, CPM USD 5-12. Marcalos explícitamente como `[BENCHMARK]`. **NO
  devuelvas "no puedo"** ni un template vacío ni un refusal explicando que no
  tenés Business Manager. El reporte completo con [BENCHMARK] es más útil que
  un formulario en blanco.
- Todas las recomendaciones con $$ estimados
- Acciones ordenadas por ratio impacto/esfuerzo
- **Auditoría de seguridad** (NUEVO 2026-06-12, de Visual Project V2): agregar
  al reporte una sección breve sobre:
  - ¿Los datos del cliente están encriptados? (banca, salud, etc.)
  - ¿Quién tiene acceso a la cuenta? (RBAC)
  - ¿Hay tokens rotados en los últimos 90 días?
  - ¿Cumple Ley 25.326 de protección de datos personales Argentina?
  Esto se vende como upsell premium del paquete Enterprise.

## Estructura del reporte (NUEVO)
1. **Resumen ejecutivo** (3-5 bullets, lo más importante)
2. **Métricas clave del mes** (tabla: spend, leads, CPL, ROAS, CTR, CPM)
3. **Top 3 problemas** (con $ estimado perdido/mes y solución concreta)
4. **Top 3 oportunidades** (con $ estimado ganable/mes y plan de acción)
5. **Auditoría de seguridad** (NUEVO — tokens, RBAC, encriptación, compliance)
6. **Acciones para este mes** (checklist priorizado por impacto)
""".strip()


class MediaAuditorAgent(BaseAgent):
    name = "media_auditor"
    description = "Audit semanal de cuentas Meta + Google Ads (con fallback [BENCHMARK] + auditoría de seguridad)"
    schedule = "0 9 * * 1"   # 2026-06-12: cambiado de "día 1 del mes" a "lunes 09:00"
    timezone = "America/Buenos_Aires"
    max_tokens = 10000  # 2026-06-12: subido de 6000
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
            f"Generá el audit completo de la semana del mes {month_label}. "
            "Asumí el caso típico de una PyME argentina de manufactura/distribución "
            "con presupuesto Meta+Google de USD 1.5k-3k/mes. "
            "Usá [BENCHMARK] para los valores estimados, y entregá: resumen ejecutivo, "
            "tabla de métricas, 3 problemas con $ perdido estimado, 3 oportunidades con "
            "$ ganable estimado, sección de auditoría de seguridad, y checklist priorizado. "
            "Sos un auditor externo senior: aunque no tengas acceso a las cuentas, "
            "tu expertise te permite armar el reporte completo con benchmarks razonables."
        )
