"""Pack `automiq` — 8 agentes de la agencia Automiq como skills de Hermes."""

from .loader import AGENTS, list_agents, get_agent, AGENT_NAMES

__all__ = ["AGENTS", "list_agents", "get_agent", "AGENT_NAMES"]
