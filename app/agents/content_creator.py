"""
Content Creator — ideas de contenido para redes de Automiq.
Schedule: Lunes, Miércoles, Viernes 13:00 ART.
"""
from .base import BaseAgent, AgentContext
from ._common import get_context_block


CONTENT_CREATOR_INSTRUCTIONS = """
# Content Creator — Automiq

## Objetivo
Generar 3 ideas de contenido para redes de Automiq (Instagram, Facebook)
con copy listo para usar.

## Tipos de contenido (rotar)
- **Caso de uso / Antes-Después**: cliente que automatizó X proceso
- **Mito vs Realidad**: creencias falsas sobre IA/automatización en PyMEs
- **Tip accionable**: 1 automatización que cualquier PyME puede hacer esta semana
- **Detrás de escena**: cómo trabajamos en Automiq (proceso, herramientas)
- **Pregunta / Encuesta**: para generar interacción

## Por cada idea entregar
1. **Formato**: reel / carrusel / post estático / story
2. **Hook**: primera línea (máx 80 chars, tiene que atrapar)
3. **Cuerpo**: copy completo (3-5 líneas para posts, 15-30s para reels)
4. **CTA**: call to action (comentá, escribinos, agendá)
5. **Hashtags**: 5-8 relevantes (sin #FollowForFollow)
6. **Visual sugerido**: qué mostrar en la imagen/video

## Reglas
- Español argentino (vos, decí, querés)
- Evitar jargon técnico innecesario
- Tono: profesional pero accesible, no corporativo frío
- NO prometer resultados garantizados ("vas a vender 10x más" ❌)
- Devolver TODO listo para agendar en Metricool o similar
""".strip()


class ContentCreatorAgent(BaseAgent):
    name = "content_creator"
    description = "Genera 3 ideas de contenido listas para redes"
    schedule = "0 13 * * 1,3,5"   # Lun/Mie/Vie 13:00 ART
    timezone = "America/Buenos_Aires"
    max_tokens = 5000

    @property
    def system_prompt(self) -> str:
        return f"{get_context_block()}\n\n{CONTENT_CREATOR_INSTRUCTIONS}"

    def build_user_message(self, ctx: AgentContext) -> str:
        return (
            "Generá las 3 ideas de contenido de hoy. "
            "Elegí 3 formatos DIFERENTES (no repitas). "
            "Cada idea tiene que estar lista para que el equipo de diseño la ejecute sin preguntas. "
            "Recordá chequear data/ por contenido previo para no repetir temas."
        )
