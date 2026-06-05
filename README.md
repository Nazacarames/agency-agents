# Automiq Agency Agents — Render Service

> Wrapper Python con FastAPI + APScheduler + MiniMax-M3 que reemplaza el gateway local
> de OpenClaw. Corre 24/7 en Render y entrega los outputs de los 8 agentes de Automiq
> a Discord vía webhook.

## ¿Qué es esto?

La agencia Automiq (manufacturing/distribución/logística, PyMEs familiares argentinas)
corre **8 agentes** que generan contenido, leads, secuencias outbound, audits y planes
de growth. Antes esto lo manejaba un gateway local de OpenClaw + cron jobs. Ahora vive
en Render como un web service, agendado con APScheduler, y los prompts van a
**MiniMax-M3** (con fallback a M2.5 / M2.5-highspeed).

## Arquitectura

```
┌─────────────────┐    cron trigger    ┌──────────────────┐
│  APScheduler    │ ──────────────────▶│   BaseAgent      │
│  (8 jobs, ART)  │                    │  + system_prompt │
└─────────────────┘                    └────────┬─────────┘
                                                │ HTTP POST
                                                ▼
                                    ┌──────────────────────┐
                                    │   MiniMax-M3 API     │
                                    │ (api.minimax.io/     │
                                    │  anthropic)          │
                                    └────────┬─────────────┘
                                             │ response
                                             ▼
                                    ┌──────────────────────┐
                                    │  Discord Webhook     │
                                    │  → canal de NAZA     │
                                    └──────────────────────┘
                                             ▲
                                    ┌────────┴─────────────┐
                                    │ FastAPI endpoints    │
                                    │  /run/<agent>        │
                                    │  /webhook/lead       │
                                    └──────────────────────┘
```

## Estructura

```
agency-agents-render/
├── app/
│   ├── main.py                 # FastAPI app + endpoints
│   ├── config.py               # Settings tipadas
│   ├── container.py            # DI: MiniMax + Discord clients
│   ├── scheduler.py            # APScheduler wrapper
│   ├── log.py                  # structlog + JSON-lines
│   ├── clients/
│   │   ├── minimax.py          # Cliente MiniMax-M3 (Anthropic API)
│   │   └── discord.py          # Cliente Discord (webhook)
│   └── agents/
│       ├── base.py             # BaseAgent abstract class
│       ├── _common.py          # Contexto compartido (AGENCY_CONTEXT)
│       ├── registry.py         # Auto-registro
│       ├── leadhunter.py       # #1 - 10 leads/día
│       ├── content_creator.py  # #4 - 3 ideas de contenido
│       ├── growth_hacker.py    # #3 - métricas + quick wins
│       ├── creative_strategist.py  # #2 - ads Meta + headlines
│       ├── social_media.py     # #5 - calendario semanal
│       ├── outbound.py         # #6 - secuencias B2B
│       ├── media_auditor.py    # #7 - audit mensual ads
│       └── seo_specialist.py   # #8 - plan SEO mensual
├── data/
│   ├── prompts/                # Prompts originales de OpenClaw (referencia)
│   ├── samples/                # Reportes reales de ejemplo
│   └── leadhunter-*.md         # Generados por el agente (gitignored)
├── docs/
│   └── INITIAL_PROMPT.md       # Briefing de la agencia
├── scripts/
│   ├── smoke_test.py           # Verifica que la app carga sin secrets
│   └── run_agent.py            # CLI: corre un agente bajo demanda
├── tests/                      # (pendiente)
├── logs/                       # JSON-lines con auditoría de runs
├── Dockerfile
├── render.yaml                 # Blueprint para Render
├── requirements.txt
├── pyproject.toml              # ruff config
├── .env.example
├── .github/workflows/deploy.yml
└── README.md
```

## Los 8 agentes

| # | Agente              | Schedule (ART)        | Output principal                         |
|---|---------------------|-----------------------|------------------------------------------|
| 1 | `leadhunter`        | diario 09:00          | 10 leads con contacto verificado         |
| 2 | `content_creator`   | Lun/Mié/Vie 13:00     | 3 ideas de contenido para IG/FB          |
| 3 | `growth_hacker`     | diario 14:00          | Reporte de métricas + quick wins         |
| 4 | `creative_strategist` | Mar/Jue 14:00       | 3 variantes ads Meta + 5 headlines       |
| 5 | `social_media`      | Domingo 18:00         | Calendario semanal IG + FB               |
| 6 | `outbound`          | Lunes 10:00           | Secuencia B2B WhatsApp + Email + LI      |
| 7 | `media_auditor`     | día 1 de cada mes 11:00 | Audit mensual de Meta + Google Ads    |
| 8 | `seo_specialist`    | día 15 de cada mes 11:00 | Plan SEO: keywords + contenido + on-page |

## Setup local (sin Render)

```bash
# 1. Clonar e instalar
cd ~/.openclaw/workspace/agency-agents-render
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt

# 2. Configurar
cp .env.example .env
# Editar .env y poner:
#   - MINIMAX_API_KEY
#   - DISCORD_WEBHOOK_URL
#   - WEBHOOK_SECRET (un string aleatorio largo)

# 3. Smoke test (sin credenciales)
python scripts/smoke_test.py

# 4. Correr la app
uvicorn app.main:app --reload --port 8000
# → http://localhost:8000/docs (Swagger)
# → http://localhost:8000/healthz
# → http://localhost:8000/agents
```

