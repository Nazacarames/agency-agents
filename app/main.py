"""
FastAPI gateway — punto de entrada HTTP.

Render expone este proceso. Internamente:
- /healthz: estado del servicio + scheduler
- /agents: lista los 8 agentes del pack automiq con schedules
- /run/<name>: dispara un agente vía packs.automiq.get_agent(name).run()
- /last/<name>: devuelve el último MD+JSON de data/
- /webhook/lead: encola enrichment a leadhunter

El scheduler de APScheduler corre los trabajos programados.
"""
from __future__ import annotations

import hmac
import hashlib
import json
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytz
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from . import __version__
from .clients.minimax import MiniMaxClient, MiniMaxError
from .clients.discord import DiscordWebhook, DiscordError
from .config import get_settings
from .container import get_container, reset_container
from .log import configure_logging, get_logger
from .scheduler import AgentScheduler, DEFAULT_SCHEDULES
from packs.automiq import list_agents, get_agent as get_pack_agent
from packs.automiq.tools import ALL_TOOLS
from .agents.registry import get_agent as get_legacy_agent, list_agents as list_legacy_agents

log = get_logger("api")

_scheduler: Optional[AgentScheduler] = None


# ── Lifespan ──

@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    settings = get_settings()
    log.info("app_startup", version=__version__,
             env="production" if settings.is_production else "dev")

    container = get_container()
    log.info("container_health", **container.health())
    log.info("automiq_pack_loaded", agents=list_agents())

    # ── Iniciar scheduler ──
    global _scheduler
    if settings.scheduler_enabled and not settings.global_pause:
        _scheduler = AgentScheduler(settings)
        _scheduler.start()
        log.info("scheduler_started", jobs=len(DEFAULT_SCHEDULES))
    else:
        log.info("scheduler_skipped",
                 enabled=settings.scheduler_enabled,
                 paused=settings.global_pause)

    yield

    if _scheduler:
        _scheduler.stop()
    log.info("app_shutdown")
    reset_container()


from starlette.middleware.base import BaseHTTPMiddleware

app = FastAPI(
    title="Automiq Agency Agents (Hermes-pack)",
    version=__version__,
    description="Render hospeda a Hermes; el equipo de agentes de Automiq vive en packs/automiq/.",
    lifespan=lifespan,
)


class BlockExternalRedirectsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        log.info("incoming_request", path=request.url.path, method=request.method)
        response = await call_next(request)
        if response.status_code in (301, 302, 307, 308):
            loc = response.headers.get("location")
            if loc and not (loc.startswith("https://automiq-agents.onrender.co")
                            or loc.startswith("https://automiq-agents.onrender.com")
                            or loc.startswith("/")):
                log.warning("blocked_external_redirect", location=loc, path=request.url.path)
                return JSONResponse({"error": "blocked external redirect", "location": loc}, status_code=502)
        return response

app.add_middleware(BlockExternalRedirectsMiddleware)


# ── Schemas ──

class HealthResponse(BaseModel):
    status: str
    version: str
    services: Dict[str, Any]


class AgentInfo(BaseModel):
    name: str
    description: str
    schedule: Optional[str] = None
    timezone: str = "America/Buenos_Aires"
    enabled: bool = True


class RunAgentRequest(BaseModel):
    args: Dict[str, Any] = Field(default_factory=dict)
    async_run: bool = True


class RunAgentResponse(BaseModel):
    run_id: str
    agent: str
    status: str
    output: Optional[str] = None


class LeadWebhookPayload(BaseModel):
    name: str
    email: str
    company: Optional[str] = None
    phone: Optional[str] = None
    message: Optional[str] = None
    source: Optional[str] = None
    extra: Optional[Dict[str, Any]] = None


# ── Helpers ──

def _verify_webhook_secret(request: Request) -> None:
    settings = get_settings()
    if not settings.webhook_secret:
        raise HTTPException(status_code=503, detail="WEBHOOK_SECRET no configurado")
    provided = request.headers.get("X-Webhook-Secret", "")
    if not hmac.compare_digest(provided, settings.webhook_secret):
        raise HTTPException(status_code=401, detail="Webhook secret inválido")


