"""
Loader de los 8 agentes de Automiq.

Auto-descubre los archivos `packs/automiq/agents/*.py` (excepto `_base.py`)
y expone un dict `{name: run_fn}` listo para registrar en Hermes.

Convención: cada archivo define un módulo con una función `run(ctx, args) -> str`
(o la crea via `make_agent` desde `_base.py`).
"""
from __future__ import annotations

import importlib
import pkgutil
from pathlib import Path
from typing import Any, Callable, Dict, List

# Esta lista es la fuente de verdad del orden de los 8 agentes.
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
]

_AGENTS_DIR = Path(__file__).resolve().parent / "agents"

# Carga lazy: se importa cada módulo al pedirlo
_CACHE: Dict[str, Any] = {}


def _load(name: str) -> Any:
    if name in _CACHE:
        return _CACHE[name]
    mod = importlib.import_module(f"packs.automiq.agents.{name}")
    _CACHE[name] = mod
    return mod


def get_agent(name: str) -> Callable:
    """Devuelve la función `run(ctx, args) -> str` del agente."""
    if name not in AGENT_NAMES:
        raise KeyError(f"agent {name!r} not in pack automiq")
    mod = _load(name)
    run = getattr(mod, "run", None)
    if run is None or not callable(run):
        raise RuntimeError(f"agent {name!r} does not expose a callable `run`")
    return run


def list_agents() -> List[str]:
    """Lista los nombres de los 8 agentes del pack."""
    return list(AGENT_NAMES)


AGENTS: Dict[str, Callable] = {name: (lambda n=name: get_agent(n)) for name in AGENT_NAMES}
