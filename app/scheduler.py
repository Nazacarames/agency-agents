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

# Schedules por defecto para el pack automiq (cron expressions).
#
# ESPACIADO (2026-06-12): cada run de Claude Code es PESADO en cuota MiniMax
# (un run grande deja a TODOS los agentes en 429 hasta el reset de la ventana).
# Por eso NO se corren varios el mismo día/hora. Regla: máx 1 agente CC por
# franja, separados ≥4h, y respetando el orden de SINERGIA del pipeline:
#   leadhunter → web_auditor → (outbound + creative_strategist).
# El inbox_assistant NO usa Claude Code (texto puro, liviano) → puede ser diario.
# TODOS LOS AGENTES, TODOS LOS DÍAS (pedido del usuario 2026-06-13).
# Espaciados POR HORA dentro del día para no dispararse todos juntos (y darle aire
# a la ventana de cuota MiniMax), respetando el ORDEN de la sinergia:
#   leadhunter (08) → web_auditor (10) → outbound (12) + creative_strategist (13).
# ⚠️ Cada run CC consume cuota: 9 agentes CC/día es quota-pesado (leadhunter 10 leads
#    solo ≈ USD 17/run). Si la ventana se agota, los últimos del día pueden dar 429.
# ⚠️ Día de semana SIEMPRE por nombre (mon..sat), nunca por número: from_crontab
#    interpreta el número como 0=lunes y desfasa +1 día. Acá usamos '* * *' (diario).
DEFAULT_SCHEDULES: Dict[str, str] = {
    "leadhunter": "0 8 * * *",            # 08:00 — prospección (10 leads), ancla del pipeline
    "inbox_assistant": "0 9 * * *",       # 09:00 — lee bandeja, redacta borradores (liviano)
    "web_auditor": "0 10 * * *",          # 10:00 — audita prospecto → dolores
    "outbound": "0 12 * * *",             # 12:00 — cold-email usando los dolores
    "creative_strategist": "0 13 * * *",  # 13:00 — ads usando los dolores
    "content_creator": "0 14 * * *",      # 14:00 — contenido
    "social_media": "0 15 * * *",         # 15:00 — calendario orgánico
    "seo_specialist": "0 16 * * *",       # 16:00 — auditoría SEO
    "media_auditor": "0 17 * * *",        # 17:00 — auditoría de ads
    "growth_hacker": "0 18 * * *",        # 18:00 — growth / funnel
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
