"""Outbound — skill de Hermes. Secuencias de cold outreach multi-canal."""
from ._base import make_agent

INSTRUCTIONS = """
# Outbound

Genera secuencias de cold outreach (email + LinkedIn + WhatsApp) para
los leads del último reporte de LeadHunter.

## Input esperado
- args.target_vertical (opcional)
- args.target_ciudad (opcional)

## Output
- Secuencia de 5 toques: 1er email, follow-up 1, follow-up 2, LinkedIn DM, WhatsApp rompe-hielo
- Personalización por vertical/ciudad
- Tono: directo, sin spam, valor primero
"""


run = make_agent("outbound", INSTRUCTIONS, max_tokens=6000, temperature=0.7,
                 filename_prefix="outbound")
