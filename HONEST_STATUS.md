# Lo que SÍ puedo prometer vs lo que NO — 2026-06-04

## Lo que SÍ puedo hacer esta noche

1. **Instalar el CLI de Render** y usarlo para crear el Web Service (con tu API key).
2. **Configurar env vars** (con placeholders por secretos, vos los completás en dashboard).
3. **Eliminar/limpiar lo de OpenClaw** en `~/.openclaw/` que ya no sirve.
4. **Ordenar la carpeta de la agencia** (mover/reorganizar `agency/` y cosas relacionadas).
5. **Push a GitHub** de los cambios finales.
6. **Tests del código** (compile + los tests pytest con mocks).
7. **Armar keep-alive** con GitHub Actions (cron cada 5 min que pegue al /healthz).
8. **Verificar el primer deploy** y el endpoint `/healthz`.

## Lo que NO puedo prometer (y por qué)

### "Mañana quiero reportes de leads 10/10 sin fallas"

- **El primer run de LeadHunter puede fallar** porque depende de:
  - Que vos pongas la `MINIMAX_API_KEY` real en Render (yo no la tengo)
  - Que pongas la `DISCORD_WEBHOOK_URL` real (idem)
  - Que M3 esté disponible con el rate limit que tiene tu plan
  - Que M3 devuelva 10 leads con contacto REAL (no fabricaré resultados)
- **Si el primer run falla, NO voy a simular un reporte exitoso**. Te voy a
  reportar el error exacto.
- **El "calidad 10/10" no es determinístico**: depende del modelo, de los
  prompts, y de si M3 encuentra contactos reales para 10 empresas argentinas
  distintas. Si la búsqueda falla, fallamos honestamente.

### "Eliminar todo lo de OpenClaw"

- **Voy a eliminar selectivamente**: configs, logs, runs viejos, plugins de
  Discord, etc.
- **NO voy a eliminar `~/.openclaw/openclaw.json` ni `~/.openclaw/.env`** sin
  tu confirmación explícita, porque pueden tener credenciales tuyas que
  necesites migrar manualmente a otra parte.
- **NO voy a `rm -rf ~/.openclaw/`**. Si tenés algo útil ahí (como la sesión
  de Discord, los QMD index, etc.) perderías cosas que no se pueden recuperar.

### "Ordenar bien la carpeta de la agencia"

- **Sí**: voy a consolidar `agency-agents-render/` con la estructura limpia.
- **NO** voy a reorganizar `~/.openclaw/workspace/agency/` (la carpeta de la
  agencia con todos los scripts existentes) sin tu OK explícito, porque ahí
  tenés `data/leadhunter-report-*.md` con info de clientes reales.

### "Sin fallas" / "10/10"

- **No existe el software 10/10 sin fallas**. Lo que sí puedo prometer es:
  - El código compila y los tests pasan (verificable)
  - El deploy llega a buen puerto
  - El /healthz responde 200
  - Los endpoints están listos
  - Si algo falla, te lo digo con el error exacto

## Plan para esta noche

Voy a marcar las cosas con checks a medida que las complete y voy a actualizar
este archivo. Si en algún momento algo se rompe, te aviso y frenamos.

### Fases

1. [ ] Instalar Render CLI
2. [ ] Validar API key con `render whoami`
3. [ ] Crear Web Service con `render services create`
4. [ ] Pushear cambios (DEPLOY_STATUS, scripts, etc.)
5. [ ] Esperar primer deploy
6. [ ] Verificar `/healthz`, `/agents`, `/docs`
7. [ ] Trigger manual de LeadHunter (`/run/leadhunter`) y ver el output
8. [ ] Configurar keep-alive workflow
9. [ ] Limpiar `~/.openclaw/` (selectivo, no destructivo)
10. [ ] Consolidar `agency-agents-render/` con el resto
11. [ ] Reporte final con todo lo hecho

## Si me trabo en algo

- Te aviso con el error exacto
- Te pregunto la decisión
- NO simulo éxito
- NO dejo nada "como si anduviera" sin verificar

Empiezo ya.
