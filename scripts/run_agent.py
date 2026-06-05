#!/usr/bin/env python3
"""
CLI local para disparar agentes manualmente (equivalente al `openclaw cron run`
de la versión anterior). Útil para testear o correr bajo demanda.

Uso:
  python scripts/run_agent.py leadhunter
  python scripts/run_agent.py leadhunter --arg vertical=manufacturing
  python scripts/run_agent.py content_creator --no-discord
"""
import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


async def main():
    parser = argparse.ArgumentParser(description="Run an Automiq agent manually")
    parser.add_argument("agent", help="Agent name (e.g. leadhunter)")
    parser.add_argument("--arg", action="append", default=[], help="key=value (repeatable)")
    parser.add_argument("--no-discord", action="store_true", help="Skip Discord delivery")
    args = parser.parse_args()

    parsed_args = {}
    for a in args.arg:
        if "=" in a:
            k, v = a.split("=", 1)
            parsed_args[k] = v

    from app.container import Container
    container = Container()
    # --no-discord: parchear el client de discord para que no haga nada
    if args.no_discord:
        async def _noop_discord_send(*a, **kw):
            return None
        from app.clients.discord import DiscordWebhook
        if container.discord is not None:
            container.discord.send = _noop_discord_send  # type: ignore[assignment]
        else:
            # Forzar a que exista, así los agentes no fallan al entregar
            class _NullDiscord:
                def send_agent_output(self, *a, **kw): return None
                def send(self, *a, **kw): return {}
            container._discord = _NullDiscord()  # type: ignore[assignment]
    try:
        output = await container.run_agent(
            args.agent,
            triggered_by="cli",
            args=parsed_args,
        )
        print("\n" + "=" * 60)
        print(output)
        print("=" * 60)
    finally:
        container.close()


if __name__ == "__main__":
    asyncio.run(main())
