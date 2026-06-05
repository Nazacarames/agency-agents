# Migración OpenClaw → Automiq Agents (Render)

> Mapping 1:1 de los componentes de OpenClaw a este nuevo servicio.
> El objetivo fue mantener los mismos outputs, schedules y agentes, pero
> cambiar la infraestructura para que viva 24/7 en la nube con Hermes/MiniMax-M3.

## Tabla de migración

| OpenClaw                                              | Nuevo equivalente                                       |
|-------------------------------------------------------|---------------------------------------------------------|
| `~/.openclaw/openclaw.json`                           | `app/config.py` (Settings, pydantic)                    |
| `~/.openclaw/gateway.cmd` (proceso local puerto 18789) | Render Web Service (Docker, puerto 8000)                |
| `~/.openclaw/cron/jobs.json` (8 jobs)                 | `app/scheduler.py` + `app/agents/*.py` (cada agente)    |
| `~/.openclaw/agents/main/agent/` (identidad)          | `app/agents/base.py` (BaseAgent) + `app/agents/_common.py` |
| `~/.openclaw/agents/main/qmd/` (memoria QMD)          | ❌ No migrado (específico de OpenClaw)                  |
| `~/.openclaw/memory/main.sqlite` (51 MB)              | ❌ No migrado (los recuerdos eran de OpenClaw)          |
| `~/.openclaw/discord/` (bot config)                   | `app/clients/discord.py` (webhook, no bot)              |
| `~/.openclaw/skills/` (symlinks a `~/.agents/skills/`) | `app/agents/*.py` (nativos, no symlinks)               |
| `~/.openclaw/credentials/`                            | `.env` + Render Environment                            |
| `~/.openclaw/flows/registry.sqlite`                   | ❌ No migrado (era registry de flujos visuales)         |
| `~/.openclaw/openclaw.json` (providers MiniMax)       | `app/clients/minimax.py` (cliente MiniMax-M3)           |
| `~/.openclaw/subagents/runs.json`                     | `logs/agent_runs.jsonl` (auditoría)                    |
| `workspace/agency/prompts/INITIAL_PROMPT.md`          | `docs/INITIAL_PROMPT.md` (sin cambios)                  |
| `workspace/agency/data/leadhunter-*.md`               | `data/leadhunter-*.md` (se siguen generando)            |
| `openclaw cron run <id>` (trigger manual)             | `POST /run/<agent>` con X-Webhook-Secret               |
| `openclaw cron list` (ver jobs)                       | `GET /scheduler/jobs`                                  |
| Discord bot con comandos                              | Discord webhook (entrega pasiva)                       |

## Los 8 agentes: de jobs JSON a clases Python

### Antes (OpenClaw `cron/jobs.json`)

```json
{
  "id": "b71c4285-3ef9-462c-ba00-cdabcd118fd8",
  "name": "Content Creator — Automiq",
  "schedule": {"kind": "cron", "expr": "0 13 * * 1,3,5"},
  "sessionTarget": "isolated",
  "payload": {
    "kind": "agentTurn",
    "message": "Sos el Content Creator de Automiq. ..."
  },
  "delivery": {"mode": "announce", "channel": "discord", "to": "user:761679574610214933"}
}
```

### Después (`app/agents/content_creator.py`)

```python
class ContentCreatorAgent(BaseAgent):
    name = "content_creator"
    description = "Genera 3 ideas de contenido listas para redes"
    schedule = "0 13 * * 1,3,5"   # Lun/Mié/Vie 13:00 ART
    timezone = "America/Buenos_Aires"

    @property
    def system_prompt(self) -> str:
        return f"{get_context_block()}\n\n{CONTENT_CREATOR_INSTRUCTIONS}"

    def build_user_message(self, ctx: AgentContext) -> str:
        return "..."
```

Ventajas:
- Type-safe (pydantic, mypy-friendly)
- Cada agente es testeable independientemente
- Prompts en archivos `.py` (versionables, con syntax highlight)
- Auto-registro por side-effect al importar

## Sistema de pause

OpenClaw usaba `agency/control.json` con flag `global_pause`.
Ahora se hace con env var `GLOBAL_PAUSE` (Render dashboard).
También se puede cambiar en runtime (próxima versión: endpoint `POST /pause`).

## Memory system

OpenClaw tenía 3 sistemas de memoria:
1. `claude-mem` plugin (short-term + long-term SQLite)
2. `memory-core` plugin (dreaming promotion)
3. QMD index (`.openclaw/agents/main/qmd/`)

**Decisión**: no se portaron. Eran específicos del modelo conversacional de OpenClaw
(que tenía sesiones largas con compresión). Este servicio es **stateless** entre runs:
cada agente recibe un prompt, ejecuta, entrega output, y se olvida.

Si se necesita memoria persistente:
- Corto plazo: `data/<agent>-state.json` con info útil entre runs
- Largo plazo: agregar Postgres o SQLite + un endpoint `/memory`

## Discord

OpenClaw: bot con `discord.js` + intents + slash commands. Requiere proceso persistente.
Nuevo: webhook. Limitación: solo entrega mensajes al canal asociado, no puede
recibir comandos. Para comandos interactivos, agregar:
- Bot Discord con `discord.py` en otro web service de Render
- O webhook receptor: Discord manda interacciones a `POST /discord/interactions`
  (más complejo, requiere firma criptográfica)

## MiniMax-M3 vs M2.7

OpenClaw usaba `minimax/MiniMax-M2.7` como primary.
Este servicio usa `MiniMax-M3` (el modelo nuevo de MiniMax, equivalente en
capacidades pero con mejor pricing). Fallbacks: M2.5, M2.5-highspeed.

Para volver a M2.7: cambiar `MINIMAX_MODEL_PRIMARY` en Render.

## Lo que NO se migró (y por qué)

| Componente                     | Por qué no se migró                                       |
|--------------------------------|-----------------------------------------------------------|
| `browser/` (921 MB)            | Caché del browser, regenerable                            |
| `npm/`, `tools/` (677 MB)      | Dependencias cacheadas                                    |
| `agents/main/qmd/` (522 MB)    | Índice vectorial de OpenClaw                              |
| `memory/main.sqlite` (51 MB)   | Recuerdos específicos de OpenClaw (no transferibles)      |
| `flows/registry.sqlite`        | Flows visuales de OpenClaw, no se usan en Hermes          |
| `delivery-queue/`, `completions/` | Colas de OpenClaw, ya no aplica                        |
| `exec-approvals.json`          | Approvals de comandos, no aplica a servicio headless      |
| `subagents/runs.json`          | Log de runs pasados (se reemplazó por JSONL en logs/)     |
| `cron/runs/*.jsonl` (logs)     | Log de runs (no aportan valor al nuevo servicio)          |
| `credentials/discord-*`        | Auth de Discord (ya no se usa bot)                        |
| `paperclip/` (workspace)       | Es el CRM, sigue funcionando aparte, no es parte de esto  |

## Próximos pasos sugeridos

1. Deployar a Render (15 min)
2. Configurar Discord webhook en el canal correcto
3. Disparar manualmente cada agente con `POST /run/<name>` para validar
4. Activar scheduler (`SCHEDULER_ENABLED=true`)
5. Verificar primera corrida de LeadHunter al día siguiente
6. Agregar monitoring (UptimeRobot o similar para `/healthz`)
