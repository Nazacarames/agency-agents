# AGENTS.md — Guía operativa para sub-agentes Hermes que operen este servicio

> Si sos un sub-agente de Hermes y te pidieron operar este servicio, leé esto primero.

## ¿Qué es este repo?

`agency-agents-render/` es un wrapper Python que hostea los 8 agentes de Automiq
(agencia de automatización con IA para PyMEs argentinas). Reemplaza el gateway
local de OpenClaw. Corre 24/7 en Render como web service + Docker.

## Antes de tocar nada

1. **Leé el contexto**:
   - `README.md` — arquitectura y setup
   - `MIGRATION.md` — qué vino de OpenClaw y qué se reemplazó
   - `docs/INITIAL_PROMPT.md` — briefing original de la agencia

2. **No rompas los 8 agentes**: leadhunter, content_creator, growth_hacker,
   creative_strategist, social_media, outbound, media_auditor, seo_specialist.
   Si tenés que modificar uno, editá su archivo en `app/agents/<name>.py` y
   agregá tests.

3. **Formato de prompts**: usá español argentino (vos), evitá jerga, sé concreto.
   Cada agente tiene `system_prompt` (rol + reglas) y `build_user_message` (el trigger).
   Si modificás `system_prompt`, mantené la estructura: contexto de la agencia +
   instrucciones del agente.

## Estructura rápida

```
app/agents/         # 8 agentes + base + common
app/clients/        # minimax.py, discord.py
app/main.py         # FastAPI
app/scheduler.py    # APScheduler (reemplaza cron de OpenClaw)
app/container.py    # DI de clientes
app/config.py       # Settings
scripts/            # CLI tools
data/               # outputs generados (gitignored los runs)
docs/               # documentación
```

## Reglas operativas

1. **No tocar `app/config.py` para agregar secretos hardcoded** — usar `.env` o
   Render Environment.
2. **No agregar deps a `requirements.txt` sin justificación** — son líneas que
   se redeployan.
3. **Si modificás un prompt, agregá un test en `tests/`** que verifique que
   `build_user_message()` devuelve un string no vacío.
4. **No subir `data/leadhunter-*.md` generados al repo** — ya está en `.gitignore`.
5. **Discord webhook**: la URL tiene el secret del canal embebido. NO commitear.

## Comandos útiles

```bash
# Smoke test (verifica que importa bien)
python scripts/smoke_test.py

# Correr un agente localmente (requiere .env con API keys)
python scripts/run_agent.py leadhunter --no-discord

# Levantar la app
uvicorn app.main:app --reload --port 8000

# Compilar sin ejecutar
python -m compileall -q app/ scripts/

# Lint
ruff check app/
```

## Cuando algo falla

| Síntoma                          | Diagnóstico                              |
|----------------------------------|------------------------------------------|
| 401 al llamar a MiniMax          | `MINIMAX_API_KEY` mal o vacía            |
| Agente no se ejecuta a horario   | `SCHEDULER_ENABLED=false` o `GLOBAL_PAUSE=true` |
| Output no llega a Discord        | `DISCORD_WEBHOOK_URL` mal                 |
| 401 en webhook                   | `X-Webhook-Secret` no coincide           |
| Render service en "sleeping"     | Plan Free — upgrade a Starter            |
| Drift de horarios                | Normal, ±1min, no crítico                |

## Cosas que NO tenés que hacer

- ❌ Agregar `claude-mem`, `qmd`, o cualquier plugin de OpenClaw — son específicos
- ❌ Crear un bot Discord con `discord.py` — usar webhook, es más simple y suficiente
- ❌ Migrar `~/.openclaw/memory/main.sqlite` — los recuerdos no son transferibles
- ❌ Hardcodear API keys en el código
- ❌ Commitear `data/leadhunter-*.md` (ya está gitignored)
- ❌ Modificar `app/agents/registry.py` para hardcodear agentes — el auto-registro funciona
