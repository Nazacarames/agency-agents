"""
Social Media Strategist — calendario semanal de contenido.
Schedule: Domingos 18:00 ART (para la semana que viene).
"""
from .base import BaseAgent, AgentContext
from ._common import get_context_block


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
""".strip()


class SocialMediaAgent(BaseAgent):
    name = "social_media"
    description = "Calendario semanal de contenido (IG + FB)"
    schedule = "0 18 * * 0"   # Domingo 18:00 ART
    timezone = "America/Buenos_Aires"
    max_tokens = 6000

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
        return (
            f"Generá el calendario para la semana que arranca el {week_start}. "
            "Revisá el contenido de la semana actual en data/ para no repetir formatos ni temas. "
            "Balanceá: si la semana pasada fue mucha venta, esta que sea más educativa."
        )
