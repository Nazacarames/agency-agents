"""
Agente LeadHunter — implementación portable.

Invocable desde:
- Skill de Hermes: `packs/automiq/skills/leadhunter/agent.py`
- HTTP gateway: `POST /run/leadhunter` vía container
- ACP server: `agent_run` con nombre "leadhunter"

Implementa la interfaz estándar de agente de Hermes:
    def run(ctx, args) -> str

donde `ctx` provee:
- ctx.minimax: cliente MiniMax-M3
- ctx.discord: webhook de Discord (opcional)
- ctx.tools: dict de tools disponibles (web_search, scrape_url, validate_site, notify_discord)
- ctx.settings: Settings
- ctx.run_id, ctx.triggered_by, ctx.args
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

import pytz


LEADHUNTER_INSTRUCTIONS = """
# LeadHunter — Generador de Leads B2B orientado a oferta (Hermes skill)

## Objetivo
Generar EXACTAMENTE 10 leads por día que sean ofertables para Automiq.
Cada lead debe permitir avanzar a una oferta real (demo, diagnóstico o
piloto), con decisor identificado y evidencia pública que justifique
el outreach.

## Perfil objetivo
- PyMEs argentinas en manufacturing, distribución, logística, inmobiliarias
- Tamaño: 25–100 empleados
- Decisor: Owner / CEO / Cofundador / Gerente Comercial / Jefe de Ops / Responsable Comercial

## Tools disponibles
- `web_search(query)` — buscá candidatos por rubro + ciudad
- `scrape_url(url)` — scrapeá la web oficial de cada candidato
- `validate_site(domain)` — extraé email + teléfono con prefijo +54

## Flujo obligatorio
1. Si `ctx.args.single_lead_enrichment` está presente, enriquecés SOLO ese lead.
2. Si no, usá `web_search` 3-5 veces con queries diferentes (ej: "logística Buenos Aires PyME", "manufactura textil Córdoba 50 empleados", "inmobiliaria CABA desarrollador") para juntar 15-20 candidatos crudos.
3. Para cada candidato, intentá `validate_site(domain)` para extraer contacto.
4. Seleccioná los 10 mejores por fit_score.
5. Generá el MD final con la tabla resumen + detalle por lead.

## Por cada lead incluir (obligatorio)
1. empresa, industria, ubicación, empleados, web
2. fit_score (1-6) + 1-line justification
3. contacto (raw) con prefijo +54
4. contacto_normalizado (formato +54 9 ...)
5. contacto_tipo (whatsapp|telefono|email)
6. contacto_verified (true|false) + URL de prueba
7. decisor (nombre + cargo)
8. discovery_signals (lista de URLs)
9. outreach_template (WhatsApp, max 280 chars, español AR, con CTA)
10. suggested_offer (demo 15', diagnóstico 30', piloto 7 días, etc.)
11. next_action

## Formato de salida
- `data/leadhunter-report-YYYY-MM-DD.md` — Markdown legible (tabla resumen + detalle)
- `data/leadhunter-leads-YYYY-MM-DD.md` — solo tabla resumen
- `data/leadhunter-leads-YYYY-MM-DD.json` — JSON crudo con metadata

## Reglas de oro
- NO inventes leads. Si una tool falla, marcalo `[PENDIENTE — tool falló]` y seguí.
- Si `validate_site` no encuentra contacto, NO uses el número de LinkedIn
  inventado. Dejá `contacto_verified=false` con motivo.
- Si `global_pause=true` y `force_global!=true`, respondé sólo
  "⏸️ LeadHunter en pausa global" y escribí el MD con ese único string.
