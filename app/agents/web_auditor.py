"""
Web Auditor — auditoría/revisión de páginas web (marketing + CRO + SEO + contenido).
Corre vía Claude Code con la skill `marketing-auditoria`: descarga la página con
WebFetch, clasifica el negocio, lanza subagentes de análisis y produce un informe
puntuado y accionable.

Schedule: lunes 12:00 ART. Default audita la landing de Automiq; se le puede pasar
`args.url` para auditar cualquier página (propia o de un prospecto/cliente).
"""
from .base import BaseAgent, AgentContext
from ._common import get_context_block


WEB_AUDITOR_INSTRUCTIONS = """
# Web Auditor — Automiq

## Objetivo
Auditar páginas web (la propia de Automiq, o las de prospectos/clientes) y producir
un informe de marketing puntuado, priorizado y accionable, enfocado en revenue:
- Contenido y mensaje (claridad, value proposition, prueba social)
- Conversión / CRO (funnels, landings, CTAs, formularios)
- SEO on-page (títulos, headings, meta, estructura)
- Señales de confianza (casos, testimonios, seguridad)
- Captación (lead magnets, email, next steps)

## Reglas
- Español argentino.
- Cada área puntuada 0-100, con quick wins priorizados por impacto/esfuerzo.
- Recomendaciones concretas y accionables esta semana, no genéricas.
- Si no podés acceder a la página, reportalo claramente en vez de inventar.
""".strip()


class WebAuditorAgent(BaseAgent):
    name = "web_auditor"
    description = "Auditoría de páginas web (contenido/CRO/SEO) con informe puntuado"
    schedule = "0 12 * * 1"  # lunes 12:00 ART
    timezone = "America/Buenos_Aires"
    max_tokens = 8000
    use_claude_code = True
    claude_code_skill = "marketing-auditoria"
    claude_code_timeout = 1200  # 5 subagentes en paralelo + WebFetch de varias páginas

    @property
    def system_prompt(self) -> str:
        return f"{get_context_block()}\n\n{WEB_AUDITOR_INSTRUCTIONS}"

    def build_user_message(self, ctx: AgentContext) -> str:
        url = "https://automiq-landing-astro.vercel.app"
        try:
            if isinstance(ctx.args, dict) and ctx.args.get("url"):
                url = str(ctx.args["url"]).strip()
        except Exception:
            pass
        return (
            f"Auditá la página: {url}\n\n"
            "Descargá con WebFetch la home y hasta 5 páginas internas clave "
            "(precios, producto/features, about, blog, contacto), clasificá el tipo de "
            "negocio, lanzá los subagentes de análisis (contenido, conversión/CRO, SEO, "
            "confianza, captación) y agregá todo en un informe puntuado (0-100 por área) "
            "con quick wins priorizados por impacto en revenue. Español argentino."
        )
