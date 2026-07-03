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
import re
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytz
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse, HTMLResponse, FileResponse, RedirectResponse, PlainTextResponse
from starlette.concurrency import run_in_threadpool
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
            own_base = (get_settings().public_base_url or "").rstrip("/")
            if loc and not (loc.startswith("/")
                            or (own_base and loc.startswith(own_base))
                            or loc.startswith("https://www.tiktok.com/")):  # OAuth de TikTok (Login Kit)
                log.warning("blocked_external_redirect", location=loc, path=request.url.path)
                return JSONResponse({"error": "blocked external redirect", "location": loc}, status_code=502)
        return response

app.add_middleware(BlockExternalRedirectsMiddleware)

# CORS: solo para que la landing (automiq.agency / previews de Vercel) pueda
# hablar con el agente demo público. El resto de la API usa el webhook secret.
from starlette.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://automiq.agency", "https://www.automiq.agency"],
    allow_origin_regex=r"https://automiq-landing-astro-[a-z0-9]+-nazacarames-projects\.vercel\.app",
    allow_methods=["POST", "GET", "OPTIONS"],
    allow_headers=["content-type"],
)


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


class PurgeRequest(BaseModel):
    dry_run: bool = True            # SEGURO por defecto: sólo previsualiza
    reset: bool = False             # vacía todo el store
    keys: List[str] = Field(default_factory=list)
    states: List[str] = Field(default_factory=list)
    channels: List[str] = Field(default_factory=list)
    email_contains: List[str] = Field(default_factory=list)
    untouched_only: bool = False


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


# Endpoint ultra-liviano para health checks de Render.
# Devuelve 200 sin tocar DB, scheduler ni Hermes. Lo configuramos como
# healthCheckPath en Render para que el container NO sea matado mientras
# la app está arrancando (playwright load + hermes-agent tardan 30-60s).
@app.get("/_ready")
async def ready():
    return {"status": "ok", "version": __version__}


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
        "web_auditor": "Auditoría de páginas web (contenido/CRO/SEO) puntuada",
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
            output=output if output else None,
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
    log.info("lead_received", name=payload.name, email=payload.email,
             company=payload.company, source=payload.source)
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
        "web_auditor": ("web-auditor-report-{d}.md", None, "web-auditor-report-{d}.json"),
        "inbox_assistant": ("inbox-assistant-report-{d}.md", None, None),
        "meeting_prep": ("meeting-prep-report-{d}.md", None, None),
    }
    # Default robusto para agentes sin patrón explícito (post_process genérico
    # guarda en data/<name-con-guiones>-report-<fecha>.md). Evita el KeyError/500.
    default_tpl = (f"{name.replace('_', '-')}-report-{{d}}.md", None, None)
    md_tpl, leads_tpl, json_tpl = patterns.get(name, default_tpl)

    md_path = data_dir / md_tpl.format(d=today)
    if not md_path.exists():
        cands = sorted(data_dir.glob(md_tpl.format(d="*")), reverse=True)
        if not cands:
            return JSONResponse({"status": "not_found", "message": "no reports yet", "date": today}, status_code=404)
        md_path = cands[0]
        # Derivar la fecha YYYY-MM-DD del filename con regex (robusto; no asume el
        # orden de los campos). El bug viejo tomaba siempre parts[0] → armaba rutas
        # como "leadhunter-report-leadhunter-report-2026.md" y devolvía vacío cuando
        # no existía el archivo de HOY (p.ej. tras el cambio de día a medianoche).
        m = re.search(r"(\d{4}-\d{2}-\d{2})", md_path.stem)
        if m:
            today = m.group(1)
        # md_path ya apunta al archivo real (cands[0]); NO re-derivar desde `today`.
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


@app.get("/admin/leads")
async def admin_leads_list(request: Request):
    """Vista del leads-store: conteo por estado + lista compacta de cada lead.
    Para inspeccionar el pipeline y decidir qué purgar."""
    _verify_webhook_secret(request)
    from .integrations import leads_store as ls
    store = ls.load_store()
    leads = [ls.lead_view(l) for l in store.get("leads", {}).values()]
    # ordenar por estado y luego empresa, para lectura
    leads.sort(key=lambda l: (str(l.get("state")), str(l.get("company"))))
    return {
        "status": "ok",
        "counts": ls.summary_counts(store),
        "updated_at": store.get("updated_at"),
        "leads": leads,
    }


@app.post("/admin/leads/purge")
async def admin_leads_purge(body: PurgeRequest, request: Request):
    """Purga leads del store. SEGURO POR DEFECTO: con dry_run=true (default) sólo
    PREVISUALIZA qué borraría, sin tocar nada. Pasá dry_run=false para ejecutar.

    Opciones (se combinan con AND, salvo `keys` que se incluyen siempre):
      - reset: true            → vacía TODO el store (ignora el resto).
      - keys: [...]            → keys exactas a borrar.
      - states: [...]          → p.ej. ["nuevo"]
      - channels: [...]        → p.ej. ["email"]
      - email_contains: [...]  → substrings de email, p.ej. ["fate.com","coto.com"]
      - untouched_only: true   → sólo leads sin ningún toque enviado.
    """
    _verify_webhook_secret(request)
    from .integrations import leads_store as ls

    if body.reset:
        if body.dry_run:
            store = ls.load_store()
            return {"status": "dry_run", "would_reset": True,
                    "current_count": ls.summary_counts(store).get("total", 0)}
        ls.reset_store()
        return {"status": "ok", "reset": True, "remaining": 0}

    store = ls.load_store()
    matched = ls.match_keys(
        store,
        keys=body.keys or None,
        states=body.states or None,
        channels=body.channels or None,
        email_contains=body.email_contains or None,
        untouched_only=body.untouched_only,
    )
    preview = [ls.lead_view(store["leads"][k]) for k in matched]
    if body.dry_run:
        return {"status": "dry_run", "would_remove": len(matched), "leads": preview}
    removed = ls.remove_keys(store, matched)
    ls.save_store(store)
    log.info("admin_leads_purged", removed=removed)
    return {"status": "ok", "removed": removed,
            "remaining": ls.summary_counts(store).get("total", 0), "leads": preview}


# ══════════════════════════════════════════════════════════════════════════
# Dashboard operativo de la agencia (UI interna)
# Auth: el mismo X-Webhook-Secret (el "login" sólo valida y el front lo guarda).
# ══════════════════════════════════════════════════════════════════════════

class LoginBody(BaseModel):
    secret: str = ""


class ClientBody(BaseModel):
    name: Optional[str] = None
    vertical: Optional[str] = None
    country: Optional[str] = None
    contact_name: Optional[str] = None
    contact_phone: Optional[str] = None
    contact_email: Optional[str] = None
    stage: Optional[str] = None
    notes: Optional[str] = None
    currency: Optional[str] = None
    monthly_fee: Optional[float] = None
    services: Optional[str] = None
    status: Optional[str] = None
    start_date: Optional[str] = None


class ExpenseBody(BaseModel):
    category: Optional[str] = "otros"
    label: Optional[str] = ""
    amount: float = 0
    currency: Optional[str] = "USD"
    date: Optional[str] = None
    recurring: Optional[bool] = False


class FxBody(BaseModel):
    rates: Dict[str, float]


class LeadBody(BaseModel):
    company: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    channel: Optional[str] = None
    state: Optional[str] = None
    next_step: Optional[int] = None


class LessonEditBody(BaseModel):
    lesson: str


class AdBody(BaseModel):
    name: Optional[str] = None
    client_id: Optional[str] = None
    client_name: Optional[str] = None
    platform: Optional[str] = "Meta"
    objective: Optional[str] = ""
    status: Optional[str] = "activa"
    currency: Optional[str] = "USD"
    budget: Optional[float] = 0
    spend: Optional[float] = 0
    results: Optional[float] = 0
    revenue: Optional[float] = 0
    start_date: Optional[str] = None
    notes: Optional[str] = ""


class TaskBody(BaseModel):
    agent: str
    prompt: str
    client_id: Optional[str] = None     # si la tarea apunta a un cliente, su memoria se inyecta


class MemoryBody(BaseModel):
    section: Optional[str] = "general"
    title: str
    content: str
    source: Optional[str] = ""
    tags: Optional[List[str]] = None


class GrowthBody(BaseModel):
    sector: Optional[str] = "general"
    objective: Optional[str] = None
    metric: Optional[str] = ""
    target: Optional[str] = ""
    status: Optional[str] = "activo"
    notes: Optional[str] = ""


class LessonBody(BaseModel):
    agent: str
    lesson: str
    kind: Optional[str] = "feedback"
    weight: Optional[int] = 1


class ClientMemoryBody(BaseModel):
    kind: Optional[str] = "note"
    agent: Optional[str] = ""
    title: Optional[str] = ""
    content: str
    meta: Optional[Dict[str, Any]] = None


class MeetingBody(BaseModel):
    client_id: Optional[str] = None
    client_name: Optional[str] = ""
    title: Optional[str] = "Reunión"
    scheduled_at: Optional[str] = None      # ISO datetime (cliente + día + hora)
    location: Optional[str] = ""
    notes: Optional[str] = ""
    status: Optional[str] = None


class CalendarEventBody(BaseModel):
    title: Optional[str] = "Reunión"
    start_iso: Optional[str] = None         # ISO-8601 con offset ART (-03:00)
    duration_min: Optional[int] = 30
    attendee_email: Optional[str] = ""
    create_meet: Optional[bool] = True      # crea Google Meet
    notes: Optional[str] = ""
    location: Optional[str] = ""
    client_name: Optional[str] = ""


class MissionStep(BaseModel):
    agent: str
    task: str
    why: Optional[str] = ""


class MissionPlanBody(BaseModel):
    objective: str
    client_id: Optional[str] = None
    agents: List[str] = []        # roster a considerar; vacío = todos


class MissionBody(BaseModel):
    objective: str
    agents: List[str] = []                       # fan-out clásico (legacy)
    steps: Optional[List[MissionStep]] = None    # plan del CEO (sub-tarea por agente)
    auto: bool = False                           # si True y sin steps/agents → el CEO planifica
    client_id: Optional[str] = None
    notes: Optional[str] = ""


class ImageBody(BaseModel):
    prompt: str
    aspect_ratio: Optional[str] = "1:1"
    n: Optional[int] = 1
    text: Optional[str] = None          # titular a componer encima (texto exacto)
    subtitle: Optional[str] = None


class PublishBody(BaseModel):
    image: str                          # /media/<file> o URL absoluta
    caption: Optional[str] = ""
    targets: Optional[List[str]] = None  # ["instagram","facebook"]; default ambos


