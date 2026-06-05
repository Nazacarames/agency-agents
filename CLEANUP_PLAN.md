# Plan de limpieza de ~/.openclaw/ — 2026-06-04

## Diagnóstico

`~/.openclaw/` pesa ~4.7 GB. Casi todo es caché/runtime:
- `browser/`: 921M (caché del browser tool, regenerable)
- `agents/`: 522M (historial QMD, regenerable)
- `npm/`: 419M (cache npm, regenerable)
- `tools/`: 258M (caché de tools, regenerable)
- `memory/`: 51M (SQLite con recuerdos específicos, no transferibles)
- `workspace/`: 2.4G (el repo de la agencia, NO TOCAR — ya migramos lo importante)

## Lo que se BORRARÍA (caché puro, regenerable)

| Carpeta | Tamaño | Por qué se puede borrar |
|---------|--------|--------------------------|
| `browser/` | 921M | Caché del browser tool |
| `agents/main/qmd/` | ~500M | Índice vectorial de OpenClaw |
| `npm/` | 419M | Cache de npm |
| `tools/` | 258M | Caché de tools |
| `media/` | 3.8M | Archivos generados |
| `completions/` | 456K | Autocomplete de OpenClaw |
| `delivery-queue/` | 457K | Cola de mensajes de OpenClaw |
| `session-delivery-queue/` | 0 | Vacío |
| `canvas/` | 2.2M | Snapshots visuales de OpenClaw |
| `tasks/` | 4.7M | Tareas ya procesadas |
| `flows/` | 4M | Registry de flows visuales |
| `logs/` | 66K | Logs viejos |
| `plugins/installs.json` | 132K | Manifest de plugins instalados |
| `subagents/runs.json` | 8K | Log de runs pasados |
| `qqbot/` | 0 | Vacío, servicio no usado |
| `plugin-skills/` | 0 | Vacío |
| `extensions/` | 21K | Extensiones OpenClaw |
| `cron/runs/*.jsonl` | ~3M | Logs de runs de cron |

Total a liberar: **~2.1 GB** de basura pura

## Lo que se PRESERVARÍA (configs, secrets, datos de valor)

| Archivo/carpeta | Por qué se preserva |
|-----------------|----------------------|
| `openclaw.json` | Config de tu setup original, referencia |
| `openclaw.json.last-good` | Última config funcional |
| `.env` | Tiene OPENAI_API_KEY, no se borra |
| `exec-approvals.json` | Approvals de comandos |
| `update-check.json` | Estado de updates |
| `credentials/discord-*.json` | Auth de Discord |
| `cron/jobs.json` | Los 8 jobs originales (referencia histórica) |
| `cron/jobs-state.json` | Estado de los jobs |
| `agents/main/agent/` | Config del agente main |
| `identity/device.json` | Identidad del device |
| `identity/device-auth.json` | Auth del device |
| `discord/` | Config Discord |
| `skills/` (symlinks) | Symlinks a skills de Hermes |
| `workspace/` | **TODO** — el repo, no se toca |
| `devices/` | Estado de devices |

## Lo que se MUEVE (backups de seguridad)

Antes de borrar nada, voy a hacer un tar.gz con todo `~/.openclaw/` a
`~/openclaw-backup-2026-06-04.tar.gz` por si algo se rompe.

## Riesgos

- Si borro `cron/runs/*.jsonl` no pierdo info útil (son logs)
- Si borro `flows/registry.sqlite` y OpenClaw lo necesita después, se regenera
- Si borro `agents/main/qmd/` no afecta a Hermes (que tiene sus propias skills)
- Si borro el `cache/npm` se regenera con `npm install`
- **Si borro `memory/main.sqlite` se pierden los recuerdos de OpenClaw** —
  no son transferibles, pero ya no los necesitamos

## Lo que NO se hace automáticamente

- NO se borra `openclaw.json` ni `.env` (referencia + secretos)
- NO se borra `workspace/` (el repo)
- NO se borra `cron/jobs.json` (histórico, está en GitHub via el código nuevo)
- NO se borra `credentials/` (auth, por si hay que referenciar)

## Orden de ejecución (cuando me autorices)

1. Crear backup tar.gz en `~/openclaw-backup-2026-06-04.tar.gz`
2. Borrar las carpetas listadas arriba (caché puro)
3. Borrar archivos individuales listados arriba
4. Verificar que `~/.openclaw/` quedó con solo configs/credenciales/repo
5. Reportar tamaño final y qué quedó

Espero tu OK.
