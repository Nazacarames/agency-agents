# Reporte Final — Deploy Automiq Agents
## 2026-06-04 ~02:15 ART

## ✅ Lo que se hizo esta noche

### 1. Código completo en GitHub
- Repo: https://github.com/Nazacarames/agency-agents (privado)
- 47 archivos pusheados, branch main
- Commit: incluye app/, tests, docs, Dockerfile, render.yaml, GitHub Actions
- **MiniMax-M3** configurado como modelo principal de los 8 agentes

### 2. Render CLI instalado
- Versión: v2.19.0
- Ubicación: `~/.local/bin/render.exe`
- PATH actualizado

### 3. Keep-alive workflow listo
- Archivo: `.github/workflows/keep-alive.yml`
- Cron cada 5 min: `*/5 * * * *`
- Solo necesita que vos configures la variable `RENDER_SERVICE_URL` en GitHub
- Después de crear el service, anda a:
  https://github.com/Nazacarames/agency-agents/settings/variables/actions
  y agregá: `RENDER_SERVICE_URL` = `https://automiq-agents.onrender.com`

### 4. Inventario de `~/.openclaw/`
- Total: ~4.7 GB
- Cache/runs/logs a borrar: ~2.1 GB (lista detallada en CLEANUP_PLAN.md)
- **Backup no hecho todavía — esperé tu OK**

## ❌ Lo que NO se pudo hacer (limitaciones reales)

### Crear el Web Service en Render
**Por qué**: La API key `rnd_...` que me pasaste autentica para:
- ✅ `GET /v1/owners` (200)
- ✅ `GET /v1/services` (200)  
- ✅ `GET /v1/blueprints` (200)
- ✅ `GET /v1/projects` (200)
- ❌ `POST /v1/services` (401 unauthorized)
- ❌ `render whoami` con CLI (unauthorized)

**Diagnóstico**: La key funciona para LECTURA pero NO para ESCRITURA de services. Es un token de solo lectura. Para crear el service, **necesitás una API Key estándar del dashboard de Render con scope de escritura**, o hacerlo manualmente desde el dashboard.

## 🎯 Lo que necesitás hacer vos (10-15 min total)

### Paso 1: Crear Web Service en Render (5 min)
1. https://dashboard.render.com/select-repo?type=web
2. Buscar y conectar: `Nazacarames/agency-agents`
3. Configurar el form con estos valores EXACTOS:
   - **Name**: `automiq-agents`
   - **Region**: Oregon
   - **Branch**: main
   - **Runtime**: Docker
   - **Dockerfile path**: `./Dockerfile`
   - **Docker context**: `.`
   - **Plan**: Free
   - **Health check path**: `/healthz`
   - **Auto-deploy**: Yes
4. Click "Create Web Service"
5. Esperar 3-5 min a que termine el primer deploy

### Paso 2: Configurar env vars (3 min)
Ir a Environment del service y agregar:

| Key | Value |
|-----|-------|
| `MINIMAX_MODEL_PRIMARY` | `MiniMax-M3` |
| `MINIMAX_MODEL_FALLBACKS` | `MiniMax-M2.5,MiniMax-M2.5-highspeed` |
| `MINIMAX_API_KEY` | *(la key real de MiniMax que uses)* |
| `DISCORD_WEBHOOK_URL` | *(la URL real del webhook de Discord)* |
| `SCHEDULER_ENABLED` | `true` |
| `GLOBAL_PAUSE` | `false` |
| `SCHEDULER_TIMEZONE` | `America/Buenos_Aires` |
| `WEBHOOK_SECRET` | *(generar uno random, ej: `openssl rand -hex 32`)* |
| `LOG_LEVEL` | `INFO` |

### Paso 3: Trigger manual de redeploy (1 min)
Para que tome las env vars, ir a Manual Deploy → Deploy latest commit.

### Paso 4: Verificar (1 min)
Abrir en el browser:
- `https://automiq-agents.onrender.com/healthz` → debe dar `{"status":"ok"}`
- `https://automiq-agents.onrender.com/agents` → debe listar 8 agentes
- `https://automiq-agents.onrender.com/docs` → Swagger UI

### Paso 5: Trigger LeadHunter (1 min)
```bash
curl -X POST https://automiq-agents.onrender.com/run/leadhunter \
  -H "X-Webhook-Secret: <tu_webhook_secret>" \
  -H "Content-Type: application/json" \
  -d '{"async_run": true, "args": {}}'
```
Recibirás un `run_id`. El output llega a Discord en 1-3 min.

### Paso 6: Activar keep-alive (1 min)
1. https://github.com/Nazacarames/agency-agents/settings/variables/actions
2. New variable: `RENDER_SERVICE_URL` = `https://automiq-agents.onrender.com`
3. Save

## 📋 Lo que va a pasar cuando el service esté creado

Mañana 9 AM ART, **LeadHunter corre automáticamente** (schedule: `0 9 * * *`).
El output llega al Discord de NAZA. La agencia ya está migrada a Hermes + M3.

## 🗑️ Limpieza de OpenClaw (pendiente tu OK)

Tengo el plan listo en `CLEANUP_PLAN.md` (borraría 2.1 GB de caché). NO toqué nada.
Cuando me autorices:
1. Backup tar.gz a `~/openclaw-backup-2026-06-04.tar.gz`
2. Borrar las carpetas de cache listadas
3. Dejar solo configs/credenciales/repo

## 💡 Si querés que termine el deploy automático

Generá una **nueva API Key** desde https://dashboard.render.com/u/settings/api-keys
con scope de escritura completa, y pasámela. Si esa anda con el CLI,
sigo yo con `render services create` y todo el deploy.

## 📂 Archivos importantes que dejé

En `C:\Users\Administrator\.openclaw\workspace\agency-agents-render\`:
- `README.md` — setup completo
- `MIGRATION.md` — qué vino de OpenClaw
- `AGENTS.md` — guía operativa
- `HONEST_STATUS.md` — este reporte
- `DEPLOY_PLAN.md` — plan de deploy
- `DEPLOY_STATUS.md` — status detallado
- `CLEANUP_PLAN.md` — plan de limpieza
- `Dockerfile`, `render.yaml`, `requirements.txt` — deploy
- `app/` — 8 agentes + base + scheduler
- `tests/` — tests con mocks
- `docs/INITIAL_PROMPT.md` — briefing de la agencia

Todo commiteado y pusheado a GitHub.

---

**Estoy parado acá esperando. Cuando hagas los pasos 1-6 (o me pases una key con scope completo), sigo yo con la verificación end-to-end y el cleanup de OpenClaw.**
