"""
Scheduler — wrapper sobre APScheduler que reemplaza el cron de OpenClaw.
Se inicializa en el startup de FastAPI y se apaga en el shutdown.

Los schedules se leen del pack `automiq` (packs/automiq/schedules.json
opcional, o default: leadhunter a las 14:00 ART).
"""
from __future__ import annotations

from typing import Dict, List, Optional

import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from .config import Settings
from .log import get_logger

log = get_logger("scheduler")

# Schedules por defecto para el pack automiq (cron expressions)
DEFAULT_SCHEDULES: Dict[str, str] = {
    "leadhunter": "0 14 * * *",          # diario 14:00 ART
    "content_creator": "0 9 * * 1",      # lunes 09:00 ART
    "social_media": "0 10 * * 1",        # lunes 10:00 ART
    "outbound": "30 14 * * 1",           # lunes 14:30 ART
    "media_auditor": "0 9 * * 1",        # lunes 09:00 ART
    "growth_hacker": "0 16 * * 5",       # viernes 16:00 ART
    "creative_strategist": "0 11 * * 1", # lunes 11:00 ART
    "seo_specialist": "0 8 * * 1",       # lunes 08:00 ART
    "web_auditor": "0 12 * * 1",         # lunes 12:00 ART (auditoría de páginas)
}
DEFAULT_TIMEZONE = "America/Buenos_Aires"


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
        for name, cron in DEFAULT_SCHEDULES.items():
            self._register_agent(name, cron, DEFAULT_TIMEZONE)
        self.scheduler.start()
        log.info("scheduler_started", jobs=self.jobs_registered, tz=self.s.scheduler_timezone)

    def stop(self) -> None:
        if self.scheduler and self.scheduler.running:
            self.scheduler.shutdown(wait=False)
            log.info("scheduler_stopped")

    def _register_agent(self, name: str, cron: str, tzname: str) -> None:
        try:
            trigger = CronTrigger.from_crontab(cron, timezone=pytz.timezone(tzname))
        except Exception as e:
            log.error("agent_schedule_invalid", agent=name, schedule=cron, error=str(e))
            return

        self.scheduler.add_job(
            _scheduled_run,
            trigger=trigger,
            args=[name],
            id=f"agent:{name}",
            name=name,
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=600,
        )
        self.jobs_registered += 1
        log.info("agent_scheduled", agent=name, cron=cron, tz=tzname)

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
