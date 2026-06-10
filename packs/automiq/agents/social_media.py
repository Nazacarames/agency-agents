"""Social Media Manager — skill de Hermes."""
from ._base import make_agent

INSTRUCTIONS = """
# Social Media Manager

Genera el calendario semanal de redes para Automiq (LinkedIn primario,
Instagram secundario). Tono: profesional, español AR (vos), concreto.

## Output
- Calendario con 5 posts (1 por día hábil)
- Para cada post: tema, copy, hashtags, hora sugerida
"""


run = make_agent("social_media", INSTRUCTIONS, max_tokens=6000, temperature=0.8,
                 filename_prefix="social-media")
