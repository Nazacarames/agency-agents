"""
FastAPI app — expone endpoints para:
- Healthcheck (Render)
- Listado de agentes y schedules
- Trigger manual de un agente (vía webhook con secret)
- Webhook genérico para integraciones externas (formularios, etc.)

Toda la app se inicializa con un lifespan async.
"""
from __future__ import annotations

import hmac
import hashlib
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from . import __version__
from .agents.registry import get_agent, list_agents
from .config import get_settings
from .container import get_container, reset_container
from .log import configure_logging, get_logger
from .scheduler import AgentScheduler

log = get_logger("api")


# ── Lifespan ──

@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    settings = get_settings()
    log.info("app_startup", version=__version__, env="production" if settings.is_production else "dev")

    container = get_container()
    log.info("container_health", **container.health())

    scheduler = AgentScheduler(settings)
    scheduler.start()
    app.state.scheduler = scheduler
    app.state.container = container

    try:
        yield
    finally:
        log.info("app_shutdown")
        scheduler.stop()
        reset_container()


app = FastAPI(
    title="Automiq Agency Agents",
    version=__version__,
    description="Wrapper Hermes-style con MiniMax-M3 para los agentes de Automiq",
    lifespan=lifespan,
)


# ── Schemas ──

class HealthResponse(BaseModel):
    status: str
    version: str
    services: Dict[str, Any]


class AgentInfo(BaseModel):
    name: str
    description: str
    schedule: Optional[str]
    timezone: str
    enabled: bool


class RunAgentRequest(BaseModel):
    args: Dict[str, Any] = Field(default_factory=dict)
    async_run: bool = True


class RunAgentResponse(BaseModel):
    run_id: str
    agent: str
    status: str
    output: Optional[str] = None


class LeadWebhookPayload(BaseModel):
    """Payload típico de un form de lead (Typeform, Tally, landing propia, etc.)."""
    name: str
    email: str
    company: Optional[str] = None
    phone: Optional[str] = None
    message: Optional[str] = None
    source: Optional[str] = None
    extra: Optional[Dict[str, Any]] = None


# ── Helpers ──

def _verify_webhook_secret(request: Request) -> None:
    """Verifica el header X-Webhook-Secret contra el SECRET configurado."""
    settings = get_settings()
    if not settings.webhook_secret:
        # Si no hay secret configurado, no aceptar webhooks
        raise HTTPException(status_code=503, detail="WEBHOOK_SECRET no configurado")
    provided = request.headers.get("X-Webhook-Secret", "")
    if not hmac.compare_digest(provided, settings.webhook_secret):
        raise HTTPException(status_code=401, detail="Webhook secret inválido")


# ── Endpoints ──

@app.get("/healthz", response_model=HealthResponse)
async def healthz():
    container = get_container()
    return HealthResponse(
        status="ok",
        version=__version__,
        services=container.health(),
    )


@app.get("/agents", response_model=List[AgentInfo])
async def list_agents_endpoint():
    return [
        AgentInfo(
            name=a.name,
            description=a.description,
            schedule=a.schedule,
            timezone=a.timezone,
            enabled=a.enabled,
        )
        for a in list_agents()
    ]


@app.get("/agents/{name}", response_model=AgentInfo)
async def get_agent_endpoint(name: str):
    try:
        a = get_agent(name)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return AgentInfo(
        name=a.name,
        description=a.description,
        schedule=a.schedule,
        timezone=a.timezone,
        enabled=a.enabled,
    )


@app.get("/scheduler/jobs")
async def scheduler_jobs(request: Request):
    scheduler: AgentScheduler = request.app.state.scheduler
    return {"jobs": scheduler.get_jobs_summary()}


@app.post("/run/{name}", response_model=RunAgentResponse)
async def run_agent_endpoint(
    name: str,
    body: RunAgentRequest,
    request: Request,
    background: BackgroundTasks,
):
    """Dispara un agente manualmente. Soporta async (devuelve run_id) o sync (espera output)."""
    _verify_webhook_secret(request)
    try:
        get_agent(name)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))

    container = get_container()

    if body.async_run:
        # Disparar y olvidar (útil para webhooks que no pueden esperar)
        import uuid
        run_id = str(uuid.uuid4())
        background.add_task(container.run_agent, name, triggered_by="manual", args=body.args, run_id=run_id)
        return RunAgentResponse(run_id=run_id, agent=name, status="queued")

    # Sync: esperar resultado
    try:
        output = await container.run_agent(name, triggered_by="manual", args=body.args)
        return RunAgentResponse(
            run_id="sync",
            agent=name,
            status="ok",
            output=output[:4000] if output else None,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/webhook/lead", status_code=status.HTTP_202_ACCEPTED)
async def lead_webhook(
    payload: LeadWebhookPayload,
    request: Request,
    background: BackgroundTasks,
):
    """Webhook genérico para nuevos leads (form de la landing, Typeform, etc.).
    Toma el lead, dispara una versión 'on-demand' de LeadHunter para enriquecerlo
    y notifica a Discord."""
    _verify_webhook_secret(request)
    container = get_container()

    # Log del lead entrante
    log.info("lead_received",
             name=payload.name, email=payload.email, company=payload.company, source=payload.source)

    # Notificación inmediata a Discord
    if container.discord:
        from .clients.discord import DiscordEmbed
        embed = DiscordEmbed(
            title=f"📥 Nuevo lead: {payload.name}",
            description=(
                f"**Empresa:** {payload.company or 'N/D'}\n"
                f"**Email:** {payload.email}\n"
                f"**Teléfono:** {payload.phone or 'N/D'}\n"
                f"**Mensaje:** {(payload.message or '')[:500]}\n"
                f"**Source:** {payload.source or 'N/D'}"
            ),
            color=0xF39C12,  # naranja
            footer="Automiq Lead Intake",
        )
        try:
            container.discord.send("", embed=embed)
        except Exception as e:
            log.error("lead_discord_notify_failed", error=str(e))

    # Encolar enrichment vía LeadHunter en background
    import uuid
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
    background.add_task(container.run_agent, "leadhunter", triggered_by="webhook:lead", args=enrichment_args, run_id=run_id)

    return {"status": "queued", "run_id": run_id, "agent": "leadhunter"}


@app.get("/")
async def root():
    return {
        "service": "automiq-agents",
        "version": __version__,
        "docs": "/docs",
        "health": "/healthz",
        "agents": "/agents",
    }