_AGENT_DESCRIPTIONS = {
    "leadhunter": "Genera 10 leads/día con contacto verificado (FIT 4-6)",
    "content_creator": "Posts/contenido para redes de Automiq",
    "tiktok_creator": "Guiones de TikTok en la voz de Nazareno (avatar de marca) + thumbnail",
    "growth_hacker": "Hipótesis de growth + quick wins",
    "creative_strategist": "Ads de marca + personalizados + headlines",
    "social_media": "Calendario semanal de redes",
    "outbound": "Motor de secuencia de cold-email",
    "media_auditor": "Auditoría de cuentas de ads",
    "seo_specialist": "SEO: keywords + quick wins on-page",
    "web_auditor": "Auditoría de páginas web puntuada",
    "inbox_assistant": "Lee la bandeja + redacta borradores",
    "meeting_prep": "Prepara reuniones con la memoria del cliente (brief, agente de test, demo, objeciones)",
    "web_optimizer": "Mejora la landing (CRO/SEO/diseño) y deploya un preview en Vercel; aprobás y publica",
}


def _agent_last_output(name: str) -> Dict[str, Any]:
    """Última corrida del agente según los reportes en data/."""
    prefix = f"{name.replace('_', '-')}-report-"
    files = sorted(_data_dir().glob(f"{prefix}*.md"))
    if not files:
        return {"has_output": False, "last_date": None}
    last = files[-1]
    m = re.search(r"(\d{4}-\d{2}-\d{2})", last.stem)
    today = datetime.now(pytz.timezone("America/Buenos_Aires")).strftime("%Y-%m-%d")
    date = m.group(1) if m else None
    return {"has_output": True, "last_date": date, "today": date == today}


@app.post("/api/login")
async def api_login(body: LoginBody):
    settings = get_settings()
    ok = bool(settings.webhook_secret) and hmac.compare_digest(body.secret, settings.webhook_secret)
    if not ok:
        raise HTTPException(status_code=401, detail="Clave inválida")
    return {"ok": True}


@app.get("/api/agents")
async def api_agents(request: Request):
    _verify_webhook_secret(request)
    out = []
    for n in list_agents():
        info = _agent_last_output(n)
        out.append({
            "name": n,
            "description": _AGENT_DESCRIPTIONS.get(n, ""),
            "schedule": DEFAULT_SCHEDULES.get(n),
            **info,
        })
    return {"agents": out}


@app.post("/api/agents/{name}/run")
async def api_run_agent(name: str, request: Request, background: BackgroundTasks):
    _verify_webhook_secret(request)
    if name not in list_agents():
        raise HTTPException(status_code=404, detail=f"agente {name} no existe")
    run_id = str(uuid.uuid4())
    background.add_task(_run_pack_agent, name, {"force_global": True}, run_id, "dashboard")
    return {"ok": True, "run_id": run_id, "agent": name, "status": "queued"}


async def _run_agent_task(name: str, prompt: str, run_id: str,
                          client_id: Optional[str] = None) -> None:
    from .integrations import tasks_store as ts
    try:
        args: Dict[str, Any] = {"task_prompt": prompt, "force_global": True}
        if client_id:
            args["client_id"] = client_id
        result = await _run_pack_agent(name, args, run_id, "dashboard:task")
        ts.update_task(run_id, "done", str(result)[:600] if result else "")
    except Exception as e:
        ts.update_task(run_id, "error", str(e)[:600])


@app.post("/api/tasks")
async def api_create_task(body: TaskBody, request: Request, background: BackgroundTasks):
    _verify_webhook_secret(request)
    from .integrations import tasks_store as ts
    if body.agent not in list_agents():
        raise HTTPException(status_code=404, detail=f"agente {body.agent} no existe")
    if not body.prompt.strip():
        raise HTTPException(status_code=400, detail="prompt vacío")
    run_id = str(uuid.uuid4())
    task = ts.add_task(body.agent, body.prompt.strip(), run_id)
    background.add_task(_run_agent_task, body.agent, body.prompt.strip(), run_id, body.client_id)
    return {"ok": True, "task": task}


@app.get("/api/tasks")
async def api_list_tasks(request: Request):
    _verify_webhook_secret(request)
    from .integrations import tasks_store as ts
    return {"tasks": ts.list_tasks(50)}


@app.delete("/api/tasks/{task_id}")
async def api_delete_task(task_id: str, request: Request):
    _verify_webhook_secret(request)
    from .integrations import tasks_store as ts
    return {"ok": ts.delete_task(task_id)}


@app.get("/api/clients")
async def api_list_clients(request: Request):
    _verify_webhook_secret(request)
    from .integrations import clients_store as cs, localization as loc
    return {"clients": cs.list_clients(), "counts": cs.summary_counts(),
            "stages": cs.STAGES, "countries": loc.list_countries()}


@app.post("/api/clients")
async def api_create_client(body: ClientBody, request: Request):
    _verify_webhook_secret(request)
    from .integrations import clients_store as cs
    return {"ok": True, "client": cs.create_client(body.model_dump())}


@app.put("/api/clients/{client_id}")
async def api_update_client(client_id: str, body: ClientBody, request: Request):
    _verify_webhook_secret(request)
    from .integrations import clients_store as cs
    c = cs.update_client(client_id, body.model_dump())
    if not c:
        raise HTTPException(status_code=404, detail="cliente no encontrado")
    return {"ok": True, "client": c}


@app.post("/api/clients/archive")
async def api_archive_clients(request: Request):
    """Archiva manualmente los prospectos fríos (>N días sin movimiento)."""
    _verify_webhook_secret(request)
    from .integrations import clients_store as cs
    return await run_in_threadpool(cs.auto_archive, get_settings().client_archive_days)


@app.delete("/api/clients/{client_id}")
async def api_delete_client(client_id: str, request: Request):
    _verify_webhook_secret(request)
    from .integrations import clients_store as cs
    if not cs.delete_client(client_id):
        raise HTTPException(status_code=404, detail="cliente no encontrado")
    return {"ok": True}


@app.get("/api/pipeline")
async def api_pipeline(request: Request):
    _verify_webhook_secret(request)
    from .integrations import leads_store as ls
    store = ls.load_store()
    leads = [ls.lead_view(l) for l in store.get("leads", {}).values()]
    leads.sort(key=lambda l: (str(l.get("state")), str(l.get("company"))))
    return {"counts": ls.summary_counts(store), "leads": leads}


@app.put("/api/pipeline/{key}")
async def api_update_lead(key: str, body: LeadBody, request: Request):
    _verify_webhook_secret(request)
    from .integrations import leads_store as ls
    lead = ls.update_lead(key, body.model_dump(exclude_none=True))
    if not lead:
        raise HTTPException(status_code=404, detail="lead no encontrado")
    return {"ok": True, "lead": lead}


@app.delete("/api/pipeline/{key}")
async def api_delete_lead(key: str, request: Request):
    _verify_webhook_secret(request)
    from .integrations import leads_store as ls
    return {"ok": ls.delete_lead(key)}


# ── Memoria por cliente (reports + info recaudada) ──

@app.get("/api/clients/{client_id}/memory")
async def api_client_memory(client_id: str, request: Request, kind: Optional[str] = None):
    _verify_webhook_secret(request)
    from .integrations import client_memory_store as cms, clients_store as cs
    client = cs.get_client(client_id)
    if not client:
        raise HTTPException(status_code=404, detail="cliente no encontrado")
    return {"client": client, "memory": cms.list_memory(client_id, kind=kind)}


@app.post("/api/clients/{client_id}/memory")
async def api_add_client_memory(client_id: str, body: ClientMemoryBody, request: Request):
    _verify_webhook_secret(request)
    from .integrations import client_memory_store as cms, clients_store as cs
    if not cs.get_client(client_id):
        raise HTTPException(status_code=404, detail="cliente no encontrado")
    item = cms.add_memory(client_id, kind=body.kind or "note", agent=body.agent or "",
                          title=body.title or "", content=body.content, meta=body.meta)
    return {"ok": True, "item": item}


@app.delete("/api/clients/{client_id}/memory/{mem_id}")
async def api_del_client_memory(client_id: str, mem_id: str, request: Request):
    _verify_webhook_secret(request)
    from .integrations import client_memory_store as cms
    cms.delete_memory(mem_id)
    return {"ok": True}


@app.post("/api/clients/{client_id}/prep")
async def api_client_prep(client_id: str, request: Request, background: BackgroundTasks):
    """Prepara una reunión para el cliente (sin agendar): dispara meeting_prep con
    toda su memoria. El brief queda en su memoria del cliente."""
    _verify_webhook_secret(request)
    from .integrations import clients_store as cs, tasks_store as ts
    client = cs.get_client(client_id)
    if not client:
        raise HTTPException(status_code=404, detail="cliente no encontrado")
    if cs.is_frozen(client_id):
        raise HTTPException(status_code=400, detail="cliente descartado (memoria congelada)")
    run_id = str(uuid.uuid4())
    ts.add_task("meeting_prep", f"Preparar reunión para {client.get('name')}", run_id)
    args = {"force_global": True, "client_id": client_id,
            "meeting": {"client_name": client.get("name"), "title": "Reunión comercial"}}

    async def _prep():
        from .integrations import tasks_store as ts2
        try:
            result = await _run_pack_agent("meeting_prep", args, run_id, "dashboard:client-prep")
            ts2.update_task(run_id, "done", str(result)[:600] if result else "")
        except Exception as e:
            ts2.update_task(run_id, "error", str(e)[:600])

    background.add_task(_prep)
    return {"ok": True, "run_id": run_id, "status": "queued"}


# ── Memoria general (knowledge base de la empresa) ──

@app.get("/api/memory")
async def api_list_memory(request: Request, section: Optional[str] = None):
    _verify_webhook_secret(request)
    from .integrations import memory_store as ms
    return {"memory": ms.list_company_memory(section), "db": ms.db.enabled()}


@app.post("/api/memory")
async def api_upsert_memory(body: MemoryBody, request: Request):
    _verify_webhook_secret(request)
    from .integrations import memory_store as ms
    item = ms.upsert_company_memory(body.section or "general", body.title, body.content,
                                    body.source or "", body.tags or [])
    return {"ok": True, "item": item}


@app.put("/api/memory/{mem_id}")
async def api_update_memory(mem_id: str, body: MemoryBody, request: Request):
    _verify_webhook_secret(request)
    from .integrations import memory_store as ms
    item = ms.update_company_memory(mem_id, body.model_dump(exclude_none=True))
    if not item:
        raise HTTPException(status_code=404, detail="entrada no encontrada")
    return {"ok": True, "item": item}


