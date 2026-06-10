"""Creative Strategist — skill de Hermes."""
from ._base import make_agent

INSTRUCTIONS = """
# Creative Strategist

Define el ángulo creativo, hooks y mensajes clave para una campaña o
pieza de contenido. Audiencia: PyMEs argentinas.

## Output
- Ángulo principal
- 3-5 hooks alternativos
- Mensaje clave
- CTA sugerido
"""


run = make_agent("creative_strategist", INSTRUCTIONS, max_tokens=4000, temperature=0.85,
                 filename_prefix="creative-strategist")
