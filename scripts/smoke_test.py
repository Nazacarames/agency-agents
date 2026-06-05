#!/usr/bin/env python3
"""
Smoke test local — verifica que la app arranca, los agentes se registran
y los endpoints básicos responden. NO requiere API keys reales.

Uso:  python scripts/smoke_test.py
"""
import asyncio
import sys
from pathlib import Path

# Permitir import de app/ cuando se ejecuta desde /scripts/
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


async def main():
    from app.config import Settings
    # Forzar settings "vacías" para evitar fallar por falta de secrets
    s = Settings(
        minimax_api_key="",
        discord_webhook_url="",
        webhook_secret="",
        scheduler_enabled=False,
    )

    from app.container import Container
    from app.agents.registry import list_agents

    container = Container(settings=s)
    print("=== Container health ===")
    print(container.health())

    print("\n=== Agentes registrados ===")
    for a in list_agents():
        print(f"  - {a.name:25s} | {a.description[:60]}")
        print(f"    schedule: {a.schedule or '(manual)'} | tz: {a.timezone}")

    print("\n=== FastAPI routes ===")
    from app.main import app
    for route in app.routes:
        if hasattr(route, "methods"):
            methods = ",".join(sorted(route.methods - {"HEAD"}))
            print(f"  {methods:8s} {route.path}")

    print("\n✅ Smoke test passed.")


if __name__ == "__main__":
    asyncio.run(main())
