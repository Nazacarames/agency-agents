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
    "outbound": "0 12 * * mon-fri",       # 12:00 hábiles — cold-email (finde no: rinde peor)
    "creative_strategist": "0 13 * * *",  # 13:00 — ads usando los dolores
    "content_creator": "0 14 * * *",      # 14:00 — contenido
    "tiktok_creator": "0 19 * * mon,wed,fri",  # lun/mié/vie 19:00 — guiones TikTok (Nazareno)
    "social_media": "0 15 * * *",         # 15:00 — calendario orgánico
    "seo_specialist": "0 16 * * *",       # 16:00 — auditoría SEO
    "media_auditor": "0 17 * * *",        # 17:00 — auditoría de ads
    "growth_hacker": "0 18 * * *",        # 18:00 — growth / funnel
    "web_optimizer": "0 20 1,15 * *",     # días 1 y 15, 20:00 — ciclo SEO/GEO quincenal con datos de Search Console.
                                          # Quincenal (no semanal) a propósito: el SEO tarda semanas en moverse y una
                                          # iteración semanal mide ruido. Día-del-mes evita llevar estado para saber
                                          # si "toca esta semana" (un contador se desincroniza si una corrida falla).
    "chief_of_staff": "0 21 * * *",       # 21:00 todos los días — CIERRE del día: qué pasó, quién no entregó,
                                          # y el plan de acción para mañana. A las 08:30 corría ANTES que todo
                                          # el equipo (que trabaja de 08 a 20), así que planificaba a ciegas.
}
DEFAULT_TIMEZONE = "America/Buenos_Aires"

# Drenado de la cola de publicaciones: 1 sola publicación por día (regla del usuario).
# Corre a las 11:00 ART, después de que los agentes de contenido del día anterior
# hayan encolado. drain_one() se autolimita a 1/día aunque el job dispare de más.
PUBLISH_DRAIN_CRON = "0 11 * * *"

# Snapshot diario de métricas (MRR, clientes, leads, ganancia) para la línea de
# crecimiento del panel. 06:00 ART.
METRICS_SNAPSHOT_CRON = "0 6 * * *"

# Auto-archivado de prospectos fríos (>N días sin movimiento). 05:00 ART.
CLIENT_ARCHIVE_CRON = "0 5 * * *"