class _AgentCtx:
    """Contexto estándar que se pasa a `agent.run(ctx, args)` en el pack automiq."""
    def __init__(self, settings, minimax, discord, run_id, triggered_by, args):
        self.settings = settings
        self.minimax = minimax
        self.discord = discord
        self.run_id = run_id
        self.triggered_by = triggered_by
        self.args = args
        self.tools = dict(ALL_TOOLS)


def _data_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "data"


# ── Endpoints ──

@app.get("/healthz", response_model=HealthResponse)
async def healthz():
    container = get_container()
    svc = container.health()
    svc["scheduler_running"] = bool(_scheduler and _scheduler.scheduler and _scheduler.scheduler.running)
    svc["scheduled_jobs"] = len(DEFAULT_SCHEDULES)
    if _scheduler:
        svc["next_runs"] = _scheduler.get_jobs_summary()
    return HealthResponse(
        status="ok",
        version=__version__,
        services=svc,
    )


@app.get("/agents", response_model=List[AgentInfo])
async def list_agents_endpoint():
    descriptions = {
        "leadhunter": "Genera 10 leads/día con contacto verificado (FIT 4-6)",
        "content_creator": "Posts LinkedIn, blog, email para Automiq",
        "growth_hacker": "Hipótesis de growth + plan experimental",
        "creative_strategist": "Ángulo, hooks, mensaje clave, CTA",
        "social_media": "Calendario semanal de redes",
        "outbound": "Secuencias cold outreach multi-canal",
        "media_auditor": "CTR / CPL / ROAS por canal + recomendaciones",
        "seo_specialist": "Keyword research + quick wins on-page",
    }
    return [
        AgentInfo(
            name=n,
            description=descriptions.get(n, ""),
            schedule=DEFAULT_SCHEDULES.get(n),
            timezone="America/Buenos_Aires",
            enabled=True,
        )
        for n in list_agents()
    ]


@app.get("/agents/{name}", response_model=AgentInfo)
async def get_agent_endpoint(name: str):
    if name not in list_agents():
        raise HTTPException(status_code=404, detail=f"agent {name} not in pack automiq")
    return AgentInfo(
        name=name,
        description="",
        schedule=DEFAULT_SCHEDULES.get(name),
        timezone="America/Buenos_Aires",
        enabled=True,
    )