@app.delete("/api/memory/{mem_id}")
async def api_del_memory(mem_id: str, request: Request):
    _verify_webhook_secret(request)
    from .integrations import memory_store as ms
    ms.delete_company_memory(mem_id)
    return {"ok": True}


# ── Objetivos de growth por sector ──

@app.get("/api/growth")
async def api_list_growth(request: Request, sector: Optional[str] = None, status: Optional[str] = None):
    _verify_webhook_secret(request)
    from .integrations import memory_store as ms
    return {"objectives": ms.list_growth(sector, status)}


@app.post("/api/growth")
async def api_add_growth(body: GrowthBody, request: Request):
    _verify_webhook_secret(request)
    from .integrations import memory_store as ms
    if not (body.objective or "").strip():
        raise HTTPException(status_code=400, detail="objetivo vacío")
    return {"ok": True, "objective": ms.add_growth(body.sector or "general", body.objective,
            body.metric or "", body.target or "", body.status or "activo", body.notes or "")}


@app.put("/api/growth/{obj_id}")
async def api_update_growth(obj_id: str, body: GrowthBody, request: Request):
    _verify_webhook_secret(request)
    from .integrations import memory_store as ms
    # exclude_unset: un update parcial NO debe pisar sector/status/notes con defaults.
    o = ms.update_growth(obj_id, body.model_dump(exclude_unset=True))
    if not o:
        raise HTTPException(status_code=404, detail="objetivo no encontrado")
    return {"ok": True, "objective": o}


@app.delete("/api/growth/{obj_id}")
async def api_del_growth(obj_id: str, request: Request):
    _verify_webhook_secret(request)
    from .integrations import memory_store as ms
    ms.delete_growth(obj_id)
    return {"ok": True}


# ── Lecciones por agente (loop de mejora continua) ──

@app.get("/api/lessons")
async def api_list_lessons(request: Request, agent: Optional[str] = None):
    _verify_webhook_secret(request)
    from .integrations import memory_store as ms
    return {"lessons": ms.list_lessons(agent=agent, active_only=False)}


@app.post("/api/learning/digest")
async def api_learning_digest(request: Request):
    """Corre el digest de aprendizaje on-demand: consolida lecciones data-driven
    (rubros que convierten) para leadhunter/outbound desde el pipeline real."""
    _verify_webhook_secret(request)
    from .integrations import learning
    res = await run_in_threadpool(learning.digest)
    return {"ok": True, "result": res}


@app.post("/api/lessons")
async def api_add_lesson(body: LessonBody, request: Request):
    _verify_webhook_secret(request)
    from .integrations import memory_store as ms
    if body.agent not in list_agents():
        raise HTTPException(status_code=404, detail=f"agente {body.agent} no existe")
    if not (body.lesson or "").strip():
        raise HTTPException(status_code=400, detail="lección vacía")
    return {"ok": True, "lesson": ms.add_lesson(body.agent, body.lesson,
            body.kind or "feedback", body.weight or 1)}


@app.put("/api/lessons/{lesson_id}")
async def api_update_lesson(lesson_id: str, body: LessonEditBody, request: Request):
    _verify_webhook_secret(request)
    from .integrations import memory_store as ms
    return {"ok": ms.update_lesson(lesson_id, body.lesson)}


@app.delete("/api/lessons/{lesson_id}")
async def api_del_lesson(lesson_id: str, request: Request):
    """Borrado real de la lección (el 🗑 del panel la elimina)."""
    _verify_webhook_secret(request)
    from .integrations import memory_store as ms
    ms.delete_lesson(lesson_id)
    return {"ok": True}


@app.get("/api/db/health")
async def api_db_health(request: Request):
    _verify_webhook_secret(request)
    from .integrations import db
    return db.healthcheck()


# ── Generación de imágenes para contenido ──

@app.post("/api/image")
async def api_generate_image(body: ImageBody, request: Request):
    _verify_webhook_secret(request)
    from .integrations import image_gen
    if not image_gen.enabled():
        raise HTTPException(status_code=400, detail="generación de imágenes deshabilitada (sin MINIMAX_API_KEY)")
    if not (body.prompt or "").strip():
        raise HTTPException(status_code=400, detail="prompt vacío")
    urls = image_gen.generate_image(body.prompt, body.aspect_ratio or "1:1", body.n or 1,
                                    text=body.text, subtitle=body.subtitle)
    if not urls:
        raise HTTPException(status_code=502, detail="no se pudo generar la imagen (proveedor)")
    return {"ok": True, "urls": urls}


@app.get("/api/publish/status")
async def api_publish_status(request: Request):
    _verify_webhook_secret(request)
    from .integrations import social_publish as sp
    return sp.status()


@app.post("/api/publish")
async def api_publish(body: PublishBody, request: Request):
    _verify_webhook_secret(request)
    from .integrations import social_publish as sp
    if not sp.enabled():
        raise HTTPException(status_code=400,
                            detail="publicación a redes no configurada (faltan tokens de Meta: META_PAGE_TOKEN + META_PAGE_ID/IG_BUSINESS_ID)")
    if not (body.image or "").strip():
        raise HTTPException(status_code=400, detail="falta la imagen a publicar")
    # IMPORTANTE: sp.publish hace llamadas HTTP síncronas a la Graph API, y la Graph
    # API a su vez descarga la imagen /media/... DE ESTE MISMO backend. Si corriéramos
    # esto en el event loop lo bloquearíamos y el contenedor no podría servir el fetch
    # de /media que FB le hace en paralelo -> "Missing or invalid image file" (deadlock
    # consigo mismo). Lo offloadeamos a un threadpool para mantener el loop libre.
    res = await run_in_threadpool(sp.publish, body.image.strip(), body.caption or "", body.targets)
    if not res.get("ok"):
        # devolver el detalle por red para poder diagnosticar
        raise HTTPException(status_code=502, detail={"msg": "no se pudo publicar", **res})
    return res


@app.get("/api/publish/queue")
async def api_publish_queue(request: Request):
    """Cola de publicaciones: pendientes + publicadas hoy. Se drena 1/día."""
    _verify_webhook_secret(request)
    from .integrations import publish_queue as pq
    return pq.summary()


@app.post("/api/publish/drain")
async def api_publish_drain(request: Request):
    """Drena manualmente la cola. Por defecto respeta el límite de 1/día; con
    {"force": true} publica igual aunque ya se haya publicado hoy."""
    _verify_webhook_secret(request)
    from .integrations import publish_queue as pq
    try:
        body = await request.json()
    except Exception:
        body = {}
    force = bool(body.get("force")) if isinstance(body, dict) else False
    res = await run_in_threadpool(pq.drain_one, force)
    return res


@app.post("/api/publish/backfill-permalinks")
async def api_publish_backfill(request: Request):
    """Completa los permalinks faltantes de posts ya publicados (IG/FB) consultando
    la Graph API. Arregla los posts viejos para que sean clickeables desde el panel."""
    _verify_webhook_secret(request)
    from .integrations import publish_queue as pq
    res = await run_in_threadpool(pq.backfill_permalinks)
    return res


@app.delete("/api/publish/queue/{item_id}")
async def api_publish_queue_delete(item_id: str, request: Request):
    _verify_webhook_secret(request)
    from .integrations import publish_queue as pq
    return {"ok": pq.delete_item(item_id)}


# ── Finanzas / facturación / métricas (panel de gestión) ──

@app.get("/api/finance")
async def api_finance_list(request: Request):
    _verify_webhook_secret(request)
    from .integrations import finance_store as fs
    return {"expenses": fs.list_expenses(), "categories": fs.CATEGORIES}


@app.post("/api/finance")
async def api_finance_add(body: ExpenseBody, request: Request):
    _verify_webhook_secret(request)
    from .integrations import finance_store as fs
    item = fs.add_expense(body.category or "otros", body.label or "", body.amount,
                          body.currency or "USD", body.date or "", bool(body.recurring))
    return {"ok": True, "expense": item}


@app.put("/api/finance/{expense_id}")
async def api_finance_update(expense_id: str, body: ExpenseBody, request: Request):
    _verify_webhook_secret(request)
    from .integrations import finance_store as fs
    # exclude_unset: un update parcial NO debe resetear amount/currency/category
    # a los defaults del modelo.
    e = fs.update_expense(expense_id, body.model_dump(exclude_unset=True))
    if not e:
        raise HTTPException(status_code=404, detail="gasto no encontrado")
    return {"ok": True, "expense": e}


@app.delete("/api/finance/{expense_id}")
async def api_finance_delete(expense_id: str, request: Request):
    _verify_webhook_secret(request)
    from .integrations import finance_store as fs
    return {"ok": fs.delete_expense(expense_id)}


@app.get("/api/finance/summary")
async def api_finance_summary(request: Request):
    _verify_webhook_secret(request)
    from .integrations import finance_store as fs, clients_store as cs
    summary = fs.finance_summary()
    summary["billing"] = cs.summary_billing()
    summary["by_client"] = cs.revenue_by_client()
    return summary


@app.get("/api/fx")
async def api_fx_get(request: Request):
    _verify_webhook_secret(request)
    from .integrations import fx_store
    return {"rates": fx_store.get_rates()}


@app.put("/api/fx")
async def api_fx_set(body: FxBody, request: Request):
    _verify_webhook_secret(request)
    from .integrations import fx_store
    return {"ok": True, "rates": fx_store.set_rates(body.rates)}


@app.get("/api/metrics")
async def api_metrics(request: Request):
    _verify_webhook_secret(request)
    from .integrations import metrics_store as ms
    return ms.series()