# Digest de aprendizaje: consolida qué rubros convierten (lecciones data-driven para
# leadhunter/outbound). Semanal, domingo 07:00 ART. Determinístico, sin costo de cuota.
LEARNING_DIGEST_CRON = "0 7 * * sun"
COMPETITOR_REFRESH_CRON = "0 8 * * sun"   # dom 08:00 — refresca el playbook de competencia
SCOUT_REFRESH_CRON = "0 9 * * sun"        # dom 09:00 — visual scout IG (Gemini mira reels reales)
TREND_RADAR_CRON = "45 6 * * *"           # diario 06:45 — radar de tendencias; digest ~7 AM
CREATIVE_STUDY_CRON = "0 10 1 * *"        # día 1 de cada mes 10:00 — re-estudia formatos de creativos
HOUSEKEEPING_CRON = "30 4 * * *"          # diario 04:30 — retención del volumen (data/images + reportes viejos)
ROUNDTABLE_CRON = "30 7 * * mon"          # lun 07:30 — mesa redonda del equipo (debate); el brief de 08:30 la lee
PRACTICE_RESEARCH_CRON = "0 7 1,15 * *"   # día 1 y 15, 07:00 — research web de mejores prácticas → lecciones
DRIVE_SYNC_CRON = "0 5 * * *"             # diario 05:00 — contenido/reportes/backup de stores a Google Drive
COMMENT_WATCH_CRON = "15 */2 * * *"       # cada 2h — comentarios nuevos en nuestros posts (comment-gate → Discord)
REEL_STUDY_CRON = "30 6 * * mon"          # lun 06:30 — Gemini mira reels del competidor → prompts/lecciones


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
        self._register_publisher(PUBLISH_DRAIN_CRON, DEFAULT_TIMEZONE)
        self._register_simple("metrics:snapshot", METRICS_SNAPSHOT_CRON, DEFAULT_TIMEZONE,
                              _scheduled_metrics_snapshot)
        self._register_simple("clients:archive", CLIENT_ARCHIVE_CRON, DEFAULT_TIMEZONE,
                              _scheduled_client_archive)
        self._register_simple("learning:digest", LEARNING_DIGEST_CRON, DEFAULT_TIMEZONE,
                              _scheduled_learning_digest)
        self._register_simple("competitor:refresh", COMPETITOR_REFRESH_CRON, DEFAULT_TIMEZONE,
                              _scheduled_competitor_refresh)
        self._register_simple("scout:refresh", SCOUT_REFRESH_CRON, DEFAULT_TIMEZONE,
                              _scheduled_scout_refresh)
        self._register_simple("trends:radar", TREND_RADAR_CRON, DEFAULT_TIMEZONE,
                              _scheduled_trend_radar)
        self._register_simple("creative:study", CREATIVE_STUDY_CRON, DEFAULT_TIMEZONE,
                              _scheduled_creative_study)
        self._register_simple("housekeeping", HOUSEKEEPING_CRON, DEFAULT_TIMEZONE,
                              _scheduled_housekeeping)
        self._register_simple("roundtable", ROUNDTABLE_CRON, DEFAULT_TIMEZONE,
                              _scheduled_roundtable)
        self._register_simple("practice:research", PRACTICE_RESEARCH_CRON, DEFAULT_TIMEZONE,
                              _scheduled_practice_research)
        self._register_simple("drive:sync", DRIVE_SYNC_CRON, DEFAULT_TIMEZONE,
                              _scheduled_drive_sync)
        self._register_simple("comments:watch", COMMENT_WATCH_CRON, DEFAULT_TIMEZONE,
                              _scheduled_comment_watch)
        self._register_simple("reels:study", REEL_STUDY_CRON, DEFAULT_TIMEZONE,
                              _scheduled_reel_study)
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

    def _register_publisher(self, cron: str, tzname: str) -> None:
        try:
            trigger = CronTrigger.from_crontab(cron, timezone=pytz.timezone(tzname))
        except Exception as e:
            log.error("publisher_schedule_invalid", schedule=cron, error=str(e))
            return
        self.scheduler.add_job(
            _scheduled_publish_drain,
            trigger=trigger,
            id="publish:drain",
            name="publish_queue_drain",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=3600,
        )
        self.jobs_registered += 1
        log.info("publisher_scheduled", cron=cron, tz=tzname)

    def _register_simple(self, job_id: str, cron: str, tzname: str, func) -> None:
        try:
            trigger = CronTrigger.from_crontab(cron, timezone=pytz.timezone(tzname))
        except Exception as e:
            log.error("job_schedule_invalid", job=job_id, schedule=cron, error=str(e))
            return
        self.scheduler.add_job(
            func, trigger=trigger, id=job_id, name=job_id,
            replace_existing=True, max_instances=1, coalesce=True, misfire_grace_time=3600,
        )
        self.jobs_registered += 1
        log.info("job_scheduled", job=job_id, cron=cron, tz=tzname)

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


async def _scheduled_publish_drain() -> None:
    """Publica como mucho 1 pieza pendiente por día. Corre el publish SÍNCRONO en un
    thread para no bloquear el event loop (la Graph API hace self-fetch de /media)."""
    import asyncio
    from .integrations import publish_queue as pq
    try:
        res = await asyncio.to_thread(pq.drain_one)
        log.info("publish_drain_done", result=res)
    except Exception as e:
        log.error("publish_drain_failed", error=str(e)[:200])


async def _scheduled_metrics_snapshot() -> None:
    """Snapshot diario de métricas para la línea de crecimiento del panel."""
    import asyncio
    from .integrations import metrics_store as ms
    try:
        pt = await asyncio.to_thread(ms.snapshot)
        log.info("metrics_snapshot_done", point=pt)
    except Exception as e:
        log.error("metrics_snapshot_failed", error=str(e)[:200])


async def _scheduled_client_archive() -> None:
    """Archiva prospectos fríos (>N días sin movimiento) para liberar memoria."""
    import asyncio
    from .integrations import clients_store as cs
    from .config import get_settings
    try:
        days = get_settings().client_archive_days
        res = await asyncio.to_thread(cs.auto_archive, days)
        log.info("client_archive_done", result=res)
    except Exception as e:
        log.error("client_archive_failed", error=str(e)[:200])


async def _scheduled_learning_digest() -> None:
    """Consolida lecciones data-driven (rubros que convierten) para los agentes."""
    import asyncio
    from .integrations import learning
    try:
        res = await asyncio.to_thread(learning.digest)
        log.info("learning_digest_scheduled_done", result=res)
    except Exception as e:
        log.error("learning_digest_failed", error=str(e)[:200])


