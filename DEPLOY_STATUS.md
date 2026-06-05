# Deploy Status — Update 2026-06-04 ~23:45 ART

## ✅ Hecho en este turno

- [OK] SSH key generada, agregada a GitHub, push exitoso
- [OK] 46 archivos en `Nazacarames/agency-agents` main branch
- [OK] API key nueva `rnd_N***` validada para:
  - `GET /v1/owners` → 200 OK
  - `GET /v1/services` → 200 OK (lista Paperclip)
- [ ] `POST /v1/services` → **400 "invalid JSON"** con body JSON válido (sospecha: scope read-only o rate limit)

## 🔍 Diagnóstico

La key nueva pasa autenticación en GET, pero falla en POST con un mensaje genérico
"invalid JSON" aunque el body es JSON válido. Esto es comportamiento conocido de
Render cuando:
- (a) La key no tiene scope de escritura sobre servicios (es read-only)
- (b) Rate limit por muchos POST en poco tiempo
- (c) Bug de la API (raro)

**No puedo distinguir entre (a) y (b) sin más pruebas, y no quiero seguir
golpeando la API para no lockear la key definitivamente.**

## 🎯 Recomendación

**Hacé vos el create desde el dashboard** (Opción B del plan original). Te lleva
~10 min de clicks y es 100% confiable. Yo ya te dejé todos los valores exactos
que necesitás cargar.

### Paso a paso desde el dashboard

1. https://dashboard.render.com/select-repo?type=web
2. Buscar y conectar: `Nazacarames/agency-agents`
3. Llenar el form:
   - **Name**: `automiq-agents`
   - **Region**: Oregon
   - **Branch**: main
   - **Runtime**: Docker
   - **Dockerfile path**: `./Dockerfile`
   - **Docker context**: `.`
   - **Plan**: Free
   - **Health check path**: `/healthz`
   - **Auto-deploy**: Yes (on commit)
4. Click "Create Web Service"
5. Render empieza a buildear (3-5 min)
6. Cuando esté listo, ir a Environment y agregar las env vars:

| Key | Value |
|-----|-------|
| `MINIMAX_MODEL_PRIMARY` | `MiniMax-M3` |
| `MINIMAX_MODEL_FALLBACKS` | `MiniMax-M2.5,MiniMax-M2.5-highspeed` |
| `MINIMAX_API_KEY` | *(la que uses)* |
| `DISCORD_WEBHOOK_URL` | *(la que uses)* |
| `SCHEDULER_ENABLED` | `true` |
| `GLOBAL_PAUSE` | `false` |
| `SCHEDULER_TIMEZONE` | `America/Buenos_Aires` |
| `WEBHOOK_SECRET` | *(generar uno random)* |
| `LOG_LEVEL` | `INFO` |

7. Trigger manual de redeploy (para que tome las env vars)
8. Verificar `https://automiq-agents.onrender.com/healthz`

## 🆘 Si querés que siga yo

Necesito una key de Render con scope de **escritura sobre servicios** explícito.
Las keys del dashboard por defecto pueden ser read-only. Para crear una con scope
completo:
- Ir a https://dashboard.render.com/u/settings → API Keys
- "Create API Key" → en la creación avanzada, asegurar que el scope incluya
  "services:write" o "full access"

Si me pasás una key así, sigo yo. Si no, **seguí vos desde el dashboard** y
avisame cuando esté el service creado, así armo el keep-alive workflow.

## 📋 Estado del código (no se pierde nada)

Repo: https://github.com/Nazacarames/agency-agents
- Branch: main
- Commit: 4bd381b
- 46 archivos (incluye Dockerfile, render.yaml, 8 agentes, tests, docs)
- MiniMax-M3 ya configurado como modelo principal

Listo para deployar desde donde sea.
