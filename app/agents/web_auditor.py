"""
Web Auditor — auditoría/revisión de páginas web (marketing + CRO + SEO + contenido).
Corre vía Claude Code con la skill `marketing-auditoria`: descarga la página con
WebFetch, clasifica el negocio, lanza subagentes de análisis y produce un informe
puntuado y accionable.

Schedule: lunes 12:00 ART. Default audita la landing de Automiq; se le puede pasar
`args.url` para auditar cualquier página (propia o de un prospecto/cliente).
"""
from .base import BaseAgent, AgentContext
from ._common import get_context_block, upstream_handoff_block


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

## Handoff a outbound / ads (SINERGIA — OBLIGATORIO)
Al final del informe, agregá SIEMPRE una sección titulada exactamente
`## Dolores detectados (handoff)`. Ahí listá 3-5 dolores concretos del negocio
auditado, cada uno con este formato (esto lo consume el agente de cold-email y el
de ads para personalizar el outreach):
- **Dolor:** <1 frase concreta, en las palabras del cliente, no técnica>
- **Evidencia:** <qué viste en la página que lo prueba>
- **Oferta Automiq que lo resuelve:** <agente IA / automatización / landing / ads>
- **Gancho de apertura sugerido:** <1 frase lista para usar como opening de un cold-email>
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
        target_hint = ""
        leads_handoff = ""
        try:
            if isinstance(ctx.args, dict) and ctx.args.get("url"):
                url = str(ctx.args["url"]).strip()
            else:
                # SINERGIA: sin url explícita, intentamos auditar el sitio de un
                # prospecto REAL que generó leadhunter (así el informe alimenta a
                # outbound con dolores de un prospecto, no de la propia landing).
                leads_handoff = upstream_handoff_block(
                    "leadhunter",
                    titulo="Leads recientes de LeadHunter (elegí un prospecto con web para auditar)",
                    max_chars=4000,
                )
                if leads_handoff:
                    target_hint = (
                        "Antes de auditar: mirá el bloque de 'Leads recientes de LeadHunter' "
                        "de abajo, elegí el primer prospecto que tenga una URL/web propia y "
                        "auditá ESA web (no la de Automiq). Si ningún lead tiene web usable, "
                        f"auditá la landing de Automiq ({url}).\n\n"
                    )
        except Exception:
            pass
        return (
            f"{target_hint}"
            f"Auditá la página: {url} (o la del prospecto elegido según la indicación de arriba).\n\n"
            "Descargá con WebFetch la home y hasta 5 páginas internas clave "
            "(precios, producto/features, about, blog, contacto), clasificá el tipo de "
            "negocio, lanzá los subagentes de análisis (contenido, conversión/CRO, SEO, "
            "confianza, captación) y agregá todo en un informe puntuado (0-100 por área) "
            "con quick wins priorizados por impacto en revenue. Español argentino. "
            "Cerrá SIEMPRE con la sección `## Dolores detectados (handoff)`."
            f"{leads_handoff}"
        )
