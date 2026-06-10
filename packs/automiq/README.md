# Pack `automiq` — los 8 agentes de Automiq como skills de Hermes

Este pack contiene los 8 agentes originales del repo OpenClaw
(leadhunter, content_creator, growth_hacker, creative_strategist,
social_media, outbound, media_auditor, seo_specialist), reempaquetados
como **skills de Hermes**.

Cada agente vive en `packs/automiq/skills/<name>/` y tiene:

- `SKILL.md` — instrucciones para Hermes (rol, reglas, formato de output)
- `agent.py` — código Python ejecutable que implementa `run(ctx, args) -> str`
- `tools.py` (opcional) — tools específicas del agente

Hermes auto-descubre las skills al arrancar desde `~/.hermes/skills/`
(que mapea a `packs/automiq/skills/`).

Los agentes son invocables por:
- Hermes CLI: `hermes skill automiq/leadhunter` (o similar)
- HTTP gateway: `POST /run/leadhunter` con `X-Webhook-Secret`
- ACP server: `agent_run` con nombre del agente
- Cron del gateway: archivo `gateway.yml` con schedules