@app.get("/api/dashboard/stats")
async def api_dashboard_stats(request: Request):
    """Consolidado para el Resumen: facturación, finanzas, pipeline, clientes,
    growth y conteos del 'motor' (conexiones entre piezas)."""
    _verify_webhook_secret(request)
    from .integrations import (clients_store as cs, finance_store as fs,
                               leads_store as ls, memory_store as ms,
                               metrics_store as mt, publish_queue as pq)
    billing = cs.summary_billing()
    fin = fs.finance_summary()
    pipe = ls.summary_counts(ls.load_store())
    try:
        growth = ms.list_growth()
    except Exception:
        growth = []
    growth_open = [g for g in growth if (g.get("status") or "").lower() not in ("hecho", "done", "cerrado")]

    # ── Alertas (señales accionables) ──
    alerts: List[Dict[str, str]] = []
    if fin["profit_month_usd"] < 0:
        alerts.append({"level": "red", "msg": f"Ganancia del mes negativa: {fin['profit_month_usd']:.0f} USD (gastos > ingresos)."})
    paused = billing["by_status"].get("pausado", 0) + billing["by_status"].get("baja", 0)
    if paused:
        alerts.append({"level": "amber", "msg": f"{paused} cliente(s) pausados o de baja: revisá la cartera."})
    if billing["active"] == 0 and billing["total"] > 0:
        alerts.append({"level": "amber", "msg": "No hay clientes activos facturando."})
    try:
        qs = pq.summary()
        failed = sum(1 for it in qs.get("items", []) if it.get("status") == "failed")
        if failed:
            alerts.append({"level": "red", "msg": f"{failed} publicación(es) fallaron: revisá la sección Publicaciones."})
    except Exception:
        pass
    if not growth_open and growth:
        alerts.append({"level": "amber", "msg": "No quedan objetivos de growth abiertos: definí los próximos."})
    return {
        "billing": billing,
        "finance": {
            "mrr_usd": fin["mrr_usd"],
            "expenses_month_usd": fin["expenses_month_usd"],
            "profit_month_usd": fin["profit_month_usd"],
            "months": fin["months"],
            "revenue_series": fin["revenue_series"],
            "expenses_series": fin["expenses_series"],
            "profit_series": fin["profit_series"],
            "by_category": fin["by_category"],
        },
        "pipeline": pipe,
        "clients_by_stage": cs.summary_counts(),
        "growth_total": len(growth),
        "growth_open": len(growth_open),
        "growth_items": growth,
        "metrics": mt.series(),
        "alerts": alerts,
        "engine": {
            "leads": pipe.get("total", 0),
            "clients_active": billing["active"],
            "clients_total": billing["total"],
            "mrr_usd": billing["mrr_usd"],
            "growth_open": len(growth_open),
        },
    }


# ── Agente demo público de la landing ────────────────────────────────────────
# Endpoint SIN secret (lo usa el widget de chat de automiq.agency). Protegido por
# CORS + rate limit por IP + tope global diario. No toca datos internos.

_DEMO_SYSTEM = (
    "Sos el agente de demostración de Automiq (automiq.agency), una agencia argentina de "
    "agentes de IA y automatización para PyMEs de 25-100 empleados (manufactureras, "
    "distribuidoras, logísticas e inmobiliarias). El visitante te está PROBANDO para ver "
    "cómo respondería un agente así en su propia empresa: demostrá con el ejemplo.\n"
    "Servicios: agente de ventas por WhatsApp (califica leads 24/7, responde en <2 min), "
    "agente de cobranza (recordatorios inteligentes, +30% de recuperación), dashboards en "
    "tiempo real conectados al ERP, agente de atención al cliente, automatizaciones "
    "n8n/Make a medida (+20 hs/semana liberadas). Modelo: diagnóstico GRATIS de 30 minutos "
    "con 2-3 quick wins; trabajo mes a mes sin permanencia.\n"
    "Reglas: respondé en español rioplatense, cálido y profesional, MÁXIMO 3-4 oraciones. "
    "NUNCA inventes precios (decí que se definen tras el diagnóstico). Si preguntan algo "
    "fuera de tema, contestá breve y traé la charla de vuelta a cómo la IA ayuda a su "
    "empresa. Cuando haya interés real, ofrecé agendar el diagnóstico por WhatsApp "
    "+54 9 11 2771 3231 o info@automiq.agency."
)
_demo_usage: Dict[str, Any] = {"day": "", "total": 0, "ips": {}}
_DEMO_IP_LIMIT = 20
_DEMO_GLOBAL_LIMIT = 400


class DemoChatBody(BaseModel):
    message: str
    history: Optional[List[Dict[str, str]]] = None


@app.post("/api/demo/chat")
async def api_demo_chat(body: DemoChatBody, request: Request):
    from datetime import datetime as _dt
    msg = (body.message or "").strip()[:500]
    if not msg:
        raise HTTPException(status_code=400, detail="mensaje vacío")
    # rate limit por día (in-memory: se resetea en cada deploy, suficiente para demo)
    today = _dt.utcnow().strftime("%Y-%m-%d")
    if _demo_usage["day"] != today:
        _demo_usage.update({"day": today, "total": 0, "ips": {}})
    ip = (request.headers.get("x-forwarded-for") or (request.client.host if request.client else "?")).split(",")[0].strip()
    if _demo_usage["total"] >= _DEMO_GLOBAL_LIMIT:
        raise HTTPException(status_code=429, detail="El agente demo alcanzó su límite diario. ¡Escribinos por WhatsApp!")
    if _demo_usage["ips"].get(ip, 0) >= _DEMO_IP_LIMIT:
        raise HTTPException(status_code=429, detail="Llegaste al límite de la demo por hoy. Agendá tu diagnóstico gratis 😉")
    _demo_usage["total"] += 1
    _demo_usage["ips"][ip] = _demo_usage["ips"].get(ip, 0) + 1

    history = []
    for h in (body.history or [])[-8:]:
        role = "assistant" if h.get("role") == "assistant" else "user"
        content = str(h.get("content", ""))[:500]
        if content:
            history.append({"role": role, "content": content})
    history.append({"role": "user", "content": msg})

    def _run() -> str:
        from .clients.minimax import MiniMaxClient
        with MiniMaxClient(get_settings()) as mc:
            r = mc.complete(_DEMO_SYSTEM, history, max_tokens=350, temperature=0.7)
            return (r.text or "").strip()

    try:
        reply = await run_in_threadpool(_run)
    except Exception as e:
        log.warning("demo_chat_failed", error=str(e)[:200])
        raise HTTPException(status_code=503, detail="El agente está ocupado, probá en un ratito 🙏")
    return {"ok": True, "reply": reply or "¿En qué te puedo ayudar con tu empresa?"}


# ── Formulario de contacto de la landing (lead inbound) ─────────────────────
_lead_usage: Dict[str, Any] = {"day": "", "total": 0, "ips": {}}


class WebLeadBody(BaseModel):
    name: str
    email: Optional[str] = ""
    phone: Optional[str] = ""
    company: Optional[str] = ""
    message: Optional[str] = ""


def _lead_auto_reply(name: str, email: str, company: str, message: str) -> None:
    """Primer contacto AUTOMÁTICO al lead de la web: mail personalizado según su
    solicitud (MiniMax redacta; template si falla), desde info@automiq.agency.
    Corre en background para no demorar la respuesta del formulario."""
    from .integrations.gmail_client import GmailClient
    s = get_settings()
    if not email or not s.gmail_configured:
        return
    first = (name.split()[0] if name.strip() else "").capitalize()
    body_txt = ""
    try:
        from .clients.minimax import MiniMaxClient
        sys_prompt = (
            "Sos el equipo de Automiq (automiq.agency), agencia argentina de agentes de IA y "
            "automatización para PyMEs. Un prospecto dejó sus datos en la web pidiendo que lo "
            "contactemos. Escribí SOLO el cuerpo del email de primera respuesta (sin asunto, "
            "sin firma — la firma la agrega el sistema): español rioplatense, cálido y concreto, "
            "3-5 oraciones. Arrancá saludándolo por el nombre, retomá ESPECÍFICAMENTE lo que "
            "pidió (si dejó mensaje) mostrando que lo leímos, contale en una línea cómo lo "
            "resolvemos, y proponé coordinar el diagnóstico gratis de 30 minutos respondiendo "
            "este mail o por WhatsApp +54 9 11 2771 3231. NUNCA inventes precios ni promesas."
        )
        user_msg = (f"Nombre: {name}\nEmpresa: {company or 'no dijo'}\n"
                    f"Solicitud: {message or 'no dejó mensaje, solo pidió contacto'}")
        with MiniMaxClient(s) as mc:
            r = mc.complete(sys_prompt, [{"role": "user", "content": user_msg}],
                            max_tokens=400, temperature=0.6)
            body_txt = (r.text or "").strip()
    except Exception as e:
        log.warning("lead_reply_llm_failed", error=str(e)[:200])
    if not body_txt:
        body_txt = (f"¡Hola{' ' + first if first else ''}! Gracias por escribirnos desde automiq.agency.\n\n"
                    "Recibimos tu consulta y en menos de 2 horas hábiles te contactamos para "
                    "coordinar tu diagnóstico gratis de 30 minutos. Si querés adelantar, "
                    "respondé este mail contándonos un poco más de tu operación, o escribinos "
                    "por WhatsApp al +54 9 11 2771 3231.")
    body_txt += "\n\n—\nEquipo Automiq · automiq.agency\ninfo@automiq.agency · WhatsApp +54 9 11 2771 3231"
    try:
        gc = GmailClient(s)
        msg_id = gc.send_message(email, "Recibimos tu consulta — Automiq",
                                 body_txt, from_name=s.outbound_from_name)
        # dejar rastro en el lead
        from .integrations import leads_store as ls
        store = ls.load_store()
        key = ls.lead_key(email=email, company=company or name)
        lead = store.get("leads", {}).get(key)
        if lead is not None:
            lead.setdefault("notes", []).append(
                f"[auto] Primera respuesta enviada por mail (msg {msg_id}) según su solicitud.")
            ls.save_store(store)
        log.info("lead_auto_reply_sent", to=email, msg_id=msg_id)
    except Exception as e:
        log.warning("lead_auto_reply_failed", error=str(e)[:200])


