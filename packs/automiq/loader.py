"""
Pack automiq — la lista canónica de agentes habilitados.

AGENT_NAMES es el GATE de /run, /last y el panel (main.py valida contra esta
lista). La implementación real de cada agente vive en `app/agents/<name>.py`
(registry); acá NO hay código de agentes — los stubs viejos de
packs/automiq/agents/ nunca corrían y confundían (editarlos no hacía nada),
así que se eliminaron.
"""
from __future__ import annotations

from typing import List

AGENT_NAMES: List[str] = [
    "leadhunter",
    "content_creator",
    "tiktok_creator",
    "growth_hacker",
    "creative_strategist",
    "social_media",
    "outbound",
    "media_auditor",
    "seo_specialist",
    "web_auditor",
    "inbox_assistant",
    "meeting_prep",
    "web_optimizer",
    "chief_of_staff",
]


def list_agents() -> List[str]:
    """Nombres de los agentes habilitados del pack."""
    return list(AGENT_NAMES)
