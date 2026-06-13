"""
Outbound — cold-email AUTOMÁTICO a los leads de leadhunter.

Flujo (determinístico + LLM, igual patrón que inbox_assistant):
  1. build_user_message: lee el reporte más reciente de leadhunter + los dolores del
     web_auditor (handoff). El LLM extrae cada lead CON email y redacta el primer
     cold-email (subject + body) personalizado. Devuelve JSON.
  2. post_process: dedup contra el sent-log (volume), tope diario, y si
     settings.outbound_auto_send → ENVÍA vía Gmail (messages.send). Si no, dry-run.

NO usa Claude Code (texto puro → liviano). El envío de Gmail corre en el proceso
principal (token con scope compose, que permite enviar).

⚠️ Sólo manda el PRIMER toque (día 0). Follow-ups quedan para otra iteración (requieren
detección de respuesta). Dedup por email → nunca se le escribe dos veces al mismo lead.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

import pytz

from .base import BaseAgent, AgentContext
from ._common import get_context_block, upstream_handoff_block
from ..integrations.gmail_client import get_gmail_client, GmailError
from ..log import get_logger

log = get_logger("outbound")

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
_SENT_LOG = _DATA_DIR / "outbound-sent.json"


OUTBOUND_INSTRUCTIONS = """
# Outbound — Cold-email a los leads de Automiq

Recibís el reporte de leads más reciente (de leadhunter) y, opcionalmente, los dolores
detectados por la auditoría web. Tu trabajo: por cada lead que tenga un EMAIL real,
redactar el PRIMER cold-email (día 0), listo para enviar.

