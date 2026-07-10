"""
Container de dependencias — singleton que mantiene los clientes vivos
mientras la app esté corriendo. Reemplaza el "main agent" de OpenClaw.
"""
from __future__ import annotations

import asyncio
import uuid
from typing import Any, Dict, Optional

from .clients.minimax import MiniMaxClient, MiniMaxError
from .clients.discord import DiscordWebhook, DiscordError
from .config import Settings, get_settings
from .log import get_logger
from .agents.base import AgentContext
from .agents.registry import get_agent

log = get_logger("container")


class Container:
    """Mantiene los clientes compartidos y expone run_agent() y run_scheduled()."""

    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()
        self._minimax: Optional[MiniMaxClient] = None
        self._discord: Optional[DiscordWebhook] = None
        # Un lock POR AGENTE: serializa cron + corridas manuales del panel/API.
        # Sin esto, dos corridas simultáneas de outbound leían el mismo store y
        # mandaban cold-emails DUPLICADOS (max_instances=1 solo cubre el cron).
        self._agent_locks: Dict[str, asyncio.Lock] = {}

    # ── lazy init (evita fallar al startup si faltan credenciales) ──

    @property
    def minimax(self) -> MiniMaxClient:
        if self._minimax is None:
            self._minimax = MiniMaxClient(self.settings)
        return self._minimax

    @property
    def discord(self) -> Optional[DiscordWebhook]:
        if self._discord is None:
            if not self.settings.discord_configured:
                return None
            self._discord = DiscordWebhook(self.settings)
        return self._discord

    def close(self) -> None:
        if self._minimax:
            self._minimax.close()
            self._minimax = None
        if self._discord:
            self._discord.close()
            self._discord = None

    def health(self) -> Dict[str, Any]:
        return {
            "minimax_configured": bool(self.settings.minimax_api_key),
            "discord_configured": self.settings.discord_configured,
            "global_pause": self.settings.global_pause,
            "is_production": self.settings.is_production,
        }

    # ── run helpers ──

    async def run_agent(
        self,
        agent_name: str,
        *,
        triggered_by: str = "manual",
        args: Optional[Dict[str, Any]] = None,
        run_id: Optional[str] = None,
    ) -> str:
        args = args or {}
        run_id = run_id or str(uuid.uuid4())
        # Allow an explicit runtime override via args.force_global to bypass GLOBAL_PAUSE
        if self.settings.global_pause and not (isinstance(args, dict) and args.get("force_global") is True):
            log.info("agent_skipped_global_pause", agent=agent_name, run_id=run_id)
            return "⏸️ Global pause activo"

        agent = get_agent(agent_name)
        ctx = AgentContext(
            settings=self.settings,
            minimax=self.minimax,
            discord=self.discord,
            run_id=run_id,
            triggered_by=triggered_by,
            args=args,
        )
        lock = self._agent_locks.setdefault(agent_name, asyncio.Lock())
        if lock.locked():
            log.warning("agent_run_queued_behind_lock", agent=agent_name,
                        run_id=run_id, triggered_by=triggered_by)
        async with lock:
            # run() es sync porque MiniMaxClient es sync; lo corremos en threadpool
            return await asyncio.to_thread(agent.run, ctx)

    async def run_scheduled(self, agent_name: str) -> None:
        """Schedule del pack automiq. Se ejecuta vía main._run_pack_agent."""
        # El run real se hace desde la tarea programada con su propio ctx.
        # Mantenemos este método por compatibilidad; en el nuevo main.py
        # se llama directo a _run_pack_agent.
        await self.run_agent(agent_name, triggered_by="cron")


# ── Singleton global usado por el scheduler y los endpoints ──
_container: Optional[Container] = None


def get_container() -> Container:
    global _container
    if _container is None:
        _container = Container()
    return _container


def reset_container() -> None:
    global _container
    if _container:
        _container.close()
    _container = None


# ── entry point del scheduler ──
async def run_scheduled_agent(agent_name: str) -> None:
    try:
        await get_container().run_scheduled(agent_name)
    except (MiniMaxError, DiscordError) as e:
        log.error("scheduled_run_error", agent=agent_name, error=str(e))
    except Exception as e:
        log.exception("scheduled_run_unexpected_error", agent=agent_name, error=str(e))
