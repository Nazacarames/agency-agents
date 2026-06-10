---
name: automiq-social-media
description: |
  Skill del pack `automiq` (agente social_media). Implementación: `packs/automiq/agents/social_media.py`.
tags: [automiq, agency, social-media]
---

# automiq-social-media

Agente social_media del pack `automiq`. Ver `packs/automiq/agents/social_media.py` para
instrucciones completas.

## Invocación rápida

```python
from packs.automiq import get_agent
run = get_agent("social_media")
output = run(ctx, args={})
```

O vía HTTP:

```bash
curl -X POST https://automiq-agents.onrender.com/run/social_media   -H "X-Webhook-Secret: $WEBHOOK_SECRET"   -H "Content-Type: application/json"   -d '{"args": {}}'
```
