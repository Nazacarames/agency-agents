---
name: automiq-media-auditor
description: |
  Skill del pack `automiq` (agente media_auditor). Implementación: `packs/automiq/agents/media_auditor.py`.
tags: [automiq, agency, media-auditor]
---

# automiq-media-auditor

Agente media_auditor del pack `automiq`. Ver `packs/automiq/agents/media_auditor.py` para
instrucciones completas.

## Invocación rápida

```python
from packs.automiq import get_agent
run = get_agent("media_auditor")
output = run(ctx, args={})
```

O vía HTTP:

```bash
curl -X POST https://automiq-agents.onrender.com/run/media_auditor   -H "X-Webhook-Secret: $WEBHOOK_SECRET"   -H "Content-Type: application/json"   -d '{"args": {}}'
```