@app.post("/api/web/lead")
async def api_web_lead(body: WebLeadBody, request: Request, background: BackgroundTasks):
    """Público (CORS de la landing). El visitante pide que lo contactemos:
    entra al pipeline como lead INBOUND caliente + aviso a Discord (#agencia)
    + primera respuesta automática por mail basada en su solicitud."""
    from datetime import datetime as _dt
    name = (body.name or "").strip()[:120]
    email = (body.email or "").strip()[:160]
    phone = (body.phone or "").strip()[:40]
    company = (body.company or "").strip()[:120]
    message = (body.message or "").strip()[:600]
    if not name or not (email or phone):
        raise HTTPException(status_code=400, detail="Faltan datos: nombre y un mail o teléfono")
    today = _dt.utcnow().strftime("%Y-%m-%d")
    if _lead_usage["day"] != today:
        _lead_usage.update({"day": today, "total": 0, "ips": {}})
    ip = (request.headers.get("x-forwarded-for") or (request.client.host if request.client else "?")).split(",")[0].strip()
    if _lead_usage["total"] >= 60 or _lead_usage["ips"].get(ip, 0) >= 5:
        raise HTTPException(status_code=429, detail="Demasiados envíos por hoy — escribinos por WhatsApp")
    _lead_usage["total"] += 1
    _lead_usage["ips"][ip] = _lead_usage["ips"].get(ip, 0) + 1

    def _save():
        from .integrations import leads_store as ls
        store = ls.load_store()
        key = ls.upsert_lead(store, company=company or name, email=email, phone=phone, decisor=name)
        if key:
            lead = store["leads"][key]
            lead["state"] = "respondió"          # inbound caliente: el outbound NO lo toca
            lead["next_touch_at"] = None
            lead.setdefault("notes", []).append(
                f"[{today}] 🔥 INBOUND desde la landing (formulario): {message or 'pidió que lo contactemos'}")
            ls.save_store(store)
        return key

    key = await run_in_threadpool(_save)
    # aviso a Discord: canal #agencia (fallback: webhook default)
    try:
        from .clients.discord import DiscordWebhook
        s = get_settings()
        if getattr(s, "discord_configured", False):
            dw = DiscordWebhook(s)
            dw.send(f"🔥 **LEAD INBOUND desde la web**\n**{name}**" +
                    (f" · {company}" if company else "") +
                    (f"\n📧 {email}" if email else "") + (f"\n📱 {phone}" if phone else "") +
                    (f"\n> {message[:200]}" if message else "") +
                    ("\n→ Ya le mandamos la primera respuesta automática por mail."
                     if email else "\n→ Sin mail: contactarlo por WhatsApp."),
                    url=s.discord_agencia_webhook_url or None)
            dw.close()
    except Exception:
        pass
    # primera respuesta automática por mail, según su solicitud (background)
    if email:
        background.add_task(_lead_auto_reply, name, email, company, message)
    log.info("web_lead_received", key=key, has_email=bool(email), has_phone=bool(phone))
    return {"ok": True}


@app.get("/api/system/health")
async def api_system_health(request: Request):
    """Estado del sistema para el panel: DB, publicación IG/FB, imágenes, cola."""
    _verify_webhook_secret(request)
    from .integrations import social_publish as sp, image_gen, publish_queue as pq, db
    from .integrations import youtube_client as yt
    try:
        dbh = db.healthcheck()
        db_ok = bool(dbh.get("ok")) if isinstance(dbh, dict) else bool(dbh)
    except Exception:
        db_ok = False
    qs = pq.summary()
    s = get_settings()
    return {
        "db": db_ok,
        "publish": sp.status(),
        "images_enabled": image_gen.enabled(),
        # sólo config local (sin llamar a la API de YouTube: esto es un healthcheck)
        "youtube": {"configured": yt.enabled(),
                    "autoupload": bool(s.youtube_autoupload),
                    "privacy": s.youtube_privacy},
        "queue": {"pending": qs.get("pending", 0), "published_today": qs.get("published_today", 0)},
    }


# ── Ads (campañas) ──

@app.get("/api/ads")
async def api_ads_list(request: Request):
    """Campañas: las reales de Meta Ads (read-only) + las manuales (otras plataformas)."""
    _verify_webhook_secret(request)
    from .integrations import ads_store as ads, meta_ads
    manual = ads.list_campaigns()
    msum = ads.summary()
    live: List[Dict[str, Any]] = []
    meta_connected = meta_ads.enabled()
    if meta_connected:
        live = await run_in_threadpool(meta_ads.live_campaigns)
    campaigns = live + manual
    spend = msum["spend_usd"] + sum(c["spend_usd"] for c in live)
    rev = msum["revenue_usd"] + sum(c["revenue_usd"] for c in live)
    results = msum["results"] + sum(c.get("results", 0) or 0 for c in live)
    by_platform = dict(msum["by_platform"])
    for c in live:
        by_platform["Meta"] = by_platform.get("Meta", 0) + c["spend_usd"]
    summary = {
        "spend_usd": round(spend, 2), "revenue_usd": round(rev, 2), "results": results,
        "roas": round(rev / spend, 2) if spend else 0.0,
        "cpl_usd": round(spend / results, 2) if results else 0.0,
        "active": msum["active"] + sum(1 for c in live if c.get("status") == "activa"),
        "total": len(campaigns),
        "by_platform": {k: round(v, 2) for k, v in by_platform.items()},
        "platforms": msum["platforms"], "statuses": msum["statuses"],
        "meta_connected": meta_connected,
    }
    return {"campaigns": campaigns, "summary": summary, "meta_connected": meta_connected}


@app.post("/api/ads")
async def api_ads_add(body: AdBody, request: Request):
    _verify_webhook_secret(request)
    from .integrations import ads_store as ads
    return {"ok": True, "campaign": ads.add_campaign(body.model_dump())}


@app.put("/api/ads/{cid}")
async def api_ads_update(cid: str, body: AdBody, request: Request):
    _verify_webhook_secret(request)
    from .integrations import ads_store as ads
    c = ads.update_campaign(cid, body.model_dump(exclude_none=True))
    if not c:
        raise HTTPException(status_code=404, detail="campaña no encontrada")
    return {"ok": True, "campaign": c}


@app.delete("/api/ads/{cid}")
async def api_ads_delete(cid: str, request: Request):
    _verify_webhook_secret(request)
    from .integrations import ads_store as ads
    return {"ok": ads.delete_campaign(cid)}


@app.get("/media/{filename}")
async def media_file(filename: str):
    """Sirve las imágenes generadas (guardadas en el volume data/images/)."""
    safe = Path(filename).name  # evita path traversal
    path = _data_dir() / "images" / safe
    if not path.exists():
        raise HTTPException(status_code=404, detail="imagen no encontrada")
    low = safe.lower()
    if low.endswith((".jpg", ".jpeg")):
        mt = "image/jpeg"
    elif low.endswith(".mp4"):
        mt = "video/mp4"
    elif low.endswith(".webm"):
        mt = "video/webm"
    else:
        mt = "image/png"
    return FileResponse(str(path), media_type=mt)


# ── Agenda de reuniones ──

@app.get("/api/meetings")
async def api_list_meetings(request: Request, upcoming: bool = False):
    _verify_webhook_secret(request)
    from .integrations import meetings_store as mt
    return {"meetings": mt.list_meetings(upcoming_only=upcoming), "statuses": mt.STATUSES}


@app.post("/api/meetings")
async def api_create_meeting(body: MeetingBody, request: Request):
    _verify_webhook_secret(request)
    from .integrations import meetings_store as mt, clients_store as cs
    if not body.scheduled_at:
        raise HTTPException(status_code=400, detail="falta fecha/hora (scheduled_at)")
    name = body.client_name or ""
    if body.client_id and not name:
        c = cs.get_client(body.client_id)
        name = c["name"] if c else ""
    m = mt.create_meeting(body.client_id, name, body.title or "Reunión",
                          body.scheduled_at, body.location or "", body.notes or "")
    return {"ok": True, "meeting": m}


@app.put("/api/meetings/{meeting_id}")
async def api_update_meeting(meeting_id: str, body: MeetingBody, request: Request):
    _verify_webhook_secret(request)
    from .integrations import meetings_store as mt
    m = mt.update_meeting(meeting_id, body.model_dump(exclude_none=True))
    if not m:
        raise HTTPException(status_code=404, detail="reunión no encontrada")
    return {"ok": True, "meeting": m}


@app.delete("/api/meetings/{meeting_id}")
async def api_delete_meeting(meeting_id: str, request: Request):
    _verify_webhook_secret(request)
    from .integrations import meetings_store as mt
    mt.delete_meeting(meeting_id)
    return {"ok": True}


@app.post("/api/meetings/{meeting_id}/prep")
async def api_meeting_prep(meeting_id: str, request: Request, background: BackgroundTasks):
    """Dispara al agente meeting_prep con toda la memoria del cliente de la reunión."""
    _verify_webhook_secret(request)
    from .integrations import meetings_store as mt, tasks_store as ts
    meeting = mt.get_meeting(meeting_id)
    if not meeting:
        raise HTTPException(status_code=404, detail="reunión no encontrada")
    run_id = str(uuid.uuid4())
    ts.add_task("meeting_prep", f"Preparar reunión: {meeting.get('title')} "
                f"({meeting.get('client_name') or 's/cliente'})", run_id)
    args: Dict[str, Any] = {"force_global": True, "meeting": meeting}
    if meeting.get("client_id"):
        args["client_id"] = meeting["client_id"]

    async def _prep():
        from .integrations import tasks_store as ts2, meetings_store as mt2
        try:
            result = await _run_pack_agent("meeting_prep", args, run_id, "dashboard:meeting")
            ts2.update_task(run_id, "done", str(result)[:600] if result else "")
            mt2.update_meeting(meeting_id, {"prep_ready": True})
        except Exception as e:
            ts2.update_task(run_id, "error", str(e)[:600])

    background.add_task(_prep)
    return {"ok": True, "run_id": run_id, "status": "queued"}


# ── Calendario (sync con Google Calendar) ──

@app.get("/api/calendar")
async def api_calendar_events(request: Request):
    """Eventos del Google Calendar de la agencia entre ?from y ?to (RFC3339)."""
    _verify_webhook_secret(request)
    s = get_settings()
    if not s.gmail_configured:
        return {"configured": False, "events": [], "detail": "Gmail/Calendar no configurado."}
    from .integrations.calendar_client import get_calendar_client, CalendarError
    qp = request.query_params
    time_min = qp.get("from") or ""
    time_max = qp.get("to") or ""
    if not time_min or not time_max:
        raise HTTPException(status_code=400, detail="faltan ?from y ?to (RFC3339)")
    try:
        cal = get_calendar_client(s)
        events = await run_in_threadpool(cal.list_events, time_min, time_max)
        return {"configured": True, "events": events}
    except CalendarError as e:
        return {"configured": False, "events": [], "detail": str(e)}
    except Exception as e:
        # Scope insuficiente / token sin re-auth → reportar sin romper el panel.
        return {"configured": False, "events": [], "detail": f"calendar error: {e}"}


