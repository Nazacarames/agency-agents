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

## Los DOS sitios (los dos entran en el plan, siempre)
- **automiq.agency** — la agencia. Vende servicio a medida, ticket alto, ciclo
  largo. Busca al que quiere "que alguien me automatice esto".
- **crm.automiq.agency** — el CRM. Es producto SaaS con suscripción mensual:
  otra intención de búsqueda, otro comprador y otra competencia (los que ya
  buscan "CRM" por nombre). Tiene su propia landing comercial en la raíz.

No son el mismo sitio con distinta ropa: si les das las mismas keywords compiten
entre ellos por la misma consulta y pierden los dos. Repartí:
- Consultas de **servicio/agencia** ("automatizar", "agente de IA a medida",
  "agencia") → automiq.agency.
- Consultas de **producto/herramienta** ("CRM", "software de gestión de
  clientes", "CRM con WhatsApp", comparativas y alternativas) → crm.automiq.agency.
- Enlazá uno al otro con anchor descriptivo: la landing del CRM es la prueba
  viva de lo que hace la agencia, y la agencia es el soporte que el SaaS no tiene.

### CRM (producto, para crm.automiq.agency)
- "CRM para PyMEs Argentina"
- "CRM con WhatsApp integrado"
- "CRM barato para pequeña empresa"
- "alternativa a [CRM conocido] en español"
- "CRM que responde WhatsApp solo"

## Foco por vertical (para la landing de la AGENCIA)
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
   dificultad baja/media/alta, intención: comercial/informacional). **Cada
   keyword dice a qué sitio va**: `[agencia]` o `[crm]`. Al menos 3 de las 10
   tienen que ser del CRM.
2. **5 ideas de artículos/blog posts** (títulos + keyword target + outline 3-5 puntos)
3. **Optimizaciones on-page** (cambios concretos a la landing). Separadas en dos
   listas, una por sitio, porque las ejecuta gente distinta: las de la agencia
   las hace web_optimizer; las del CRM van al backlog como `crm-web`.
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


def _hechos_landing() -> str:
    """Datos medidos del HTML servido de los DOS sitios: que el análisis arranque
    de hechos y no de impresiones (el 'H1 vacío' se reportó 22 días seguidos y
    era falso)."""
    try:
        from ..integrations import landing_facts
        return landing_facts.bloque_todos()
    except Exception:
        return ""


class SeoSpecialistAgent(BaseAgent):
    name = "seo_specialist"
    description = "Plan SEO semanal (keywords + contenido + on-page + links) alineado al Big Domino"
    schedule = "0 8 * * 1"   # 2026-06-12: cambiado de "día 15 del mes" a lunes 08:00 semanal
    timezone = "America/Buenos_Aires"
    max_tokens = 12000  # 2026-06-12: subido de 6000 (truncamiento observado en producción)
    use_claude_code = True
    claude_code_skill = "marketing-seo-contenido,ai-seo,schema,programmatic-seo,competitors,lead-magnets,directory-submissions,public-relations"
    claude_code_timeout = 900  # puede WebFetchear la landing para on-page real

    @property
    def system_prompt(self) -> str:
        return f"{get_context_block()}\n\n{SEO_INSTRUCTIONS}"

    def build_user_message(self, ctx: AgentContext) -> str:
        return (
            _hechos_landing() +
            "Generá el plan SEO completo de esta semana para los DOS sitios: "
            "automiq.agency (la agencia) y crm.automiq.agency (el CRM, producto "
            "SaaS con su propia landing). El del CRM no es un extra al final: "
            "reparte las keywords entre los dos según la intención, como dice el "
            "system prompt, y marcá cada una con [agencia] o [crm]. "
            "En la agencia priorizá el vertical DISTRIBUCIÓN pero incluí también "
            "manufacturing, logística e inmobiliarias. "
            "Devolvé el plan COMPLETO (los 6 puntos del output esperado) en una "
            "sola corrida. NO devuelvas 'primero dejame chequear data/' ni el plan "
            "parcial. El equipo operativo necesita el plan entero para ejecutar "
            "esta semana. Usá [BENCHMARK] para volúmenes estimados de keywords. "
            "Cada recomendación de contenido tiene que arrancar por el problema "
            "del cliente, no por la tecnología."
        )
