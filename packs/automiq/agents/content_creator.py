"""
Agente ContentCreator — implementación portable como skill de Hermes.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

import pytz


INSTRUCTIONS = """
# ContentCreator — Skill de Hermes

Genera contenido (posts, artículos, copys) para los canales de Automiq
(LinkedIn, blog, email).

## Perfil
- Tono: profesional, español argentino (vos), concreto
- Formatos: posts LinkedIn (150-300 palabras), artículos blog (800-1500), emails (50-150)
- Audiencia: PyMEs argentinas que podrían tercerizar automatización

## Inputs (args)
- `tema` (str): tema del contenido
- `formato` (str): "linkedin_post" | "blog" | "email" | "twitter"
- `cantidad` (int, default 3): cantidad de piezas a generar
- `audiencia` (str, default "PyMEs AR"): target

## Output
- `data/content-creator-report-YYYY-MM-DD.md` con las piezas numeradas
- JSON con metadata
- Embed a Discord

## Garantías
- SIEMPRE devuelve un string, persist en disco.
- Sin raise en errores.
"""


def run(ctx, args: Optional[Dict[str, Any]] = None) -> str:
    args = args or {}
    tz = pytz.timezone("America/Buenos_Aires")
    today = datetime.now(tz).strftime("%Y-%m-%d")
    now_iso = datetime.now(tz).isoformat()
    data_dir = _data_dir(ctx)
    data_dir.mkdir(parents=True, exist_ok=True)

    if getattr(ctx.settings, "global_pause", False) and not args.get("force_global"):
        return _persist(ctx, data_dir, today, "# ContentCreator — Pausa global\n", now_iso, args)

    tema = args.get("tema", "automatización para PyMEs")
    formato = args.get("formato", "linkedin_post")
    cantidad = int(args.get("cantidad", 3))
    user_msg = (
        f"Generá {cantidad} piezas de contenido sobre '{tema}', formato {formato}.\n"
        f"Audiencia: {args.get('audiencia', 'PyMEs argentinas')}.\n"
        f"Fecha: {today}.\n"
    )

    try:
        response = ctx.minimax.complete(
            system=INSTRUCTIONS,
            messages=[{"role": "user", "content": user_msg}],
            max_tokens=6000,
            temperature=0.8,
        )
        out_text = response.text if hasattr(response, "text") else str(response)
    except Exception as e:
        out_text = f"# ContentCreator — Error: {e}\n"

    return _persist(ctx, data_dir, today, out_text, now_iso, args)


def _data_dir(ctx) -> Path:
    if hasattr(ctx.settings, "data_dir"):
        return Path(ctx.settings.data_dir)
    return Path(__file__).resolve().parent.parent.parent.parent / "data"


def _persist(ctx, data_dir, today, text, now_iso, args) -> str:
    safe = (text or "").strip() or f"# ContentCreator — {today} (sin output)"
    md_file = data_dir / f"content-creator-report-{today}.md"
    json_file = data_dir / f"content-creator-report-{today}.json"
    try:
        md_file.write_text(safe + "\n", encoding="utf-8")
    except Exception:
        pass
    try:
        import json
        json_file.write_text(json.dumps({
            "date": today, "run_id": ctx.run_id, "agent": "content_creator",
            "timestamp": now_iso, "args": dict(args or {}), "output": safe,
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except Exception:
        pass
    if getattr(ctx, "discord", None):
        try:
            ctx.discord.send_agent_output(agent_name="content_creator", text=safe[:3900], run_id=ctx.run_id)
        except Exception:
            pass
    return safe
