---
name: automiq-growth-hacker
description: |
  Skill del pack `automiq` (agente growth_hacker). Implementación: `packs/automiq/agents/growth_hacker.py`.
tags: [automiq, agency, growth-hacker]
---

# automiq-growth-hacker

Agente growth_hacker del pack `automiq`. Ver `packs/automiq/agents/growth_hacker.py` para
instrucciones completas.

## Invocación rápida

```python
from packs.automiq import get_agent
run = get_agent("growth_hacker")
output = run(ctx, args={})
```

O vía HTTP:

```bash
curl -X POST https://automiq-agents.onrender.com/run/growth_hacker   -H "X-Webhook-Secret: $WEBHOOK_SECRET"   -H "Content-Type: application/json"   -d '{"args": {}}'
```
