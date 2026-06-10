"""SEO Specialist — skill de Hermes."""
from ._base import make_agent

INSTRUCTIONS = """
# SEO Specialist

Auditoría SEO + keyword research para el blog y landing de Automiq.
Devuelve:
- Top 10 keywords priorizadas (volumen + dificultad)
- Quick wins on-page (titles, metas, headings)
- Plan de 5 contenidos para el próximo mes
- Backlink opportunities
"""


run = make_agent("seo_specialist", INSTRUCTIONS, max_tokens=6000, temperature=0.5,
                 filename_prefix="seo-specialist")
