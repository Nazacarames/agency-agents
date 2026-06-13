"""
Registry de agentes — los módulos de agentes se importan aquí y se auto-registran.
Para agregar un agente nuevo, basta con crear un archivo en app/agents/ e importarlo abajo.
"""
from typing import Dict, List

from .base import BaseAgent

_REGISTRY: Dict[str, BaseAgent] = {}


def register_agent(agent: BaseAgent) -> None:
    if agent.name in _REGISTRY:
        raise ValueError(f"Agente duplicado: {agent.name}")
    _REGISTRY[agent.name] = agent


def get_agent(name: str) -> BaseAgent:
    if name not in _REGISTRY:
        raise KeyError(f"Agente no encontrado: {name}. Disponibles: {list(_REGISTRY.keys())}")
    return _REGISTRY[name]


def list_agents() -> List[BaseAgent]:
    return list(_REGISTRY.values())


# ── Importar todos los agentes (auto-registro por side-effect) ──
from . import leadhunter       # noqa: F401, E402
from . import content_creator  # noqa: F401, E402
from . import growth_hacker    # noqa: F401, E402
from . import creative_strategist  # noqa: F401, E402
from . import social_media     # noqa: F401, E402
from . import outbound         # noqa: F401, E402
from . import media_auditor    # noqa: F401, E402
from . import seo_specialist   # noqa: F401, E402
from . import web_auditor      # noqa: F401, E402
from . import inbox_assistant  # noqa: F401, E402
