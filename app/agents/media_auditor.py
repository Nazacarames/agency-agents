"""
Media Auditor — audit de cuentas de ads (Meta + Google).
v4 (2026-07-03) — Sin Adspirer como servicio: se quitó el MCP; queda la skill
`ad-campaign-management` como METODOLOGÍA pura (umbrales, workflows de
performance/wasted spend/optimización) además de `marketing-ads`.
- Inyecta las campañas REALES de Meta (Graph API, integración meta_ads) en el
  prompt: el reporte sale con números de verdad; [BENCHMARK] queda como fallback.
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

## Fuentes de datos (en orden de prioridad)
La skill `ad-campaign-management` es tu METODOLOGÍA (umbrales, workflows, qué
mirar) — NO tiene tools conectadas; no intentes llamar tools de ads.
1. **Datos reales de Meta** que vienen en el mensaje (bloque `CAMPAÑAS REALES DE META`):
   usalos tal cual, son de la Graph API de la cuenta.
2. **[BENCHMARK]** — SOLO si no hay datos reales: generá el reporte
   COMPLETO con benchmarks típicos de PyME argentina (presupuesto USD 1k-3k/mes:
   CPL USD 8-20, CTR 1-2%, ROAS 1.5-3, CPM USD 5-12), marcados como `[BENCHMARK]`.
   **NO devuelvas "no puedo"** ni un template vacío.

## Output
Reporte con secciones:
1. **Resumen ejecutivo** (3-5 bullets, lo más importante)
2. **Métricas clave** (tabla: spend, resultados, CPL, ROAS, CTR, CPM — por campaña si hay datos reales)
3. **Top 3 problemas** (con $ estimado perdido/mes y solución concreta)
4. **Top 3 oportunidades** (con $ estimado ganable/mes y plan de acción)
5. **Auditoría de seguridad** (tokens, RBAC, encriptación, Ley 25.326 — upsell Enterprise)
6. **Acciones para esta semana** (checklist priorizado por impacto/esfuerzo)

## Reglas
- Todas las recomendaciones con $$ estimados; acciones ordenadas por impacto/esfuerzo.
- Con datos reales: NADA de inventar métricas que no estén; derivá (ROAS, CPL) solo
  de los números provistos y marcá cualquier estimación.
- Si una campaña real tiene gasto y 0 resultados, eso es el problema nº1 SIEMPRE.
""".strip()


class MediaAuditorAgent(BaseAgent):
    name = "media_auditor"
    description = "Audit semanal de ads (Meta real + metodología ad-campaign-management + fallback [BENCHMARK])"
    schedule = "0 9 * * 1"   # lunes 09:00
    timezone = "America/Buenos_Aires"
    max_tokens = 10000
    use_claude_code = True
    claude_code_skill = "marketing-ads,ad-campaign-management"
    claude_code_timeout = 700

    @property
    def system_prompt(self) -> str:
        return f"{get_context_block()}\n\n{MEDIA_AUDITOR_INSTRUCTIONS}"

    def _meta_block(self) -> str:
        """Campañas reales de Meta (Graph API) para el prompt. '' si no hay conexión."""
        try:
            from ..integrations import meta_ads
            if not meta_ads.enabled():
                return ""
            camps = meta_ads.live_campaigns()
            if not camps:
                return ""
            lines = []
            for c in camps[:25]:
                lines.append(
                    f"- {c['name']} [{c['status']}] objetivo={c['objective'] or 's/d'} · "
                    f"spend USD {c['spend_usd']} · resultados {c['results']} · "
                    f"CPL USD {c['cpl_usd']} · ROAS {c['roas']} · "
                    f"impresiones {c['impressions']} · clics {c['clicks']}"
                )
            return ("\n\n## CAMPAÑAS REALES DE META (Graph API — datos de verdad, usalos)\n"
                    + "\n".join(lines))
        except Exception:
            return ""

    def build_user_message(self, ctx: AgentContext) -> str:
        from datetime import datetime
        import pytz
        tz = pytz.timezone("America/Buenos_Aires")
        now = datetime.now(tz)
        meta = self._meta_block()
        fuentes = []
        if meta:
            fuentes.append("el bloque CAMPAÑAS REALES DE META de abajo")
        if not fuentes:
            fuentes.append("benchmarks [BENCHMARK] de PyME argentina (no hay cuentas conectadas)")
        return (
            f"Generá el audit completo de la semana ({now.strftime('%Y-%m-%d')}). "
            f"Fuente de datos: {'; '.join(fuentes)}. "
            "Entregá: resumen ejecutivo, tabla de métricas, 3 problemas con $ perdido "
            "estimado, 3 oportunidades con $ ganable estimado, auditoría de seguridad, "
            "y checklist priorizado de la semana."
            + meta
        )
