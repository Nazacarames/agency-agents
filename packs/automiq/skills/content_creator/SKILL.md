---
name: automiq-content-creator
description: |
  Skill del pack `automiq` (agente content_creator). Implementación: `packs/automiq/agents/content_creator.py`.
tags: [automiq, agency, content-creator]
---

# automiq-content-creator

Agente content_creator del pack `automiq`. Ver `packs/automiq/agents/content_creator.py` para
instrucciones completas.

## Invocación rápida

```python
from packs.automiq import get_agent
run = get_agent("content_creator")
output = run(ctx, args={})
```

O vía HTTP:

```bash
curl -X POST https://automiq-agents.onrender.com/run/content_creator   -H "X-Webhook-Secret: $WEBHOOK_SECRET"   -H "Content-Type: application/json"   -d '{"args": {}}'
```