async def _scheduled_competitor_refresh() -> None:
    """Refresca el playbook de competencia + el bloque de tendencias (estudio constante)."""
    import asyncio
    from .integrations import competitor_study, trends
    try:
        res = await asyncio.to_thread(competitor_study.refresh)
        log.info("competitor_refresh_scheduled_done", result=res)
    except Exception as e:
        log.error("competitor_refresh_failed", error=str(e)[:200])
    try:
        tr = await asyncio.to_thread(trends.refresh)
        log.info("trends_refresh_scheduled_done", result=tr)
    except Exception as e:
        log.error("trends_refresh_failed", error=str(e)[:200])


async def _scheduled_scout_refresh() -> None:
    """Aprendizaje constante: el visual scout mira reels reales de IG (Gemini) y refresca
    el playbook de edición/hooks. Autónomo en el server (Business Discovery + Gemini no se
    bloquean por IP). Best-effort."""
    import asyncio
    from .integrations import content_scout
    try:
        res = await asyncio.to_thread(content_scout.refresh)
        log.info("scout_refresh_scheduled_done", result=res)
    except Exception as e:
        log.error("scout_refresh_failed", error=str(e)[:200])


async def _scheduled_creative_study() -> None:
    """Re-estudio mensual de formatos de creativos: reescribe la dirección de arte
    que se inyecta a los agentes de contenido. Best-effort."""
    import asyncio
    from .integrations import creative_direction
    try:
        res = await asyncio.to_thread(creative_direction.refresh)
        log.info("creative_study_scheduled_done", result=res)
    except Exception as e:
        log.error("creative_study_failed", error=str(e)[:200])


async def _scheduled_practice_research() -> None:
    """Research web quincenal de mejores prácticas → lecciones inyectadas a los agentes."""
    import asyncio
    from .integrations import practice_research
    try:
        res = await asyncio.to_thread(practice_research.refresh)
        log.info("practice_research_scheduled_done", result=res)
    except Exception as e:
        log.error("practice_research_scheduled_failed", error=str(e)[:200])


async def _scheduled_roundtable() -> None:
    """Mesa redonda semanal: los agentes debaten y lo acordado se reparte como
    notas/lecciones que cada uno recibe en su próxima corrida."""
    import asyncio
    from .integrations import roundtable
    try:
        res = await asyncio.to_thread(roundtable.run_roundtable)
        log.info("roundtable_scheduled_done", result=res)
    except Exception as e:
        log.error("roundtable_scheduled_failed", error=str(e)[:200])


async def _scheduled_housekeeping() -> None:
    """Retención del volumen: borra media vieja no pendiente y reportes antiguos."""
    import asyncio
    from .integrations import housekeeping
    try:
        res = await asyncio.to_thread(housekeeping.cleanup)
        log.info("housekeeping_scheduled_done", result=res)
    except Exception as e:
        log.error("housekeeping_failed", error=str(e)[:200])


async def _scheduled_reel_study() -> None:
    """Gemini mira los reels top no estudiados del competidor → prompts/lecciones."""
    import asyncio
    from .integrations import reel_study
    try:
        res = await asyncio.to_thread(reel_study.study, 2)
        log.info("reel_study_scheduled_done", result=res)
    except Exception as e:
        log.error("reel_study_failed", error=str(e)[:200])


async def _scheduled_drive_sync() -> None:
    """Sube a Drive el contenido/reportes nuevos + backup diario de los stores."""
    import asyncio
    from .integrations import drive_sync
    try:
        res = await asyncio.to_thread(drive_sync.sync)
        log.info("drive_sync_scheduled_done", result=res)
    except Exception as e:
        log.error("drive_sync_failed", error=str(e)[:200])


async def _scheduled_comment_watch() -> None:
    """Comentarios nuevos en nuestros posts de IG → Discord (comment-gate = leads)."""
    import asyncio
    from .integrations import comment_watch
    try:
        res = await asyncio.to_thread(comment_watch.check)
        log.info("comment_watch_scheduled_done", result=res)
    except Exception as e:
        log.error("comment_watch_failed", error=str(e)[:200])


async def _scheduled_trend_radar() -> None:
    """Radar de tendencias diario: revisa las fuentes, etiqueta (gancho/explicativo/
    ignorar) y manda el top 5 por Discord (~7 AM). Best-effort."""
    import asyncio
    from .integrations import trend_radar
    try:
        res = await asyncio.to_thread(trend_radar.refresh)
        if res.get("ok"):
            await asyncio.to_thread(trend_radar.send_digest)
        log.info("trend_radar_scheduled_done", result=res)
    except Exception as e:
        log.error("trend_radar_failed", error=str(e)[:200])
