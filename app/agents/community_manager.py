"""
Community Manager — engagement de comunidad (departamento Marketing).

Mira los comentarios/DMs recientes de las redes y DECIDE la interacción: a qué
comentario responder, con quién enganchar, qué mensaje conviene. No crea contenido
(eso es content/social); se encarga de la conversación. Autonomía de Marketing =
"publica": puede responder engagement ya en curso, nunca a un cliente nuevo.
"""
from .base import BaseAgent, AgentContext
from ._common import get_context_block
from ..log import get_logger

log = get_logger("community_manager")

CM_INSTRUCTIONS = """
# Community Manager — Automiq

## Quién sos
Sos el COMMUNITY MANAGER de Automiq. Tu trabajo es la CONVERSACIÓN en las redes:
responder comentarios y DMs, enganchar con la audiencia y detectar oportunidades
(alguien preguntando por el servicio, un lead tibio, una queja). NO producís los
posts (eso lo hacen content/social); vos gestionás lo que pasa DESPUÉS de publicar.

## Reglas de oro
1. **Prioridad por valor**: un comentario que huele a lead o una queja van PRIMERO.
   El "🔥" genérico, respuesta corta o ninguna.
2. **Voz de marca, humana**: respuestas que suenan a persona, no a bot. Cortas,
   con onda porteña, sin sonar a copy pegado.
3. **Comment-gate**: si un post pide comentar una palabra para recibir algo, el
   sistema ya auto-DMea; vos cubrís lo que queda afuera de ese flujo.
4. **Oportunidades → al pipeline**: si detectás un lead real, marcalo para que
   Comercial lo tome (no lo cierres vos).
5. **Nunca inventes**: si no sabés algo del producto/precio, no improvises;
   derivás o marcás para responder con data.

## Formato de salida
- **Cola de respuestas**: por cada comentario/DM que amerita → a quién, qué post,
  y la respuesta sugerida (o enviada, según autonomía).
- **Oportunidades detectadas**: leads/quejas para que Comercial/CS tomen.
- **Pulso de la comunidad**: qué temas/reacciones se repiten (feedback para content).
"""


class CommunityManagerAgent(BaseAgent):
    name = "community_manager"
    description = "Engagement: responde comentarios/DMs, engancha y detecta oportunidades"
    schedule = "30 15 * * mon-fri"  # días hábiles 15:30, después de social_media
    max_tokens = 5000
    llm_provider = "glm"            # copy/voz viva; fallback MiniMax
    claude_code_skill = "social,humanizer"

    @property
    def system_prompt(self) -> str:
        from .departments import autonomy_note
        return f"{get_context_block()}\n\n{autonomy_note(self.name)}\n\n{CM_INSTRUCTIONS}"

    def build_user_message(self, ctx: AgentContext) -> str:
        parts = ["Gestioná la conversación de la comunidad con lo de abajo.\n"]
        try:
            from ..integrations import comment_watch as cw
            data = cw.check(n_posts=12)
            parts.append(f"## Comentarios recientes detectados\n{data}\n")
        except Exception as e:
            log.warning("cm_comments_failed", error=str(e)[:150])
        if len(parts) == 1:
            parts.append("(No pude leer comentarios en vivo ahora — igual dejá el "
                         "playbook de respuestas: cómo contestar los 4-5 tipos de "
                         "comentario más comunes de nuestro nicho, listo para usar.)")
        return "\n".join(parts)
