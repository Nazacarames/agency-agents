"""
Scheduler — wrapper sobre APScheduler que reemplaza el cron de OpenClaw.
Se inicializa en el startup de FastAPI y se apaga en el shutdown.
"""
from __future__ import annotations

from typing import Optional

import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from .agents.base import BaseAgent
from .agents.registry import list_agents
from .config import Settings
from .log import get_logger

log = get_logger("scheduler")


class AgentScheduler:
    def __init__(self, settings: Settings):
        self.s = settings
        self.scheduler: Optional[AsyncIOScheduler] = None
        self.jobs_registered = 0

    def start(self) -> None:
        if not self.s.scheduler_enabled:
            log.info("scheduler_disabled")
            return
        if self.s.global_pause:
            log.warning("global_pause_active_scheduler_disabled")
            return

        tz = pytz.timezone(self.s.scheduler_timezone)
        self.scheduler = AsyncIOScheduler(timezone=tz)
        for agent in list_agents():
            self._register_agent(agent)
        self.scheduler.start()
        log.info("scheduler_started", jobs=self.jobs_registered, tz=self.s.scheduler_timezone)

    def stop(self) -> None:
        if self.scheduler and self.scheduler.running:
            self.scheduler.shutdown(wait=False)
            log.info("scheduler_stopped")

    def _register_agent(self, agent: BaseAgent) -> None:
        if not agent.enabled:
            return
        if not agent.schedule:
            return
        try:
            trigger = CronTrigger.from_crontab(agent.schedule, timezone=pytz.timezone(agent.timezone))
        except Exception as e:
            log.error("agent_schedule_invalid", agent=agent.name, schedule=agent.schedule, error=str(e))
            return

        self.scheduler.add_job(
            _scheduled_run,
            trigger=trigger,
            args=[agent.name],
            id=f"agent:{agent.name}",
            name=agent.name,
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=600,  # 10 min de tolerancia
        )
        self.jobs_registered += 1
        log.info("agent_scheduled", agent=agent.name, cron=agent.schedule, tz=agent.timezone)

    def get_jobs_summary(self) -> list[dict]:
        if not self.scheduler:
            return []
        out = []
        for job in self.scheduler.get_jobs():
            out.append({
                "id": job.id,
                "name": job.name,
                "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
            })
        return out


# ── placeholder; la implementación real usa el container DI ──
async def _scheduled_run(agent_name: str) -> None:
    """Entry point del scheduler. Resuelve el agente via el container de la app."""
    from .container import run_scheduled_agent
    await run_scheduled_agent(agent_name)