@app.post("/run/{name}", response_model=RunAgentResponse)
async def run_agent_endpoint(name: str, body: RunAgentRequest,
                             request: Request, background: BackgroundTasks):
    _verify_webhook_secret(request)
    if name not in list_agents():
        raise HTTPException(status_code=404, detail=f"agent {name} not in pack automiq")

    if body.async_run:
        run_id = str(uuid.uuid4())
        background.add_task(_run_pack_agent, name, body.args, run_id, "manual")
        return RunAgentResponse(run_id=run_id, agent=name, status="queued")

    # Sync
    try:
        output = await _run_pack_agent(name, body.args, None, "manual")
        return RunAgentResponse(
            run_id="sync", agent=name, status="ok",
            output=output[:4000] if output else None,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


async def _run_pack_agent(name: str, args: Dict[str, Any], run_id: Optional[str], triggered_by: str) -> str:
    """
    Ejecuta un agente del pack automiq.

    Usa la implementación LEGACY (app/agents/<name>.py) que tiene la lógica
    real de generación de leads/POST/social, NO los stubs del pack.
    """
    import asyncio
    container = get_container()
    run_id = run_id or str(uuid.uuid4())
    
    # Usar la implementación legacy del container (app/agents/leadhunter.py real)
    try:
        result = await container.run_agent(name, triggered_by=triggered_by, args=args, run_id=run_id)
        log.info("agent_completed", agent=name, run_id=run_id, triggered_by=triggered_by,
                 output_len=len(str(result)))
        return result
    except Exception as e:
        log.error("agent_failed", agent=name, run_id=run_id, error=str(e))
        raise


@app.post("/webhook/lead", status_code=status.HTTP_202_ACCEPTED)
async def lead_webhook(payload: LeadWebhookPayload, request: Request,
                       background: BackgroundTasks):
    _verify_webhook_secret(request)
    container = get_container()
    log.info("lead_received", name=payload.name, email=payload.email,
             company=payload.company, source=payload.source)
    if container.discord:
        try:
            container.discord.send("", embed=None)
        except Exception:
            pass
    run_id = str(uuid.uuid4())
    enrichment_args = {
        "vertical": payload.extra.get("vertical", "general") if payload.extra else "general",
        "single_lead_enrichment": {
            "name": payload.name,
            "email": payload.email,
            "company": payload.company,
            "phone": payload.phone,
            "message": payload.message,
        },
    }
    background.add_task(_run_pack_agent, "leadhunter", enrichment_args, run_id, "webhook:lead")
    return {"status": "queued", "run_id": run_id, "agent": "leadhunter"}


# ── Last output (manual pull del MD+JSON a PC) ──

@app.get("/last/{name}")
async def last_agent_output(name: str, request: Request):
    _verify_webhook_secret(request)
    if name not in list_agents():
        raise HTTPException(status_code=404, detail=f"agent {name} not in pack automiq")
    today = datetime.now(pytz.timezone("America/Buenos_Aires")).strftime("%Y-%m-%d")
    data_dir = _data_dir()

    patterns = {
        "leadhunter": ("leadhunter-report-{d}.md", None, "leadhunter-leads-{d}.json"),
        "content_creator": ("content-creator-report-{d}.md", None, "content-creator-report-{d}.json"),
        "growth_hacker": ("growth-hacker-report-{d}.md", None, "growth-hacker-report-{d}.json"),
        "creative_strategist": ("creative-strategist-report-{d}.md", None, "creative-strategist-report-{d}.json"),
        "social_media": ("social-media-report-{d}.md", None, "social-media-report-{d}.json"),
        "outbound": ("outbound-report-{d}.md", None, "outbound-report-{d}.json"),
        "media_auditor": ("media-auditor-report-{d}.md", None, "media-auditor-report-{d}.json"),
        "seo_specialist": ("seo-specialist-report-{d}.md", None, "seo-specialist-report-{d}.json"),
    }
    md_tpl, leads_tpl, json_tpl = patterns[name]

    md_path = data_dir / md_tpl.format(d=today)
    if not md_path.exists():
        cands = sorted(data_dir.glob(md_tpl.format(d="*")), reverse=True)
        if not cands:
            return JSONResponse({"status": "not_found", "message": "no reports yet", "date": today}, status_code=404)
        md_path = cands[0]
        # Extraer date del filename
        parts = md_path.stem.split("-")
        # leadhunter-report-2026-06-09 → ["leadhunter","report","2026","06","09"]
        date_cands = [p for p in parts if "-".join(parts[parts.index(p):]).count("-") >= 2]
        if date_cands:
            idx = parts.index(date_cands[0])
            today = "-".join(parts[idx:idx+3])
        md_path = data_dir / md_tpl.format(d=today)
    json_path = data_dir / json_tpl.format(d=today) if json_tpl else None
    leads_path = data_dir / leads_tpl.format(d=today) if leads_tpl else None

    def _read(p):
        try:
            return p.read_text(encoding="utf-8")
        except Exception:
            return None

    def _size(p):
        try:
            return p.stat().st_size
        except Exception:
            return 0

    return {
        "status": "ok",
        "agent": name,
        "date": today,
        "files": {
            "report_md": _read(md_path),
            "leads_md": _read(leads_path) if leads_path else None,
            "leads_json": _read(json_path) if json_path else None,
        },
        "sizes": {
            "report_md": _size(md_path),
            "leads_md": _size(leads_path) if leads_path else 0,
            "leads_json": _size(json_path) if json_path else 0,
        },
    }


@app.get("/")
async def root():
    return {
        "service": "automiq-agents",
        "version": __version__,
        "runtime": "hermes-pack",
        "agents": "/agents",
        "last": "/last/{agent}",
        "health": "/healthz",
    }