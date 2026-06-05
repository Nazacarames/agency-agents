# Plan de Deploy a Render — Paso a Paso

> Documento vivo. Cada paso se marca con [OK] cuando se completa.

## Pre-requisitos verificados

- [OK] `agency-agents-render/` existe con 45 archivos, compilan limpio
- [OK] `MiniMax-M3` configurado como modelo principal
- [OK] NO está trackeado por el repo SAAS (0 files en `git ls-files`)
- [OK] Render API key disponible: `rnd_V8y7MiIAMtDpP84xRg66thH9P0WA` (de Agency-Operations-Manual.md)
- [OK] `curl` disponible, `jq` NO (uso Python en su lugar)
- [ ] `gh` CLI NO instalado — necesito decisión sobre cómo crear el repo GitHub
- [ ] `git user.name`/`user.email` globales NO configurados (usar repo-local)

---

## PASO 1 — Crear repo `Nazacarames/agency-agents` en GitHub

**Opciones:**

### Opción A — Vos lo creás manualmente (RECOMENDADO por simplicidad)
1. Ir a https://github.com/new
2. Repository name: `agency-agents`
3. Visibility: **Private** (tiene secrets)
4. NO inicializar con README/license/.gitignore
5. Click "Create repository"

### Opción B — Yo lo creo con API directa
- Necesito un GitHub Personal Access Token (PAT) con scope `repo`
- Comando:
  ```bash
  curl -X POST https://api.github.com/user/repos \
    -H "Authorization: token ghp_XXX" \
    -H "Accept: application/vnd.github+json" \
    -d '{"name":"agency-agents","private":true,"description":"Automiq agency agents (Hermes + MiniMax-M3) on Render"}'
  ```

### Opción C — Instalar `gh` CLI y autenticar
- `winget install --id GitHub.cli` (Windows)
- `gh auth login` (requiere browser interactivo — bloqueante en este entorno)

**Decisión recomendada: A** (vos lo creás, 30 segundos).

---

## PASO 2 — Inicializar git local + commit + push

```bash
cd ~/.openclaw/workspace/agency-agents-render

# Configurar user local (solo para este repo)
git config user.name "Automiq Agents"
git config user.email "agents@automiq.com.ar"

# Inicializar repo independiente
git init
git add .
git commit -m "feat: initial commit — Automiq agency agents on Render

- FastAPI + APScheduler + MiniMax-M3 + Discord webhook
- 8 agents ported from OpenClaw (leadhunter, content_creator, etc.)
- Dockerfile + render.yaml blueprint
- GitHub Actions CI/CD with deploy hook
- Tests with mocks (no API keys required)
- Docs: README, MIGRATION, AGENTS, INITIAL_PROMPT"

# Agregar remote
git remote add origin https://github.com/Nazacarames/agency-agents.git

# Push
git branch -M main
git push -u origin main
```

**Esto NO toca el repo SAAS** (carpeta independiente, sin `.git` parent).

---

## PASO 3 — Crear Web Service en Render via API

**Endpoint**: `POST https://api.render.com/v1/services`

**Body**:
```json
{
  "type": "web_service",
  "name": "automiq-agents",
  "ownerId": "<owner-id>",
  "repo": "https://github.com/Nazacarames/agency-agents",
  "branch": "main",
  "runtime": "docker",
  "dockerfilePath": "./Dockerfile",
  "dockerContext": ".",
  "plan": "free",
  "region": "oregon",
  "autoDeploy": true,
  "healthCheckPath": "/healthz"
}
```

**Para el `ownerId`**: lo saco de `GET /v1/owners` con tu API key.

---

## PASO 4 — Configurar env vars (sin commitear los valores)

**Endpoint**: `POST /v1/services/{serviceId}/env-vars`

```json
[
  {"key": "MINIMAX_API_KEY", "value": "<PEGAR ACÁ>"},
  {"key": "DISCORD_WEBHOOK_URL", "value": "<PEGAR ACÁ>"},
  {"key": "MINIMAX_MODEL_PRIMARY", "value": "MiniMax-M3"},
  {"key": "MINIMAX_MODEL_FALLBACKS", "value": "MiniMax-M2.5,MiniMax-M2.5-highspeed"},
  {"key": "SCHEDULER_ENABLED", "value": "true"},
  {"key": "GLOBAL_PAUSE", "value": "false"},
  {"key": "SCHEDULER_TIMEZONE", "value": "America/Buenos_Aires"},
  {"key": "WEBHOOK_SECRET", "value": "<PEGAR ACÁ>"},
  {"key": "LOG_LEVEL", "value": "INFO"}
]
```

**Necesito de vos (si los querés hardcodear ahora):**
- `MINIMAX_API_KEY` real (o lo configurás vos en el dashboard de Render después)
- `DISCORD_WEBHOOK_URL` real (idem)
- `WEBHOOK_SECRET` (puedo generar uno random y vos lo ves)

Si no me los pasás, los configuro como placeholders y vos los reemplazás en
el dashboard de Render.

---

## PASO 5 — Esperar primer deploy

- Render detecta el push y empieza a buildear
- Tarda 3-5 minutos (descarga imagen Python, pip install, etc.)
- Mientras tanto, yo voy a pollear el status

**Verificar**:
```bash
# Una vez deployed
curl https://automiq-agents.onrender.com/healthz
# → {"status":"ok",...}

curl https://automiq-agents.onrender.com/agents
# → lista de 8 agentes
```

---

## PASO 6 — Configurar keep-alive (UptimeRobot)

Para que el plan free no hiberne, configurar UptimeRobot (gratis):

1. Ir a https://uptimerobot.com → Sign up free
2. Add New Monitor:
   - Type: HTTP(s)
   - Friendly name: `automiq-agents`
   - URL: `https://automiq-agents.onrender.com/healthz`
   - Monitoring interval: **5 minutes**
3. Save

Esto le pega al servicio cada 5 min → Render NO lo duerme.

**Alternativa más simple**: GitHub Actions cron cada 5 min que haga
`curl $SERVICE_URL/healthz`. No requiere cuenta en UptimeRobot.

Lo agrego como workflow separado en `.github/workflows/keep-alive.yml`.

---

## Riesgos y rollback

- **Si algo falla en Render**: el servicio se puede borrar desde dashboard o
  via API (`DELETE /v1/services/{id}`). Rollback instantáneo.
- **Si el push a GitHub falla**: no pasa nada, los archivos quedan locales.
- **Si la API de Render devuelve error**: le muestro el error y frena.

---

## Estado actual

- [ ] PASO 1: repo GitHub
- [ ] PASO 2: git init + push
- [ ] PASO 3: crear Render service
- [ ] PASO 4: env vars
- [ ] PASO 5: esperar deploy + smoke test
- [ ] PASO 6: keep-alive (UptimeRobot o GitHub Action)