## Reglas del email
- Español argentino, tono humano y directo (NO plantilla obvia, NO "Estimado señor").
- **Subject** corto, que NO parezca spam (sin MAYÚSCULAS, sin "!!!", sin "oferta").
- **Cuerpo** ≤ 120 palabras: 1 línea de apertura personalizada (referí algo real del
  lead: su rubro, un dolor detectado, algo de su web), 1-2 líneas de valor concreto
  (Big Domino: beneficio medible, no "te ayudo"), y 1 CTA simple ("¿te viene bien una
  llamada de 15 min el martes o el jueves?").
- Firmá como "Equipo Automiq".
- NUNCA inventes precios, plazos ni datos del lead que no estén en el material.
- Si un lead NO tiene email (solo WhatsApp/teléfono), OMITILO (no lo incluyas en el JSON).

## Formato de salida (OBLIGATORIO)
Devolvé EXCLUSIVAMENTE un array JSON válido (sin texto antes/después, sin ```), un
objeto por lead CON email:

[
  {"company": "Nombre de la empresa", "email": "info@empresa.com.ar",
   "subject": "asunto del email", "body": "cuerpo completo del email"}
]
""".strip()


def _parse_json_array(text: str) -> List[Dict[str, Any]]:
    if not text:
        return []
    fence = re.search(r"```(?:json)?\s*(.+?)```", text, re.DOTALL)
    cand = fence.group(1) if fence else text
    a, b = cand.find("["), cand.rfind("]")
    if a == -1 or b == -1 or b <= a:
        return []
    try:
        data = json.loads(cand[a:b + 1])
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        return []


def _load_sent_log() -> Dict[str, Any]:
    try:
        return json.loads(_SENT_LOG.read_text(encoding="utf-8"))
    except Exception:
        return {"emails": {}}


def _save_sent_log(data: Dict[str, Any]) -> None:
    try:
        _DATA_DIR.mkdir(exist_ok=True)
        _SENT_LOG.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        log.error("outbound_sentlog_save_failed", error=str(e))


def _latest_leadhunter_report() -> str:
    cands = sorted(_DATA_DIR.glob("leadhunter-report-*.md"), reverse=True)
    for p in cands:
        try:
            t = p.read_text(encoding="utf-8")
            if len(t) > 200:
                return t
        except Exception:
            continue
    return ""


class OutboundAgent(BaseAgent):
    name = "outbound"
    description = "Cold-email automático a los leads de leadhunter (Gmail, dedup, tope diario)"
    schedule = "0 12 * * *"
    timezone = "America/Buenos_Aires"
    max_tokens = 8000
    temperature = 0.6
    use_claude_code = False   # composición de texto + envío determinístico (liviano)

    @property
    def system_prompt(self) -> str:
        return f"{get_context_block()}\n\n{OUTBOUND_INSTRUCTIONS}"

    def build_user_message(self, ctx: AgentContext) -> str:
        report = _latest_leadhunter_report()
        if not report:
            ctx.args["_ob_status"] = "no_leads"
            return ("No hay reporte de leadhunter disponible en data/. Respondé EXACTAMENTE: "
                    "'⚠️ Outbound: sin reporte de leads para procesar.'")

        sent = _load_sent_log().get("emails", {})
        already = ", ".join(list(sent.keys())[:50]) or "(ninguno)"
        pains = upstream_handoff_block(
            "web_auditor",
            titulo="Dolores detectados por la auditoría web (usalos para personalizar el opening)",
            max_chars=4000,
        )
        ctx.args["_ob_status"] = "ok"
        return (
            "Abajo va el reporte de leads más reciente de leadhunter. Extraé CADA lead que "
            "tenga un EMAIL real y redactá su primer cold-email (JSON especificado).\n\n"
            f"⚠️ NO incluyas estos emails (ya fueron contactados): {already}\n\n"
            "=== REPORTE DE LEADS ===\n"
            f"{report[:12000]}\n"
            f"{pains}"
        )

    def post_process(self, response_text: str, ctx: AgentContext) -> str:
        status = ctx.args.get("_ob_status") if isinstance(ctx.args, dict) else None
        if status == "no_leads":
            return super().post_process(response_text, ctx)

        items = _parse_json_array(response_text)
        log_data = _load_sent_log()
        sent_map: Dict[str, Any] = log_data.setdefault("emails", {})

        # Filtrar: email válido, no repetido (sent-log + dentro del batch)
        candidates: List[Dict[str, Any]] = []
        seen_batch = set()
        skipped_no_email = skipped_dup = 0
        for it in items:
            email = (it.get("email") or "").strip().lower()
            if not _EMAIL_RE.match(email):
                skipped_no_email += 1
                continue
            if email in sent_map or email in seen_batch:
                skipped_dup += 1
                continue
            seen_batch.add(email)
            candidates.append({**it, "email": email})

        cap = int(ctx.settings.outbound_daily_cap)
        to_send = candidates[:cap]
        over_cap = len(candidates) - len(to_send)

        dry_run = bool(ctx.args.get("dry_run")) if isinstance(ctx.args, dict) else False
        auto = bool(ctx.settings.outbound_auto_send)
        tz = pytz.timezone(self.timezone)
        today = datetime.now(tz).strftime("%Y-%m-%d")

        client = None
        live = auto and not dry_run
        if live:
            try:
                client = get_gmail_client(ctx.settings)
            except GmailError as e:
                log.error("outbound_gmail_unavailable", error=str(e))
                live = False

        sent, errors, preview = [], [], []
        for c in to_send:
            email, company = c["email"], (c.get("company") or "?")
            subject, body = (c.get("subject") or "").strip(), (c.get("body") or "").strip()
            if not subject or not body:
                errors.append(f"• {company} <{email}> → sin subject/body, omitido")
                continue
            if not live:
                preview.append(f"• **{company}** <{email}> — _{subject}_")
                continue
            try:
                mid = client.send_message(to=email, subject=subject, body=body,
                                          from_name=ctx.settings.outbound_from_name)
                sent_map[email] = {"company": company, "date": today, "subject": subject,
                                   "msg_id": mid, "run_id": ctx.run_id}
                sent.append(f"• **{company}** <{email}> → ✅ enviado (`{mid[:10]}`)")
            except Exception as e:
                log.error("outbound_send_failed", email=email, error=str(e))
                errors.append(f"• {company} <{email}> → ❌ {e}")

        if live and sent:
            _save_sent_log(log_data)

        log.info("outbound_done", run_id=ctx.run_id, sent=len(sent),
                 preview=len(preview), errors=len(errors), live=live)

        # Resumen para #Outbound
        mode = "ENVÍO REAL" if live else ("DRY-RUN (auto_send OFF)" if not auto else "DRY-RUN (pedido)")
        parts = [
            f"# 📤 Outbound — cold-email ({mode})",
            "",
            (f"**Enviados:** {len(sent)} · " if live else f"**A enviar:** {len(preview)} · ")
            + f"**Omitidos sin email:** {skipped_no_email} · **Ya contactados (dedup):** {skipped_dup}"
            + (f" · **Sobre el tope {cap}:** {over_cap} (quedan para mañana)" if over_cap else ""),
            "",
        ]
        if sent:
            parts += ["## ✅ Enviados hoy", *sent, ""]
        if preview:
            parts += [f"## 👀 Se enviarían (tope {cap})", *preview,
                      "", "_(auto_send OFF o dry_run; no se envió nada)_", ""]
        if errors:
            parts += ["## ⚠️ Errores", *errors, ""]
        if not sent and not preview and not errors:
            parts += ["_Sin leads nuevos con email para contactar (todos ya contactados o sin email)._"]
        return super().post_process("\n".join(parts), ctx)
