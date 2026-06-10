"""
Helpers compartidos para los agentes del pack automiq.

`make_agent(name, instructions, max_tokens, temperature)` devuelve un módulo
con `run(ctx, args) -> str` que sigue la convención de skills de Hermes.

Los agentes individuales (growth_hacker, etc.) importan este helper y
definen sólo las instrucciones + defaults.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

import pytz


def make_agent(
    name: str,
    instructions: str,
    *,
    max_tokens: int = 6000,
    temperature: float = 0.7,
    filename_prefix: Optional[str] = None,
):
    """Devuelve una función `run(ctx, args) -> str` con la lógica estándar."""
    prefix = filename_prefix or name
    report_filename = f"{prefix}-report-{{date}}.md"
    json_filename = f"{prefix}-report-{{date}}.json"

    def _data_dir(ctx) -> Path:
        if hasattr(ctx.settings, "data_dir"):
            return Path(ctx.settings.data_dir)
        return Path(__file__).resolve().parent.parent.parent.parent / "data"

    def _persist(ctx, data_dir, today, text, now_iso, args) -> str:
        safe = (text or "").strip() or f"# {name} — {today} (sin output)"
        md_file = data_dir / report_filename.format(date=today)
        json_file = data_dir / json_filename.format(date=today)
        try:
            md_file.write_text(safe + "\n", encoding="utf-8")
        except Exception:
            pass
        try:
            json_file.write_text(json.dumps({
                "date": today,
                "run_id": ctx.run_id,
                "agent": name,
                "timestamp": now_iso,
                "args": dict(args or {}),
                "output": safe,
            }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        except Exception:
            pass
        if getattr(ctx, "discord", None):
            try:
                ctx.discord.send_agent_output(agent_name=name, text=safe[:3900], run_id=ctx.run_id)
            except Exception:
                pass
        return safe

    def run(ctx, args: Optional[Dict[str, Any]] = None) -> str:
        args = args or {}
        tz = pytz.timezone("America/Buenos_Aires")
        today = datetime.now(tz).strftime("%Y-%m-%d")
        now_iso = datetime.now(tz).isoformat()
        data_dir = _data_dir(ctx)
        data_dir.mkdir(parents=True, exist_ok=True)

        if getattr(ctx.settings, "global_pause", False) and not args.get("force_global"):
            return _persist(ctx, data_dir, today,
                            f"# {name} — Pausa global\n", now_iso, args)

        user_msg = (
            f"Fecha: {today}\n"
            f"Args: {json.dumps(args, ensure_ascii=False)}\n\n"
            f"Generá el output siguiendo las instrucciones.\n"
        )
        try:
            response = ctx.minimax.complete(
                system=instructions,
                messages=[{"role": "user", "content": user_msg}],
                max_tokens=max_tokens,
                temperature=temperature,
            )
            out_text = response.text if hasattr(response, "text") else str(response)
        except Exception as e:
            out_text = f"# {name} — Error: {e}\n"
        return _persist(ctx, data_dir, today, out_text, now_iso, args)

    run.__name__ = f"{name}_run"
    run.__doc__ = f"Run entry point for agent {name}"
    return run