@app.post("/api/calendar")
async def api_calendar_create(body: CalendarEventBody, request: Request):
    """Crea un evento en Google Calendar (opcionalmente con Meet) y lo registra en el panel."""
    _verify_webhook_secret(request)
    s = get_settings()
    if not s.gmail_configured:
        raise HTTPException(status_code=400, detail="Gmail/Calendar no configurado (re-auth pendiente).")
    if not body.start_iso:
        raise HTTPException(status_code=400, detail="falta fecha/hora (start_iso)")
    from .integrations.calendar_client import get_calendar_client, CalendarError
    from .integrations import meetings_store as mt
    title = (body.title or "Reunión").strip()
    try:
        cal = get_calendar_client(s)
        if body.create_meet:
            ev = await run_in_threadpool(
                cal.create_meet_event, title, body.start_iso,
                int(body.duration_min or 30), body.attendee_email or None,
                body.notes or "")
        else:
            ev = await run_in_threadpool(
                _calendar_plain_event, cal, title, body.start_iso,
                int(body.duration_min or 30), body.attendee_email or None, body.notes or "")
    except CalendarError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"calendar error: {e}")
    # Registrar también en el panel (agenda) para que meeting_prep lo prepare.
    try:
        mt.create_meeting(None, body.client_name or "", title,
                          ev.get("start") or body.start_iso,
                          ev.get("meet_link") or body.location or "", body.notes or "")
    except Exception:
        pass
    return {"ok": True, "event": ev}


@app.delete("/api/calendar/{event_id}")
async def api_calendar_delete(event_id: str, request: Request):
    _verify_webhook_secret(request)
    s = get_settings()
    if not s.gmail_configured:
        raise HTTPException(status_code=400, detail="Gmail/Calendar no configurado.")
    from .integrations.calendar_client import get_calendar_client
    cal = get_calendar_client(s)
    await run_in_threadpool(cal.delete_event, event_id)
    return {"ok": True}


def _calendar_plain_event(cal, title, start_iso, duration_min, attendee, notes):
    """Crea un evento SIN Meet (reutiliza el service del calendar_client)."""
    from datetime import timedelta
    from .integrations.calendar_client import _parse_dt
    svc = cal._build_service()
    start_dt = _parse_dt(start_iso)
    end_dt = start_dt + timedelta(minutes=max(10, duration_min))
    body = {
        "summary": title, "description": notes or "",
        "start": {"dateTime": start_dt.isoformat(), "timeZone": "America/Argentina/Buenos_Aires"},
        "end": {"dateTime": end_dt.isoformat(), "timeZone": "America/Argentina/Buenos_Aires"},
    }
    if attendee:
        body["attendees"] = [{"email": attendee}]
    ev = svc.events().insert(calendarId="primary", body=body, sendUpdates="all").execute()
    return {"event_id": ev.get("id", ""), "meet_link": "", "html_link": ev.get("htmlLink", ""),
            "start": start_dt.isoformat(), "end": end_dt.isoformat()}


# ── Misiones del CEO (un objetivo → varios agentes) ──

@app.get("/api/missions")
async def api_list_missions(request: Request):
    _verify_webhook_secret(request)
    from .integrations import missions_store as mis
    return {"missions": mis.list_missions()}


def _agent_roster(only: Optional[List[str]] = None) -> List[Dict[str, str]]:
    """Roster {name, description} para el planner del CEO."""
    names = list_agents()
    if only:
        names = [a for a in names if a in only]
    return [{"name": n, "description": _AGENT_DESCRIPTIONS.get(n, "")} for n in names]


def _client_ctx_for_plan(client_id: Optional[str]) -> str:
    if not client_id:
        return ""
    try:
        from .integrations import clients_store as cs, localization as loc
        c = cs.get_client(client_id)
        if not c:
            return ""
        return (f"{c.get('name')} — {loc.label(c.get('country'))} — "
                f"vertical {c.get('vertical') or 's/v'} — etapa {c.get('stage')}")
    except Exception:
        return ""


@app.post("/api/missions/plan")
async def api_plan_mission(body: MissionPlanBody, request: Request):
    """El CEO descompone el objetivo en sub-tareas por agente (preview, no dispara)."""
    _verify_webhook_secret(request)
    if not (body.objective or "").strip():
        raise HTTPException(status_code=400, detail="objetivo vacío")
    from .integrations import ceo_planner as cp
    roster = _agent_roster(body.agents or None)
    steps = cp.plan_objective(body.objective.strip(), roster,
                              client_ctx=_client_ctx_for_plan(body.client_id))
    return {"ok": True, "steps": steps, "planner": "llm" if steps else "none"}


@app.post("/api/missions")
async def api_create_mission(body: MissionBody, request: Request, background: BackgroundTasks):
    _verify_webhook_secret(request)
    from .integrations import missions_store as mis, ceo_planner as cp
    objective = (body.objective or "").strip()
    if not objective:
        raise HTTPException(status_code=400, detail="objetivo vacío")

    valid = set(list_agents())
    # 1) plan explícito (aprobado en el dashboard) → cada agente con SU sub-tarea
    steps: List[Dict[str, Any]] = []
    if body.steps:
        steps = [{"agent": s.agent, "task": s.task} for s in body.steps if s.agent in valid and s.task.strip()]
    # 2) auto: el CEO planifica (cuando no hay steps ni agentes elegidos)
    elif body.auto or not body.agents:
        roster = _agent_roster(body.agents or None)
        plan = cp.plan_objective(objective, roster, client_ctx=_client_ctx_for_plan(body.client_id))
        steps = [{"agent": p["agent"], "task": p["task"]} for p in plan]

    # 3) fallback / legacy fan-out: mismo objetivo a los agentes elegidos
    if not steps:
        agents = [a for a in body.agents if a in valid]
        if not agents:
            raise HTTPException(status_code=400, detail="no se pudo planificar; elegí al menos un agente")
        steps = [{"agent": a, "task": f"Resolvé tu parte de este objetivo desde tu rol de {a}."} for a in agents]

    agents = [s["agent"] for s in steps]
    run_ids: Dict[str, str] = {a: str(uuid.uuid4()) for a in agents}
    mission = mis.create_mission(objective, agents, body.client_id, run_ids, body.notes or "", plan=steps)

    # disparar cada agente con SU sub-tarea concreta
    from .integrations import tasks_store as ts
    for s in steps:
        a, rid = s["agent"], run_ids[s["agent"]]
        prompt = (f"MISIÓN del CEO: {objective}\n\n"
                  f"TU SUB-TAREA específica ({a}):\n{s['task']}\n\n"
                  "Resolvé exactamente tu sub-tarea y entregá ese resultado, listo para usar.")
        ts.add_task(a, prompt, rid)
        background.add_task(_run_agent_task, a, prompt, rid, body.client_id)
    return {"ok": True, "mission": mission, "steps": steps}


@app.delete("/api/missions/{mission_id}")
async def api_delete_mission(mission_id: str, request: Request):
    _verify_webhook_secret(request)
    from .integrations import missions_store as mis
    mis.delete_mission(mission_id)
    return {"ok": True}


# ── TikTok (Login Kit OAuth + Content Posting API) ──

def _tiktok_state_path() -> Path:
    return _data_dir() / "tiktok-oauth-state.json"


def _tiktok_save_state(state: str, key: str) -> None:
    import time as _t
    p = _tiktok_state_path()
    try:
        data = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except Exception:
        data = {}
    now = int(_t.time())
    data = {s: v for s, v in data.items() if now - int(v.get("ts", 0)) < 3600}
    data[state] = {"key": key, "ts": now}
    try:
        p.write_text(json.dumps(data), encoding="utf-8")
    except Exception:
        pass


def _tiktok_pop_state(state: str) -> Dict[str, Any]:
    p = _tiktok_state_path()
    try:
        data = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except Exception:
        data = {}
    v = data.pop(state, None)
    try:
        p.write_text(json.dumps(data), encoding="utf-8")
    except Exception:
        pass
    return v or {}


@app.get("/auth/tiktok/login")
async def tiktok_login(request: Request):
    """Inicia el OAuth de TikTok. Requiere ?key=WEBHOOK_SECRET (acción de admin)."""
    s = get_settings()
    key = request.query_params.get("key", "")
    if not s.webhook_secret or not hmac.compare_digest(key, s.webhook_secret):
        raise HTTPException(status_code=401, detail="key inválida")
    from .integrations.tiktok_client import get_tiktok_client
    tc = get_tiktok_client(s)
    if not tc.configured():
        raise HTTPException(status_code=400,
                            detail="TikTok no configurado (faltan TIKTOK_CLIENT_KEY/SECRET o redirect URI)")
    state = uuid.uuid4().hex
    _tiktok_save_state(state, key)
    return RedirectResponse(tc.authorize_url(state))


@app.get("/auth/tiktok/callback")
async def tiktok_callback(request: Request):
    """Callback de TikTok: intercambia el code por el token y lo guarda."""
    s = get_settings()
    qp = request.query_params
    if qp.get("error"):
        return HTMLResponse(
            f"<h2>TikTok devolvió un error</h2><pre>{qp.get('error')}: {qp.get('error_description','')}</pre>",
            status_code=400)
    code = qp.get("code")
    state = qp.get("state", "")
    if not code:
        return HTMLResponse("<h2>Falta el parámetro code</h2>", status_code=400)
    v = _tiktok_pop_state(state)
    from .integrations.tiktok_client import get_tiktok_client
    tc = get_tiktok_client(s)
    try:
        await run_in_threadpool(tc.exchange_code, code)
    except Exception as e:
        return HTMLResponse(f"<h2>No se pudo conectar la cuenta</h2><pre>{str(e)[:500]}</pre>",
                            status_code=502)
    key = v.get("key", "")
    return RedirectResponse(f"/tiktok?key={key}&connected=1" if key else "/tiktok")


@app.get("/api/tiktok/status")
async def api_tiktok_status(request: Request):
    _verify_webhook_secret(request)
    from .integrations.tiktok_client import get_tiktok_client
    return get_tiktok_client(get_settings()).status()


@app.post("/api/tiktok/post-test")
async def api_tiktok_post_test(request: Request):
    """Postea un video de prueba (Direct Post, PULL_FROM_URL). En sandbox = privado."""
    _verify_webhook_secret(request)
    s = get_settings()
    try:
        body = await request.json()
    except Exception:
        body = {}
    video_url = (body or {}).get("video_url") or s.tiktok_test_video_url
    caption = (body or {}).get("caption") or "Prueba de integración de Automiq 🤖 #automatizacion"
    if not video_url:
        raise HTTPException(status_code=400,
                            detail="falta video_url (mp4 en un dominio verificado en la app de TikTok)")
    from .integrations.tiktok_client import get_tiktok_client
    tc = get_tiktok_client(s)
    try:
        info = await run_in_threadpool(tc.creator_info)
        # FILE_UPLOAD: bajamos el mp4 y lo subimos por bytes (no requiere verificación
        # de dominio, a diferencia de PULL_FROM_URL).
        vid = await run_in_threadpool(tc.fetch_bytes, video_url)
        res = await run_in_threadpool(tc.post_video_file_upload, vid, caption)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e)[:500])
    # Registrar en la sección Publicaciones del panel.
    try:
        from .integrations import publish_queue as pq
        pid = (res.get("data") or {}).get("publish_id")
        pq.record_published(
            image=video_url, caption=caption, target="tiktok",
            result={"ok": True, "id": pid,
                    "privacy": "SELF_ONLY" if s.tiktok_sandbox else "PUBLIC"},
            source="api")
    except Exception:
        pass
    return {"ok": True, "creator_info": info.get("data"), "post": res.get("data")}


