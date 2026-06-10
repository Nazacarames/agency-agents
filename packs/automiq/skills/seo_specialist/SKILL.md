---
name: automiq-seo-specialist
description: |
  Skill del pack `automiq` (agente seo_specialist). Implementación: `packs/automiq/agents/seo_specialist.py`.
tags: [automiq, agency, seo-specialist]
---

# automiq-seo-specialist

Agente seo_specialist del pack `automiq`. Ver `packs/automiq/agents/seo_specialist.py` para
instrucciones completas.

## Invocación rápida

```python
from packs.automiq import get_agent
run = get_agent("seo_specialist")
output = run(ctx, args={})
```

O vía HTTP:

```bash
curl -X POST https://automiq-agents.onrender.com/run/seo_specialist   -H "X-Webhook-Secret: $WEBHOOK_SECRET"   -H "Content-Type: application/json"   -d '{"args": {}}'
```