## Setup en Render

### 1. Crear el servicio

Opción A — Blueprint (recomendado):
1. Push este repo a GitHub
2. Render dashboard → **New** → **Blueprint**
3. Conectá el repo → Render lee `render.yaml` y crea todo

Opción B — Manual:
1. Render dashboard → **New** → **Web Service**
2. Conectá el repo
3. Runtime: **Docker**
4. Dockerfile path: `./Dockerfile`
5. Plan: **Starter** ($7/mes — necesario para que el scheduler no se duerma)
6. Region: Oregon

### 2. Variables de entorno

Configurá en Render → Environment:

| Variable                   | Valor                                          |
|----------------------------|------------------------------------------------|
| `MINIMAX_API_KEY`          | Tu API key de minimax                          |
| `DISCORD_WEBHOOK_URL`      | Webhook del canal de NAZA                      |
| `WEBHOOK_SECRET`           | Generar con `python -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `SCHEDULER_ENABLED`        | `true`                                          |
| `GLOBAL_PAUSE`             | `false`                                         |
| `SCHEDULER_TIMEZONE`       | `America/Buenos_Aires`                         |

Render auto-detecta: `PORT`, `RENDER_SERVICE_ID`, `RENDER_EXTERNAL_URL`.

### 3. GitHub Actions → deploy hook

Para que cada push a `main` redeploy + smoke test:

1. Render → service → Settings → **Deploy Hook** → copiá la URL
2. GitHub repo → Settings → Secrets → `RENDER_DEPLOY_HOOK` = esa URL
3. (Opcional) Settings → Variables → `RENDER_SERVICE_URL` = `https://automiq-agents.onrender.com`

Cada push a main:
1. GitHub Actions corre ruff + valida render.yaml
2. Llama al deploy hook
3. Render rebuild + redeploy
4. Actions espera 30s y hace `GET /healthz`

## Endpoints

| Método | Path                    | Auth                | Descripción                            |
|--------|-------------------------|---------------------|----------------------------------------|
| GET    | `/healthz`              | no                  | Healthcheck (Render lo usa)            |
| GET    | `/`                     | no                  | Info básica                            |
| GET    | `/agents`               | no                  | Lista de los 8 agentes                 |
| GET    | `/agents/{name}`        | no                  | Detalle de un agente                   |
| GET    | `/scheduler/jobs`       | no                  | Próximas ejecuciones                   |
| POST   | `/run/{name}`           | X-Webhook-Secret    | Dispara un agente (async o sync)       |
| POST   | `/webhook/lead`         | X-Webhook-Secret    | Recibe lead del form, dispara enrichment |
| GET    | `/docs`                 | no                  | Swagger UI                             |

### Ejemplo: disparar LeadHunter

```bash
curl -X POST https://automiq-agents.onrender.com/run/leadhunter \
  -H "X-Webhook-Secret: $WEBHOOK_SECRET" \
  -H "Content-Type: application/json" \
  -d '{"async_run": true, "args": {"vertical": "manufacturing"}}'
```

### Ejemplo: webhook de lead

```bash
curl -X POST https://automiq-agents.onrender.com/webhook/lead \
  -H "X-Webhook-Secret: $WEBHOOK_SECRET" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Juan Pérez",
    "email": "juan@empresa.com.ar",
    "company": "Empresa S.A.",
    "phone": "+5491155555555",
    "message": "Necesito automatizar mi proceso de pedidos",
    "source": "landing"
  }'
```

## Pausar todo

Para frenar todos los agentes sin redeployar:
- Render dashboard → Environment → `GLOBAL_PAUSE` = `true` → Save (redeploy automático)

O desde un trigger:
```bash
# (no hay endpoint de pause; agregar si hace falta)
```

## Migración desde OpenClaw

Ver [`MIGRATION.md`](MIGRATION.md) para el mapping detallado de cada componente.

## Costos

- Render Starter: $7/mes
- MiniMax-M3: ~$0.30/$1.20 por millón tokens input/output (mucho más barato que Claude Opus)
- 8 agentes/día × ~30 días × ~10k tokens out c/u ≈ 2.4M tokens out/mes ≈ **$2.88/mes**
- Total estimado: **~$10/mes** corriendo full

## Limitaciones conocidas

- **Discord**: solo webhook (no bot). Para bots con slash commands, se necesita
  un proceso persistente con `discord.py` y otro puerto. No es trivial en Render free tier.
- **Scheduler accuracy**: ±1 minuto de drift en horarios no críticos. Para precisión de
  segundos usar Render Cron Jobs externos.
- **No hay memoria persistente entre runs** más allá de los archivos en `data/`.
  El `MEMORY.md` de Hermes y el `claude-mem` plugin de OpenClaw no se portaron
  (eran específicos de OpenClaw). Si hace falta, agregar un endpoint `/memory` que
  use SQLite.

## Próximos pasos

- [ ] Tests (pytest) con mocks de MiniMax + Discord
- [ ] Métricas Prometheus
- [ ] Rate limiting por agente
- [ ] Webhook entrante de WhatsApp (Baileys/Evolution API)
- [ ] Persistencia de runs en Postgres (en vez de archivos JSONL)