@app.post("/api/tiktok/disconnect")
async def api_tiktok_disconnect(request: Request):
    _verify_webhook_secret(request)
    from .integrations.tiktok_client import clear_token
    clear_token()
    return {"ok": True}


@app.get("/tiktok", response_class=HTMLResponse)
async def tiktok_connect_page(request: Request):
    """Página de conexión/demo de TikTok. Requiere ?key=WEBHOOK_SECRET."""
    s = get_settings()
    key = request.query_params.get("key", "")
    if not s.webhook_secret or not hmac.compare_digest(key, s.webhook_secret):
        return HTMLResponse("<body style='font-family:system-ui;background:#0D1426;color:#EAF0FF;"
                            "padding:3rem'><h2>No autorizado</h2><p>Agregá <code>?key=WEBHOOK_SECRET</code> "
                            "a la URL.</p></body>", status_code=401)
    from .integrations.tiktok_client import get_tiktok_client
    st = get_tiktok_client(s).status()
    connected = bool(st.get("connected"))
    badge = ("<span style='color:#22c55e'>● Conectada</span>" if connected
             else "<span style='color:#f59e0b'>● No conectada</span>")
    openid = st.get("open_id") or "—"
    sandbox = "Sí (posts privados)" if st.get("sandbox") else "No (producción)"
    cfg = "OK" if st.get("configured") else "FALTAN credenciales"
    connect_btn = (f"<a class='btn' href='/auth/tiktok/login?key={key}'>Conectar cuenta de TikTok</a>"
                   if not connected else
                   f"<a class='btn' href='/auth/tiktok/login?key={key}'>Reconectar</a>")
    post_block = ""
    if connected:
        post_block = f"""
        <h3>Publicar video de prueba (sandbox)</h3>
        <input id='vurl' placeholder='URL del .mp4 (dominio verificado)' value='{s.tiktok_test_video_url}' />
        <button class='btn' onclick='postTest()'>Publicar prueba</button>
        <pre id='out'></pre>
        <script>
        async function postTest() {{
          const out=document.getElementById('out'); out.textContent='Publicando...';
          try {{
            const r=await fetch('/api/tiktok/post-test',{{method:'POST',
              headers:{{'Content-Type':'application/json','X-Webhook-Secret':'{key}'}},
              body:JSON.stringify({{video_url:document.getElementById('vurl').value}})}});
            out.textContent=JSON.stringify(await r.json(),null,2);
          }} catch(e) {{ out.textContent='Error: '+e; }}
        }}
        </script>"""
    html = f"""<!doctype html><html lang=es><head><meta charset=utf-8>
    <meta name=viewport content='width=device-width,initial-scale=1'>
    <title>Automiq · TikTok</title>
    <style>
      body{{font-family:system-ui,Segoe UI,sans-serif;background:#0D1426;color:#EAF0FF;
        max-width:620px;margin:0 auto;padding:3rem 1.5rem;line-height:1.6}}
      h1{{font-size:1.6rem}} h3{{margin-top:2rem}}
      .card{{background:#142042;border:1px solid rgba(255,255,255,.08);border-radius:14px;
        padding:1.2rem 1.4rem;margin:1.2rem 0}}
      .btn{{display:inline-block;background:#2B5BE8;color:#fff;text-decoration:none;border:0;
        padding:.7rem 1.2rem;border-radius:9999px;font-size:.95rem;cursor:pointer;margin-top:.6rem}}
      .btn:hover{{background:#3B82F6}}
      input{{width:100%;padding:.6rem .8rem;border-radius:8px;border:1px solid rgba(255,255,255,.15);
        background:#0D1426;color:#EAF0FF;margin:.5rem 0}}
      pre{{background:#0D1426;border:1px solid rgba(255,255,255,.1);border-radius:8px;padding:1rem;
        overflow:auto;font-size:.8rem;white-space:pre-wrap}}
      .muted{{color:#8C97B5;font-size:.9rem}} code{{color:#3B82F6}}
    </style></head><body>
    <h1>Automiq · Publicador de TikTok</h1>
    <p class=muted>Integración con la Content Posting API para publicar contenido propio en la cuenta oficial de la marca.</p>
    <div class=card>
      <p>Estado: {badge}</p>
      <p class=muted>open_id: <code>{openid}</code><br>Sandbox: {sandbox}<br>Credenciales: {cfg}</p>
      {connect_btn}
    </div>
    <div class=card>{post_block or "<p class=muted>Conectá la cuenta para habilitar la publicación de prueba.</p>"}</div>
    </body></html>"""
    return HTMLResponse(html)


# ── Búsqueda web server-side para los agentes (Claude Code + MiniMax no tiene WebSearch) ──

@app.get("/api/search")
async def api_search(request: Request):
    """Búsqueda web real (Serper/Brave/Tavily) servida como texto. Los agentes la
    consultan con WebFetch (la tool WebSearch de Claude Code no anda con MiniMax).
    Auth por query param ?key= (WebFetch no puede mandar headers)."""
    s = get_settings()
    key = request.query_params.get("key", "")
    if not s.webhook_secret or not hmac.compare_digest(key, s.webhook_secret):
        return PlainTextResponse("no autorizado", status_code=401)
    q = (request.query_params.get("q", "") or "").strip()
    if not q:
        return PlainTextResponse("falta el parámetro q", status_code=400)
    try:
        n = max(1, min(int(request.query_params.get("n", "6")), 10))
    except Exception:
        n = 6
    from packs.automiq.tools.web_search import web_search
    results = await run_in_threadpool(web_search, q, n)
    if not results:
        return PlainTextResponse(
            f"Sin resultados para «{q}». (Búsqueda no configurada: falta "
            f"SERPER_API_KEY / BRAVE_API_KEY / TAVILY_API_KEY en el entorno.)")
    out = [f"# Resultados de búsqueda: {q}", ""]
    for i, r in enumerate(results, 1):
        out.append(f"{i}. {r.get('title','').strip()}")
        out.append(f"   URL: {r.get('url','').strip()}")
        if r.get("snippet"):
            out.append(f"   {r['snippet'].strip()}")
        out.append("")
    return PlainTextResponse("\n".join(out))


# ── MiniMax Video (Hailuo) — generación de video en la nube (reemplaza HeyGen/MPT) ──

@app.post("/api/video/test")
async def api_video_test(request: Request):
    """Crea una tarea de video (image-to-video). Body: {prompt, image_url?, model?, duration?, resolution?}.
    Devuelve task_id; consultar con GET /api/video/status?task_id=."""
    _verify_webhook_secret(request)
    from .integrations import minimax_video as mv
    if not mv.enabled():
        raise HTTPException(status_code=400, detail="MiniMax no configurado (sin MINIMAX_API_KEY)")
    try:
        body = await request.json()
    except Exception:
        body = {}
    prompt = (body or {}).get("prompt") or ""
    if not prompt.strip():
        raise HTTPException(status_code=400, detail="falta prompt")
    image_url = (body or {}).get("image_url") or None
    model = (body or {}).get("model") or mv.DEFAULT_MODEL
    duration = int((body or {}).get("duration") or 6)
    resolution = (body or {}).get("resolution") or "1080P"
    try:
        tid = await run_in_threadpool(mv.create_task, prompt, image_url, model, duration, resolution)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e)[:400])
    return {"ok": True, "task_id": tid}


@app.get("/api/video/status")
async def api_video_status(request: Request):
    _verify_webhook_secret(request)
    from .integrations import minimax_video as mv
    tid = request.query_params.get("task_id", "")
    if not tid:
        raise HTTPException(status_code=400, detail="falta task_id")
    try:
        return await run_in_threadpool(mv.status_with_url, tid)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e)[:400])


# ── Google Veo 3 — generación de video con créditos GCP (path principal TikTok) ──

@app.post("/api/veo/test")
async def api_veo_test(request: Request):
    """Crea una tarea de video Veo (image-to-video). Body: {prompt, image_url?, aspect_ratio?, negative_prompt?}.
    Devuelve operation; consultar con GET /api/veo/status?operation=."""
    _verify_webhook_secret(request)
    from .integrations import veo_video as veo
    if not veo.enabled():
        raise HTTPException(status_code=400,
                            detail="Veo no configurado (falta GOOGLE_SERVICE_ACCOUNT_JSON / credencial de Vertex)")
    try:
        body = await request.json()
    except Exception:
        body = {}
    prompt = (body or {}).get("prompt") or ""
    if not prompt.strip():
        raise HTTPException(status_code=400, detail="falta prompt")
    image_url = (body or {}).get("image_url") or None
    aspect = (body or {}).get("aspect_ratio") or "9:16"
    negative = (body or {}).get("negative_prompt") or ""
    try:
        op = await run_in_threadpool(veo.create_task, prompt, image_url, None, aspect, negative)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e)[:400])
    return {"ok": True, "operation": op}


@app.get("/api/veo/status")
async def api_veo_status(request: Request):
    _verify_webhook_secret(request)
    from .integrations import veo_video as veo
    op = request.query_params.get("operation", "")
    if not op:
        raise HTTPException(status_code=400, detail="falta operation")
    try:
        q = await run_in_threadpool(veo.query_task, op)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e)[:400])
    # No devolver el base64 gigante del video; sólo resumen.
    return {"done": q.get("done"), "has_video": bool(q.get("b64") or q.get("gcsUri")),
            "gcsUri": q.get("gcsUri"), "error": q.get("error")}


# ── Web (landing): aprobar el preview del web_optimizer → producción ──

@app.get("/api/web/deployments")
async def api_web_deployments(request: Request):
    """Último preview (para aprobar) + producción actual de la landing."""
    _verify_webhook_secret(request)
    s = get_settings()
    if not s.web_optimizer_configured:
        return {"configured": False}
    from .integrations.vercel_client import get_vercel_client, VercelError
    vc = get_vercel_client(s)
    out: Dict[str, Any] = {"configured": True}
    def _view(d):
        return {"url": f"https://{d.get('url')}" if d.get("url") else "",
                "created": d.get("created") or d.get("createdAt"), "uid": d.get("uid")}
    try:
        out["preview"] = _view(await run_in_threadpool(vc.latest_preview_deployment))
    except (VercelError, Exception) as e:
        out["preview"] = None
        out["preview_error"] = str(e)[:200]
    try:
        out["production"] = _view(await run_in_threadpool(vc.latest_production_deployment))
    except Exception:
        out["production"] = None
    return out


