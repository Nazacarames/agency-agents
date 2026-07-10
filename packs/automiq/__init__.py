"""Pack `automiq` - lista canonica de agentes habilitados (gate de /run y el panel)."""

from .loader import list_agents, AGENT_NAMES

__all__ = ["list_agents", "AGENT_NAMES"]
