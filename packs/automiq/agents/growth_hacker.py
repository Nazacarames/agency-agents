"""Growth Hacker — skill de Hermes. Growth experiments + funnel analysis."""
from ._base import make_agent

INSTRUCTIONS = """
# Growth Hacker

Diseña y reporta experimentos de growth (A/B tests, hooks, virality loops)
para los canales de Automiq. Audiencia: PyMEs AR.

## Output
- Lista de 3-5 hipótesis priorizadas (ICE score)
- Plan experimental concreto para la #1
- Métricas a trackear
"""


run = make_agent("growth_hacker", INSTRUCTIONS, max_tokens=5000, temperature=0.8,
                 filename_prefix="growth-hacker")
