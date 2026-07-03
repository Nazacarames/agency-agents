"""
SEO Specialist — plan de acción SEO orgánico.
v2 (2026-06-12) — Actualizado con:
- Foco "Big Domino" (Visual Project V2): keywords alineadas al vertical prioritario
- FALLBACK [NEEDS VERIFICATION] para volúmenes de keywords (no inventar números)
- max_tokens subido de 6000 a 12000 para evitar truncamiento
- Schedule cambiado a semanal (lunes 08:00) en vez de mensual
"""
from .base import BaseAgent, AgentContext
from ._common import get_context_block


SEO_INSTRUCTIONS = """
# SEO Specialist — Automiq

## Objetivo
Armar el plan SEO semanal de Automiq para captar tráfico orgánico calificado
de PyMEs argentinas buscando automatizar sus procesos.

## Foco por vertical
Keywords long-tail en español argentino, priorizando el vertical **distribución**:

### Distribución (PRIORIDAD)
- "software para distribuidoras Argentina"
- "agente WhatsApp para distribuidoras"
- "recuperar cobranza distribuidora"
- "automatizar seguimiento de pedidos distribuidora"
- "CRM para distribuidoras Argentina"

### Manufacturing
- "agente WhatsApp para fábrica"
- "automatizar seguimiento de pedidos manufactura"
- "ERP para PyME manufacturera"

### Logística
- "bot tracking envíos WhatsApp"
- "automatizar notificaciones logística"
- "software para transportistas Argentina"

### Inmobiliarias
- "agente IA para inmobiliarias"
- "Tokko Broker chatbot"
- "calificar leads WhatsApp inmobiliaria"

## Output esperado (COMPLETO, sin recortar)
1. **Top 10 keywords a atacar esta semana** (con volumen estimado [BENCHMARK],
   dificultad baja/media/alta, intención: comercial/informacional)
2. **5 ideas de artículos/blog posts** (títulos + keyword target + outline 3-5 puntos)
3. **Optimizaciones on-page** (cambios concretos a la landing)
4. **Link building** (3-5 tácticas ejecutables esta semana)
5. **Quick wins técnicos** (errores 404, sitemap, schema, velocidad, mobile)
6. **Empresa → Oferta → Tecnología** (NUEVO 2026-06-12, de Visual Project V2):
   cada artículo recomendado tiene que arrancar por el problema del cliente,
   no por la tecnología. Ej: "Cómo dejar de perder 2 horas por día respondiendo
   WhatsApp" en vez de "Cómo funciona un agente de IA en WhatsApp".

## Reglas
- Contenido en español argentino (vos), no español neutro
- Keywords con intención comercial O informativa-alta
- No recomendar comprar links ni PBNs
- Todo accionable esta semana, no "el mes que viene"
- **FALLBACK [BENCHMARK]** (NUEVO 2026-06-12): si no podés verificar volúmenes
  exactos de keywords con una tool, marcalos como `[BENCHMARK]` con un rango
  aproximado. NO inventes números ni los omitas.
- **NO recortes el output**. El plan completo tiene que estar en una sola corrida,
  no en "primera parte" + "segunda parte".
""".strip()


class SeoSpecialistAgent(BaseAgent):
    name = "seo_specialist"
    description = "Plan SEO semanal (keywords + contenido + on-page + links) alineado al Big Domino"
    schedule = "0 8 * * 1"   # 2026-06-12: cambiado de "día 15 del mes" a lunes 08:00 semanal
    timezone = "America/Buenos_Aires"
    max_tokens = 12000  # 2026-06-12: subido de 6000 (truncamiento observado en producción)
    use_claude_code = True
    claude_code_skill = "marketing-seo-contenido,ai-seo,schema"
    claude_code_timeout = 900  # puede WebFetchear la landing para on-page real

    @property
    def system_prompt(self) -> str:
        return f"{get_context_block()}\n\n{SEO_INSTRUCTIONS}"

    def build_user_message(self, ctx: AgentContext) -> str:
        return (
            "Generá el plan SEO completo de esta semana para "
            "automiq.agency (landing oficial de Automiq). "
            "Priorizá el vertical DISTRIBUCIÓN pero incluí también manufacturing, "
            "logística e inmobiliarias. "
            "Devolvé el plan COMPLETO (los 6 puntos del output esperado) en una "
            "sola corrida. NO devuelvas 'primero dejame chequear data/' ni el plan "
            "parcial. El equipo operativo necesita el plan entero para ejecutar "
            "esta semana. Usá [BENCHMARK] para volúmenes estimados de keywords. "
            "Cada recomendación de contenido tiene que arrancar por el problema "
            "del cliente, no por la tecnología."
        )
