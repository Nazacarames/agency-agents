---
name: automiq-leadhunter
description: |
  Generador de leads B2B para PyMEs argentinas (manufactura, distribución,
  logística, inmobiliarias). Produce 10 leads/día con contacto verificado
  vía scraping de webs oficiales.
tags: [leads, b2b, scraping, argentina]
---

# automiq-leadhunter

Skill del pack `automiq`. Implementación: `packs/automiq/agents/leadhunter.py`.

## Invocación

```python
from packs.automiq import get_agent
run = get_agent("leadhunter")
output = run(ctx, args={"vertical": "logistica", "ciudad": "Buenos Aires"})
```

O vía HTTP:

```bash
curl -X POST https://automiq-agents.onrender.com/run/leadhunter \
  -H "X-Webhook-Secret: $WEBHOOK_SECRET" \
  -H "Content-Type: application/json" \
  -d '{"args": {"vertical": "logistica", "ciudad": "Buenos Aires"}}'
```

Ver `SKILL.md` completo en `packs/automiq/skills/leadhunter/SKILL.md`.
