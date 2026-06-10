"""Media Auditor — skill de Hermes. Análisis de performance de campañas."""
from ._base import make_agent

INSTRUCTIONS = """
# Media Auditor

Analiza el rendimiento de las últimas campañas (Ads, LinkedIn, email).
Devuelve:
- CTR / CPL / ROAS por canal
- Top 3 anuncios
- Recomendaciones accionables
- Presupuesto sugerido para próximo mes
"""


run = make_agent("media_auditor", INSTRUCTIONS, max_tokens=6000, temperature=0.5,
                 filename_prefix="media-auditor")