class WebReviewBody(BaseModel):
    review: str
    deployment: Optional[str] = None    # uid del preview reviewado (itera sobre él)
    regenerate: Optional[bool] = True   # False = sólo guardar la preferencia


@app.post("/api/web/review")
async def api_web_review(body: WebReviewBody, request: Request, background: BackgroundTasks):
    """Review del operador sobre un preview de la landing. Hace dos cosas:
    1. Guarda la review como preferencia PERMANENTE del web_optimizer (lección).
    2. (default) Regenera el preview aplicando la review SOBRE esa misma versión."""
    _verify_webhook_secret(request)
    review = (body.review or "").strip()
    if not review:
        raise HTTPException(status_code=400, detail="review vacía")
    from .integrations import memory_store as ms, tasks_store as ts
    try:
        ms.add_lesson("web_optimizer", review, kind="feedback", weight=2)
    except Exception as e:
        log.warning("web_review_lesson_failed", error=str(e)[:200])
    if not body.regenerate:
        return {"ok": True, "saved": True, "regenerating": False}

    run_id = str(uuid.uuid4())
    prompt = ("REVIEW del operador sobre el preview actual de la landing:\n"
              f"{review}\n\n"
              "Estás trabajando SOBRE la versión de ese preview (no de cero): aplicá la "
              "review tal cual — lo que pida mantener NO se toca, lo que pida cambiar/"
              "sacar se hace exactamente así.")
    ts.add_task("web_optimizer", f"Review de la landing: {review[:120]}", run_id)
    args: Dict[str, Any] = {"task_prompt": prompt, "force_global": True}
    if body.deployment:
        args["base_deployment"] = body.deployment.strip()

    async def _rev():
        from .integrations import tasks_store as ts2
        try:
            result = await _run_pack_agent("web_optimizer", args, run_id, "dashboard:review")
            ts2.update_task(run_id, "done", str(result)[:600] if result else "")
        except Exception as e:
            ts2.update_task(run_id, "error", str(e)[:600])

    background.add_task(_rev)
    return {"ok": True, "saved": True, "regenerating": True, "run_id": run_id}


@app.post("/api/web/promote")
async def api_web_promote(request: Request):
    """APRUEBA el preview del web_optimizer: lo promueve a PRODUCCIÓN.
    Body opcional: {deployment: "<url o id>"}; sin body promueve el último preview."""
    _verify_webhook_secret(request)
    s = get_settings()
    if not s.web_optimizer_configured:
        raise HTTPException(status_code=400, detail="Vercel no configurado (VERCEL_TOKEN/PROJECT)")
    from .integrations.vercel_client import get_vercel_client, VercelError
    vc = get_vercel_client(s)
    try:
        body = await request.json()
    except Exception:
        body = {}
    dep = ((body or {}).get("deployment") or "").strip()
    try:
        if not dep:
            d = await run_in_threadpool(vc.latest_preview_deployment)
            dep = f"https://{d.get('url')}" if d.get("url") else d.get("uid", "")
        out = await run_in_threadpool(vc.promote, dep)
    except (VercelError, Exception) as e:
        raise HTTPException(status_code=502, detail=str(e)[:300])
    log.info("web_promoted", deployment=dep)
    return {"ok": True, "promoted": dep, "output": out}


@app.post("/api/video/assemble")
async def api_video_assemble(request: Request):
    """Arma un short (ffmpeg) desde archivos del volume. Body: {clip: "/media/x.mp4",
    proofs: ["/media/y.jpg"], proof_dur?, upload_youtube?, title?}.
    Sirve para rearmar a mano un short cuya corrida falló."""
    _verify_webhook_secret(request)
    from .integrations import video_assembler as va
    try:
        body = await request.json()
    except Exception:
        body = {}
    def _local(ref: str) -> Optional[str]:
        if not ref:
            return None
        p = _data_dir() / "images" / Path(ref).name
        return str(p) if p.exists() else None
    clip = _local((body or {}).get("clip") or "")
    if not clip:
        raise HTTPException(status_code=400, detail="falta clip (usá /media/<file>.mp4 del volume)")
    proofs = [p for p in (_local(x) for x in (body or {}).get("proofs") or []) if p]
    dur = float((body or {}).get("proof_dur") or 5.0)
    url = await run_in_threadpool(va.assemble_short, clip, proofs, dur)
    if not url:
        raise HTTPException(status_code=502, detail="ffmpeg no pudo armar el video (ver logs)")
    out: Dict[str, Any] = {"ok": True, "url": url}
    if (body or {}).get("upload_youtube"):
        from .integrations import youtube_client as yt, publish_queue as pq
        title = ((body or {}).get("title") or "Automiq · IA para tu negocio")[:90] + " #Shorts"
        try:
            res = await run_in_threadpool(
                yt.upload_video, _local(url), title,
                f"{title}\n\n#Shorts #IA #automatizacion #pymes #argentina",
                ["IA", "automatizacion", "pymes", "argentina", "shorts"])
            pq.record_published(image=url, caption=title, target="youtube",
                                result={"ok": True, "id": res.get("id"),
                                        "permalink": res.get("url"),
                                        "privacy": res.get("privacy")}, source="api")
            out["youtube"] = res
        except Exception as e:
            out["youtube_error"] = str(e)[:300]
    return out


# ── Páginas legales / compliance (auditoría YouTube Data API) ──

@app.get("/privacy", response_class=HTMLResponse)
async def page_privacy():
    from . import legal
    return HTMLResponse(legal.privacy_html())


@app.get("/terms", response_class=HTMLResponse)
async def page_terms():
    from . import legal
    return HTMLResponse(legal.terms_html())


@app.get("/youtube", response_class=HTMLResponse)
async def page_youtube():
    from . import legal
    return HTMLResponse(legal.info_html())


# ── YouTube — subir Shorts del canal de Nazareno ──

@app.get("/api/youtube/status")
async def api_youtube_status(request: Request):
    _verify_webhook_secret(request)
    from .integrations import youtube_client as yt
    return await run_in_threadpool(yt.status)


@app.post("/api/youtube/upload")
async def api_youtube_upload(request: Request):
    """Sube un video al canal. Body: {file|url, title, description?, tags?, privacy?}.
    `file` = /media/<archivo>.mp4 (en el volume) o ruta local; `url` = se descarga."""
    _verify_webhook_secret(request)
    from .integrations import youtube_client as yt
    if not yt.enabled():
        raise HTTPException(status_code=400, detail="YouTube no configurado")
    try:
        body = await request.json()
    except Exception:
        body = {}
    title = (body or {}).get("title")
    if not title:
        raise HTTPException(status_code=400, detail="falta title")
    fileref = (body or {}).get("file") or ""
    url = (body or {}).get("url") or ""
    path = None
    if fileref:
        name = Path(fileref).name
        p = _data_dir() / "images" / name
        if p.exists():
            path = str(p)
    if not path and url:
        # descargar el mp4 al volume y subir desde ahí
        import httpx
        try:
            def _download() -> str:
                with httpx.Client(timeout=180, follow_redirects=True) as c:
                    r = c.get(url)
                    r.raise_for_status()
                d = _data_dir() / "images"
                d.mkdir(parents=True, exist_ok=True)
                p2 = d / f"yt_{uuid.uuid4().hex}.mp4"
                p2.write_bytes(r.content)
                return str(p2)
            path = await run_in_threadpool(_download)
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"no pude descargar el video: {str(e)[:200]}")
    if not path:
        raise HTTPException(status_code=400,
                            detail="archivo no encontrado (usá file=/media/<file>.mp4 del volume, o url=)")
    try:
        res = await run_in_threadpool(
            yt.upload_video, path, title, (body or {}).get("description") or "",
            (body or {}).get("tags") or [], (body or {}).get("privacy"))
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e)[:400])
    # Registrar en la sección Publicaciones del panel.
    try:
        from .integrations import publish_queue as pq
        pq.record_published(
            image=f"/media/{Path(path).name}", caption=title, target="youtube",
            result={"ok": True, "id": res.get("id"), "permalink": res.get("url"),
                    "privacy": res.get("privacy")},
            source="api")
    except Exception:
        pass
    return {"ok": True, **res}


# ── Mockups de chat (WhatsApp realista, render por código) ──

@app.post("/api/mockup/whatsapp")
async def api_mockup_whatsapp(request: Request):
    """Renderiza un chat de WhatsApp realista. Body: {business, subtitle?, messages:[{from,time,text}]}."""
    _verify_webhook_secret(request)
    from .integrations import chat_mockup
    try:
        body = await request.json()
    except Exception:
        body = {}
    business = (body or {}).get("business") or "Negocio"
    subtitle = (body or {}).get("subtitle") or "en línea"
    messages = (body or {}).get("messages") or []
    if not messages:
        raise HTTPException(status_code=400, detail="faltan messages")
    url = await run_in_threadpool(chat_mockup.render_whatsapp, business, messages, subtitle)
    if not url:
        raise HTTPException(status_code=502, detail="no se pudo renderizar")
    return {"ok": True, "url": url}


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page():
    html_path = Path(__file__).resolve().parent / "dashboard" / "index.html"
    if not html_path.exists():
        raise HTTPException(status_code=404, detail="dashboard no encontrado")
    return HTMLResponse(html_path.read_text(encoding="utf-8"))


@app.get("/favicon.ico")
async def favicon_ico():
    p = Path(__file__).resolve().parent / "dashboard" / "favicon.ico"
    if not p.exists():
        raise HTTPException(status_code=404, detail="no favicon")
    return FileResponse(str(p), media_type="image/x-icon")


@app.get("/favicon.png")
async def favicon_png():
    p = Path(__file__).resolve().parent / "dashboard" / "favicon.png"
    if not p.exists():
        raise HTTPException(status_code=404, detail="no favicon")
    return FileResponse(str(p), media_type="image/png")


@app.get("/")
async def root():
    return {
        "service": "automiq-agents",
        "version": __version__,
        "runtime": "hermes-pack",
        "dashboard": "/dashboard",
        "agents": "/agents",
        "last": "/last/{agent}",
        "health": "/healthz",
    }