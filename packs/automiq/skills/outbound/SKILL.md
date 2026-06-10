---
name: automiq-outbound
description: |
  Skill del pack `automiq` (agente outbound). Implementación: `packs/automiq/agents/outbound.py`.
tags: [automiq, agency, outbound]
---

# automiq-outbound

Agente outbound del pack `automiq`. Ver `packs/automiq/agents/outbound.py` para
instrucciones completas.

## Invocación rápida

```python
from packs.automiq import get_agent
run = get_agent("outbound")
output = run(ctx, args={})
```

O vía HTTP:

```bash
curl -X POST https://automiq-agents.onrender.com/run/outbound   -H "X-Webhook-Secret: $WEBHOOK_SECRET"   -H "Content-Type: application/json"   -d '{"args": {}}'
```
