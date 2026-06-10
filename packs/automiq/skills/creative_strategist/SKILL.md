---
name: automiq-creative-strategist
description: |
  Skill del pack `automiq` (agente creative_strategist). Implementación: `packs/automiq/agents/creative_strategist.py`.
tags: [automiq, agency, creative-strategist]
---

# automiq-creative-strategist

Agente creative_strategist del pack `automiq`. Ver `packs/automiq/agents/creative_strategist.py` para
instrucciones completas.

## Invocación rápida

```python
from packs.automiq import get_agent
run = get_agent("creative_strategist")
output = run(ctx, args={})
```

O vía HTTP:

```bash
curl -X POST https://automiq-agents.onrender.com/run/creative_strategist   -H "X-Webhook-Secret: $WEBHOOK_SECRET"   -H "Content-Type: application/json"   -d '{"args": {}}'
```
