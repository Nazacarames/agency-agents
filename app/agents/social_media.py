"""
Social Media Strategist — calendario semanal de contenido.
Schedule: Domingos 18:00 ART (para la semana que viene).
"""
from .base import BaseAgent, AgentContext
from ._common import (get_context_block, official_site_directive,
                      image_prompt_directive, augment_with_images,
                      competitor_visual_directive_for)


def _estilos_del_lote(texto: str) -> set:
    """Los `ESTILO: x` que pidió el agente en esta corrida."""
    import re
    return {m.group(1).lower() for m in
            re.finditer(r"ESTILO:\s*([a-záéíóúñ]+)", texto or "", re.IGNORECASE)}


def _feed_lleno() -> tuple:
    """(carril lleno?, pendientes, tope). El carril de feed drena 1/día: cuando se
    llena, `enqueue()` descarta en silencio lo que se generó. Mejor planificar
    historias y decirlo que producir piezas que no entran."""
    try:
        from ..integrations import publish_queue as pq
        pend = pq.pending_count(lane="feed")
        return (pend >= pq.MAX_PENDING_FEED, pend, pq.MAX_PENDING_FEED)
    except Exception:
        return (False, 0, 0)


def _playbook_block() -> str:
    try:
        from ..integrations.competitor_playbook import playbook_block
        return playbook_block()
    except Exception:
        return ""


SOCIAL_MEDIA_INSTRUCTIONS = """
# Social Media Strategist — Automiq

## Objetivo
Armar el calendario de la semana que viene (Lun a Dom) para Instagram y Facebook
de Automiq.

## Output
Una tabla markdown con columnas:
| Día | Fecha | Plataforma | Formato | Tema / Hook | Caption corto | Hashtags | Objetivo |

Y debajo de la tabla, el detalle de:
- 1 campaña de IG/FB Stories con secuencia de 5 frames
- 1 colaboración o reel colaborativo propuesto
- Métricas clave a mirar al final de la semana

## Reglas de frecuencia
- Lun a Vie: 1 post estático o carrusel por día + 3 stories
- Sáb: 1 reel o IGTV largo (contenido de valor)
- Dom: descanso (sólo stories de engagement si hay)

## Tono y estilo
- Profesional pero accesible
- Español argentino
- 70% valor educativo / 20% prueba social / 10% venta directa
- NO postear sin un objetivo claro (alcance / consideración / conversión)
- **BIG DOMINO** (NUEVO 2026-06-12, de Visual Project V2): el calendario tiene
  que girar alrededor del Big Domino. Cada post es una pequeña prueba de que
  Automiq resuelve un problema concreto de un cliente específico. Evitar contenido
  genérico sobre "qué es la IA".
- **Documentar el journey** (NUEVO 2026-06-12, de Claudio Conde V1): incluir al
  menos 1 "Detrás de escena" por semana (mostrar el proceso, no el resultado
  pulido). Esto es lo que construye la marca personal.
- **Empresa → Oferta → Tecnología** (NUEVO 2026-06-12): la mayoría de los posts
  arrancan por el problema del cliente (empresa), no por la herramienta. El
  agente de IA / WhatsApp se menciona al final, si es que se menciona.
""".strip()


class SocialMediaAgent(BaseAgent):
    name = "social_media"
    needs_creative_material = True
    description = "Calendario semanal de contenido (IG + FB)"
    schedule = "0 18 * * 0"   # Domingo 18:00 ART
    timezone = "America/Buenos_Aires"
    max_tokens = 6000
    use_claude_code = True
    claude_code_skill = "marketing-redes,hook-generator,post-formatter,social,copywriting,humanizer"
    claude_code_timeout = 700
    llm_provider = "glm"   # GLM 5.2: copy más vivo; fallback CC/MiniMax

    @property
    def system_prompt(self) -> str:
        return f"{get_context_block()}\n\n{SOCIAL_MEDIA_INSTRUCTIONS}"

    def build_user_message(self, ctx: AgentContext) -> str:
        from datetime import datetime, timedelta
        import pytz
        tz = pytz.timezone("America/Buenos_Aires")
        # Domingo actual → lunes próximo
        today = datetime.now(tz)
        next_monday = today + timedelta(days=(7 - today.weekday()) % 7 + (7 if today.weekday() == 6 else 0))
        # Si hoy es domingo, el lunes próximo es mañana
        if today.weekday() == 6:
            next_monday = today + timedelta(days=1)
        week_start = next_monday.strftime("%Y-%m-%d")
        lleno, pend, tope = _feed_lleno()
        aviso = ("" if not lleno else
                 f"\n\n⚠️ **El carril de FEED está lleno** ({pend} pendientes, tope {tope}): "
                 "todo lo que encoles como post/carrusel se descarta sin publicar. "
                 "Planificá SOLO historias (`FORMATO: historia`) hasta que baje, y decilo "
                 "arriba de tu reporte con `feed_blocked=true` y cuántas piezas esperan.")
        return (
            f"Generá el calendario para la semana que arranca el {week_start}. "
            "Revisá el contenido de la semana actual en data/ para no repetir formatos ni temas. "
            "Balanceá: si la semana pasada fue mucha venta, esta que sea más educativa."
            + aviso
            + official_site_directive()
            + competitor_visual_directive_for(ctx)
            + _playbook_block()
            + image_prompt_directive()
        )

    def post_process(self, response_text: str, ctx: AgentContext) -> str:
        from ..config import get_settings
        s = get_settings()
        pub = s.social_auto_publish
        args = getattr(ctx, "args", None) or {}
        if isinstance(args, dict) and "publish" in args:
            pub = bool(args["publish"])
        # QA con Gemini ANTES de encolar: si el contenido está muy flojo, frena el
        # auto-publish (queda para revisión) en vez de mandar algo malo. Best-effort.
        pub_final, qa_line, gap_line = pub, "", ""
        try:
            from ..integrations import text_judge
            # Los estilos que son texto (tipográfico) o metáfora (surreal) puntúan
            # bajo con la rúbrica de foto aunque hagan bien su trabajo: el 2026-08-16
            # un lote tipográfico sacó 12/100 y se frenó la publicación entera. Se
            # miden con umbral 30, y el reporte dice con qué vara se midió.
            estilos = _estilos_del_lote(response_text)
            legible = bool(estilos) and estilos <= {"tipografico", "surreal"}
            gate = text_judge.qa_gate(
                self.name, "social", response_text,
                hold_below=30 if legible else None,
                qa_mode="legibilidad" if legible else "")
            pub_final = pub and gate["publish_ok"]
            qa_line = gate["line"]
            # Cierre del loop competitivo: brecha vs el estudio del competidor → lección.
            gap_line = text_judge.competitor_gap(self.name, response_text, "imagen")
        except Exception:
            pass
        text = augment_with_images(response_text, s.content_image_count, publish=pub_final)
        lleno, pend, tope = _feed_lleno()
        if lleno:
            text += (f"\n\n`feed_blocked=true` — {pend} piezas de feed esperando (tope {tope}). "
                     "Lo que se encole como post/carrusel hoy se descarta sin publicar.")
        if qa_line:
            text += "\n" + qa_line
        if gap_line:
            text += "\n" + gap_line
        return super().post_process(text, ctx)
