"""
Content Creator — ideas de contenido para redes de Automiq.
v2 (2026-06-12) — Actualizado con:
- Foco "Big Domino" (Visual Project V2): el contenido gira alrededor del pitch central
- "Documentar el journey" (Claudio Conde V1): al menos 1 "Detrás de escena" por semana
- "Empresa → Oferta → Tecnología" (Visual Project V2): copy arranca por el problema
- max_tokens subido de 5000 a 12000 para evitar truncamiento
"""
from .base import BaseAgent, AgentContext
from ._common import (get_context_block, official_site_directive,
                      image_prompt_directive, augment_with_images,
                      competitor_visual_directive_for)


CONTENT_CREATOR_INSTRUCTIONS = """
# Content Creator — Automiq

## Objetivo
Generar 3 ideas de contenido para redes de Automiq (Instagram, Facebook, LinkedIn)
con copy listo para usar, alineadas al Big Domino de la agencia.

## Tipos de contenido (rotar)
- **Caso de uso / Antes-Después**: cliente que automatizó X proceso
- **Mito vs Realidad**: creencias falsas sobre IA/automatización en PyMEs
- **Tip accionable**: 1 automatización que cualquier PyME puede hacer esta semana
- **Detrás de escena**: cómo trabajamos en Automiq (proceso, herramientas, journey)
- **Pregunta / Encuesta**: para generar interacción

## Por cada idea entregar (formato OBLIGATORIO)
1. **Tipo de contenido** (uno de los 5 de arriba)
2. **Formato visual** (reel / carrusel / post estático / story)
3. **Industria target** (manufacturing / distribución / logística / inmobiliarias)
4. **Hook**: primera línea (máx 80 chars, tiene que atrapar)
5. **Cuerpo**: copy completo (3-5 líneas para posts, 15-30s para reels)
6. **CTA**: call to action (comentá, escribinos, agendá)
7. **Hashtags**: 5-8 relevantes (sin #FollowForFollow)
8. **Visual sugerido**: qué mostrar en la imagen/video

## Reglas
- Español argentino (vos, decí, querés)
- Evitar jargon técnico innecesario
- Tono: profesional pero accesible, no corporativo frío
- NO prometer resultados garantizados ("vas a vender 10x más" ❌)
- Devolver TODO listo para agendar en Metricool o similar
- **Foco "Big Domino"** (NUEVO 2026-06-12, de Visual Project V2): el contenido
  tiene que girar alrededor del Big Domino de Automiq. Cada post es una pequeña
  prueba de que resolvemos un problema concreto de un cliente específico.
- **Documentar el journey** (NUEVO 2026-06-12, de Claudio Conde V1): incluir
  al menos 1 idea de "Detrás de escena" por semana. Mostrar el proceso real,
  no el resultado pulido. Eso es lo que conecta.
- **Empresa → Oferta → Tecnología** (NUEVO 2026-06-12, de Visual Project V2):
  el copy arranca con el problema del cliente (empresa), después muestra
  cómo se resuelve (oferta), y solo al final menciona la herramienta.
""".strip()


class ContentCreatorAgent(BaseAgent):
    name = "content_creator"
    description = "Genera 3 ideas de contenido listas para redes (alineadas al Big Domino)"
    schedule = "0 9 * * 1"   # 2026-06-12: cambiado a lunes 09:00 (antes 13:00 3x semana)
    timezone = "America/Buenos_Aires"
    max_tokens = 12000  # 2026-06-12: subido de 5000 (truncamiento observado en producción)
    use_claude_code = True
    claude_code_skill = "marketing-redes"
    claude_code_timeout = 700

    @property
    def system_prompt(self) -> str:
        return f"{get_context_block()}\n\n{CONTENT_CREATOR_INSTRUCTIONS}"

    def build_user_message(self, ctx: AgentContext) -> str:
        return (
            "Generá las 3 ideas de contenido de la semana. "
            "Elegí 3 tipos DIFERENTES entre sí. "
            "Cada idea tiene que estar 100% lista (hook + cuerpo + CTA + hashtags + visual). "
            "Rotá entre industrias (manufacturing, logística, distribución, inmobiliarias) "
            "y entre ángulos (caso de uso, mito, tip, detrás de escena, encuesta). "
            "Alineá todo al Big Domino de Automiq: ayudar a PyMEs manufactureras/distribuidoras/"
            "logísticas a recuperar cobranza / ahorrar horas / aumentar citas. "
            "NO recortes las ideas. El copy tiene que estar completo en cada una, "
            "aunque sean largas. El equipo de diseño las va a tomar tal cual salen."
            + official_site_directive()
            + competitor_visual_directive_for(ctx)
            + image_prompt_directive()
        )

    def post_process(self, response_text: str, ctx: AgentContext) -> str:
        from ..config import get_settings
        text = augment_with_images(response_text, get_settings().content_image_count)
        return super().post_process(text, ctx)