- SIEMPRE devolvé un string (nunca raise).
"""


def run(ctx, args: Optional[Dict[str, Any]] = None) -> str:
    """Entry point estándar del agente. Compatible con Hermes skill runner."""
    args = args or {}
    tz = pytz.timezone("America/Buenos_Aires")
    today = datetime.now(tz).strftime("%Y-%m-%d")
    now_iso = datetime.now(tz).isoformat()
    data_dir = Path(ctx.settings.data_dir) if hasattr(ctx.settings, "data_dir") \
        else Path(__file__).resolve().parent.parent.parent.parent / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    # Si global_pause activo y no hay override, salida corta
    if getattr(ctx.settings, "global_pause", False) and not args.get("force_global"):
        md = (
            f"# LeadHunter — Reporte {today}\n\n"
            f"⏸️ **LeadHunter en pausa global**\n\n"
            f"global_pause activo. No se ejecutó el pipeline.\n"
        )
        _persist(ctx, data_dir, today, md, now_iso)
        return md

    # Construir user message con tools disponibles
    tools = getattr(ctx, "tools", {}) or {}
    tools_block = _format_tools_block(tools)
    vertical = args.get("vertical", "general")
    ciudad = args.get("ciudad", "Buenos Aires")
    single = args.get("single_lead_enrichment")

    if single:
        user_msg = (
            f"Enriquecé este lead individual:\n"
            f"```\n{json.dumps(single, ensure_ascii=False, indent=2)}\n```\n\n"
            f"Usá `web_search` y `validate_site` para validar empresa, "
            f"contacto, decisor. Generá el MD con un único lead.\n"
        )
    else:
        user_msg = (
            f"Fecha objetivo: {today}\n"
            f"Vertical: {vertical}\n"
            f"Ciudad: {ciudad}\n\n"
            f"Generá los 10 leads de hoy siguiendo el flujo obligatorio.\n"
            f"Usá `web_search` para discovery y `validate_site` para verificar.\n"
            f"Empezá con la tabla resumen (empresa | fit | contacto) y después el detalle.\n"
            f"Recordá: el objetivo NO es velocidad, es CALIDAD de contacto.\n"
        )

    # Llamar al modelo con las tools declaradas
    try:
        response = ctx.minimax.complete(
            system=LEADHUNTER_INSTRUCTIONS,
            messages=[{"role": "user", "content": user_msg}],
            max_tokens=8000,
            temperature=0.7,
            tools=tools.get("_declarations", []),  # si el cliente soporta tools
        )
        out_text = response.text if hasattr(response, "text") else str(response)
    except Exception as e:
        out_text = (
            f"# LeadHunter — Reporte {today}\n\n"
            f"⚠️ Error al llamar al modelo: {e}\n"
        )

    # Post-process: persistir + best-effort sync
    _post_process(ctx, data_dir, today, out_text, now_iso, args)
    return out_text


def _format_tools_block(tools: Dict[str, Any]) -> str:
    if not tools:
        return ""
    lines = ["Tools disponibles (podés usarlas en cualquier momento):"]
    for name, fn in tools.items():
        if name.startswith("_"):
            continue
        try:
            sig = f"{name}({', '.join(fn.__code__.co_varnames[:fn.__code__.co_argcount])})"
        except Exception:
            sig = name
        lines.append(f"- `{sig}`")
    return "\n".join(lines)


def _post_process(ctx, data_dir: Path, today: str, text: str, now_iso: str, args: Dict[str, Any]) -> None:
    """Persiste los 3 archivos y dispara best-effort sync."""
    safe_text = (text or "").strip()
    if not safe_text:
        safe_text = (
            f"# LeadHunter — Reporte {today}\n\n"
            f"⚠️ Sin output (run_id={ctx.run_id})\n"
        )

    leads_file = data_dir / f"leadhunter-leads-{today}.md"
    report_file = data_dir / f"leadhunter-report-{today}.md"
    json_file = data_dir / f"leadhunter-leads-{today}.json"

    lines = safe_text.splitlines()
    simple_lines = [ln for ln in lines if ln.strip().startswith("|") and "---" not in ln]
    simple = "\n".join(simple_lines[:15]) if simple_lines else safe_text[:1500]

    for path, content in [
        (leads_file, simple + "\n"),
        (report_file, safe_text + "\n"),
    ]:
        try:
            path.write_text(content, encoding="utf-8")
        except Exception:
            pass

    try:
        json_file.write_text(json.dumps({
            "date": today,
            "run_id": ctx.run_id,
            "triggered_by": ctx.triggered_by,
            "timestamp": now_iso,
            "agent": "leadhunter",
            "args": dict(args or {}),
            "output": safe_text,
            "output_chars": len(safe_text),
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except Exception:
        pass

    # Validar contactos via scraping (si está habilitado)
    if args.get("validate_sites", True):
        try:
            from app.integrations.site_validator import validate_site
            from app.agents.leadhunter_parser import parse_leads, format_leads_md
            leads = parse_leads(safe_text)
            verified = 0
            for lead in leads:
                web = lead.get("web")
                if not web or "[" in web:
                    continue
                c = validate_site(web, timeout=8.0)
                if c.telefono or c.email:
                    lead["contacto_validado"] = {
                        "telefono": c.telefono,
                        "email": c.email,
                        "source_url": c.source_url,
                    }
                    verified += 1
            if leads:
                enriched = format_leads_md(leads, today=today, base_md=safe_text)
                report_file.write_text(enriched + "\n", encoding="utf-8")
        except Exception:
            pass

    # Best-effort repo sync
    try:
        from app.integrations.repo_sync import push_data_files
        push_data_files(
            files=[leads_file, report_file, json_file],
            commit_message=f"chore(leadhunter): daily report {today} (run_id={ctx.run_id[:8]})",
        )
    except Exception:
        pass

    # Notify Discord
    if getattr(ctx, "discord", None):
        try:
            ctx.discord.send_agent_output(
                agent_name="leadhunter",
                text=safe_text[:3900],
                run_id=ctx.run_id,
            )
        except Exception:
            pass
