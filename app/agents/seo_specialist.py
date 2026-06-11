"""
SEO Specialist — plan de acción SEO orgánico.
Schedule: día 15 de cada mes a las 11:00 ART.
"""
from .base import BaseAgent, AgentContext
from ._common import get_context_block


SEO_INSTRUCTIONS = """
# SEO Specialist — Automiq

## Objetivo
Armar (o actualizar) el plan SEO mensual de Automiq para captar tráfico orgánico
calificado de PyMEs argentinas buscando automatizar sus procesos.

## Foco
Keywords long-tail en español:
- "automatizar [proceso] para PyMEs"
- "WhatsApp business para empresas"
- "CRM para PyMEs Argentina"
- "agencia automatización IA Argentina"
- etc.

## Output
1. **Top 10 keywords a atacar este mes** (con volumen estimado, dificultad, intención)
2. **5 ideas de artículos/blog posts** (títulos + keyword target + outline de 3-5 puntos)
3. **Optimizaciones on-page** (cambios concretos a la landing)
4. **Link building** (3-5 tácticas ejecutables este mes)
5. **Quick wins técnicos** (errores 404, sitemap, schema, velocidad)

## Reglas
- Contenido en español argentino, no español neutro
- Keywords con intención comercial O informativa-alta
- No recomendar comprar links ni PBNs
- Todo accionable esta semana, no "el mes que viene"
""".strip()


class SeoSpecialistAgent(BaseAgent):
    name = "seo_specialist"
    description = "Plan SEO mensual (keywords + contenido + on-page + links)"
    schedule = "0 11 15 * *"  # Día 15 de cada mes, 11:00 ART
    timezone = "America/Buenos_Aires"
    max_tokens = 6000
    use_claude_code = True
    claude_code_skill = "marketing-seo-contenido"
    claude_code_timeout = 900  # puede WebFetchear la landing para on-page real

    @property
    def system_prompt(self) -> str:
        return f"{get_context_block()}\n\n{SEO_INSTRUCTIONS}"

    def build_user_message(self, ctx: AgentContext) -> str:
        return (
            "Generá el plan SEO de este mes para automiq-landing-astro.vercel.app "
            "(landing oficial de Automiq, hospedada en Vercel). "
            "El sitio apunta a PyMEs manufactureras, distribuidoras y logísticas argentinas. "
            "Incluí keywords long-tail en español argentino con intención comercial o informativa alta. "
            "No repitas keywords ni ideas de artículos que ya figuren en el system prompt. "
            "Devolvé el plan completo (los 5 puntos del output esperado) listo para que el equipo ejecute."
        )
