"""
Outbound — motor de SECUENCIA de cold-email automático a los leads de leadhunter.

Flujo (determinístico + LLM, driven por el leads_store):
  1. build_user_message:
     - Ingesta el reporte más reciente de leadhunter al leads_store (estado=nuevo).
     - Calcula qué leads toca contactar HOY (primer toque + follow-ups vencidos),
       según la cadencia día 0/+2/+5/+9 que vive en el store.
     - Para cada lead due, el LLM redacta el mensaje del STEP correspondiente
       (primer toque vs follow-up 1/2/3). Devuelve JSON con la `key` del lead.
  2. post_process: valida, respeta el tope diario, y si outbound_auto_send →
     ENVÍA vía Gmail; registra el toque en el store (avanza la secuencia). Si no,
     dry-run. La secuencia FRENA sola cuando inbox_assistant marca al lead como
     "respondió" (mark_replied) → ese lead deja de aparecer como due.

NO usa Claude Code (texto puro → liviano). El envío de Gmail corre en el proceso
principal (token con scope compose).
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
from ..integrations import leads_store as ls
from ..log import get_logger

log = get_logger("outbound")

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
_SENT_LOG = _DATA_DIR / "outbound-sent.json"


OUTBOUND_INSTRUCTIONS = """
# Outbound — Secuencia de cold-email a los leads de Automiq

Recibís una lista de leads que toca contactar HOY. Cada uno trae un `step`:
- step 0 = PRIMER TOQUE (no nos conoce)
- step 1, 2, 3 = FOLLOW-UP (ya le escribimos antes y no respondió)

Tu trabajo: por cada lead, redactar el email que corresponde a SU step.

## Reglas comunes del email
- Español argentino, tono humano y directo (NO plantilla obvia, NO "Estimado señor").
- **Subject** corto, sin spam (sin MAYÚSCULAS, sin "!!!", sin "oferta", sin "gratis").
- Firmá como "Equipo Automiq".
- NUNCA inventes precios, plazos ni datos del lead que no estén en el material.

## Cómo cambia el mensaje según el step
- **step 0 (primer toque)** ≤ 90 palabras, que se sienta escrito a mano 1-a-1 (NO masivo):
  1. **Apertura ESPECÍFICA** de SU negocio (su rubro + un dolor concreto y creíble: "vi que
     atienden consultas por WhatsApp en [empresa] — cuando entran 30 mensajes a la vez es
     imposible contestar todos a tiempo"). Nada genérico tipo "espero que estés bien".
  2. **1 beneficio medible** (Big Domino, con número si es creíble): "un agente de IA contesta
     al toque 24/7, califica al cliente y te lo carga al CRM — recuperás las ventas que hoy se
     pierden por no contestar a tiempo".
  3. **CTA de baja fricción y ON-BRAND**: ofrecé MOSTRARLO, no "una reunión". Ej: "¿te mando
     un ejemplo del agente funcionando por WhatsApp, armado para [empresa]? Son 2 minutos." o
     "¿15 min el miércoles o el jueves y te lo muestro en vivo?". Dar 1 acción clarísima.
- **step 1 (follow-up 1)** ≤ 55 palabras: breve, subí un dato/beneficio NUEVO (no repitas),
  re-ofrecé el ejemplo por WhatsApp. Asunto "Re: <asunto anterior>".
- **step 2 (follow-up 2)** ≤ 40 palabras: un ángulo distinto o mini-prueba ("a [rubro similar]
  le subió un 30% las respuestas"), CTA suave.
- **step 3 (follow-up 3, ÚLTIMO)** ≤ 30 palabras: cierre cordial sin presión ("¿lo dejo por
  acá o te sirve que te muestre 15 min?").

## Formato de salida (OBLIGATORIO)
Devolvé EXCLUSIVAMENTE un array JSON válido (sin texto antes/después, sin ```), un
objeto por lead, COPIANDO la `key` tal cual te la pasé:

[
  {"key": "<la key del lead>", "company": "Nombre", "email": "info@empresa.com.ar",
   "step": 0, "subject": "asunto", "body": "cuerpo completo del email"}
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


def _wa_link(phone: str) -> str:
    """Convierte +5491135866629 → https://wa.me/5491135866629 (clic directo a WhatsApp)."""
    digits = re.sub(r"[^\d]", "", phone or "")
    return f"https://wa.me/{digits}" if digits else ""


def _wa_line(w: dict) -> str:
    """Línea de la cola WhatsApp con link clickeable + decisor."""
    link = _wa_link(w.get("phone", ""))
    who = f" · {w['decisor']}" if w.get("decisor") else ""
    tail = f" → {link}" if link else ""
    return f"• **{w['company']}** — `{w.get('phone','')}`{tail}{who}"


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
    description = "Secuencia de cold-email automático a los leads (día 0/+2/+4/+7, dedup, tope)"
    # Sólo días hábiles: un cold-email B2B un sábado/domingo rinde peor y huele a bot
    # (se estaban mandando 19-20 mails también los fines de semana).
    schedule = "0 12 * * mon-fri"
    timezone = "America/Buenos_Aires"
    max_tokens = 8000
    temperature = 0.6
    use_claude_code = False   # composición de texto + envío determinístico (liviano)

    @property
    def system_prompt(self) -> str:
        return f"{get_context_block()}\n\n{OUTBOUND_INSTRUCTIONS}"

    def _today(self) -> str:
        return datetime.now(pytz.timezone(self.timezone)).strftime("%Y-%m-%d")

    def build_user_message(self, ctx: AgentContext) -> str:
        today = self._today()
        store = ls.load_store()

        # 1) Ingestar el reporte más reciente de leadhunter (idempotente). Sembramos
        #    desde el sent-log histórico para no re-mailear a quien ya le escribimos.
        report = _latest_leadhunter_report()
        sent_emails = _load_sent_log().get("emails", {})
        ingest_stats = {"nuevos": 0, "existentes": 0}
        if report:
            ingest_stats = ls.ingest_report(store, report, today=today, sent_log_emails=sent_emails)

        # 2) ¿Qué leads toca contactar hoy? (primer toque + follow-ups vencidos)
        cap = int(ctx.settings.outbound_daily_cap)
        due = ls.due_for_touch(store, today=today)
        due_today = due[:cap]
        over_cap = len(due) - len(due_today)

        # Guardamos el store ya ingestado y el contexto para post_process.
        ls.save_store(store)
        ctx.args["_ob_due_keys"] = [l["key"] for l in due_today]
        ctx.args["_ob_over_cap"] = over_cap
        ctx.args["_ob_ingest"] = ingest_stats
        ctx.args["_ob_wa_queue"] = [
            {"company": l.get("company", "?"), "phone": l.get("phone", ""),
             "decisor": l.get("decisor", "")}
            for l in ls.whatsapp_queue(store)[:15]
        ]

        if not due_today:
            ctx.args["_ob_status"] = "nothing_due"
            return ("No hay leads para contactar hoy en la secuencia. Respondé EXACTAMENTE: "
                    "'✅ Outbound: sin toques pendientes para hoy.'")

        ctx.args["_ob_status"] = "ok"
        pains = upstream_handoff_block(
            "web_auditor",
            titulo="Dolores detectados por la auditoría web (usalos para personalizar)",
            max_chars=3000,
        )

        # Bloque por lead: damos al modelo lo justo para personalizar + el step.
        blocks: List[str] = []
        for l in due_today:
            step = l.get("next_step", 0)
            prev = ""
            if l.get("touches"):
                last = l["touches"][-1]
                prev = f" · último asunto enviado: \"{last.get('subject', '')}\""
            blocks.append(
                f"- key: {l['key']}\n"
                f"  empresa: {l.get('company', '?')}\n"
                f"  email: {l.get('email', '')}\n"
                f"  decisor: {l.get('decisor', '') or '(s/d)'}\n"
                f"  industria: {l.get('industria', '') or '(s/d)'}\n"
                f"  web: {l.get('web', '') or '(s/d)'}\n"
                f"  step: {step}  ({ls.STEP_LABEL.get(step, 'follow-up')}){prev}"
            )

        return (
            f"Leads a contactar HOY ({len(due_today)}). Por cada uno redactá el email de SU "
            f"step y devolvé el array JSON (copiá la `key` tal cual).\n\n"
            "=== LEADS ===\n" + "\n\n".join(blocks) + "\n"
            f"{pains}"
        )

    def post_process(self, response_text: str, ctx: AgentContext) -> str:
        status = ctx.args.get("_ob_status") if isinstance(ctx.args, dict) else None
        if status == "nothing_due":
            # Igual mostramos un resumen útil (ingest + cola WhatsApp) en vez del texto pelado.
            return super().post_process(self._summary_when_idle(ctx), ctx)

        today = self._today()
        store = ls.load_store()
        due_keys = set(ctx.args.get("_ob_due_keys", []))

        items = _parse_json_array(response_text)
        # Mapear por key (autoritativo); descartar lo que el modelo inventó fuera del batch.
        by_key: Dict[str, Dict[str, Any]] = {}
        for it in items:
            k = (it.get("key") or "").strip()
            if k in due_keys and k not in by_key:
                by_key[k] = it

        dry_run = bool(ctx.args.get("dry_run")) if isinstance(ctx.args, dict) else False
        auto = bool(ctx.settings.outbound_auto_send)
        live = auto and not dry_run

        client = None
        if live:
            try:
                client = get_gmail_client(ctx.settings)
            except GmailError as e:
                log.error("outbound_gmail_unavailable", error=str(e))
                live = False

        sent_log = _load_sent_log()
        sent_map = sent_log.setdefault("emails", {})

        sent, preview, errors, missing = [], [], [], []
        for key in ctx.args.get("_ob_due_keys", []):
            lead = store.get("leads", {}).get(key)
            if not lead:
                continue
            step = lead.get("next_step", 0)
            label = ls.STEP_LABEL.get(step, f"step {step}")
            company = lead.get("company", "?")
            email = lead.get("email", "")
            it = by_key.get(key)
            if not it:
                missing.append(f"• {company} <{email}> — el modelo no redactó el {label}")
                continue
            subject = (it.get("subject") or "").strip()
            body = (it.get("body") or "").strip()
            if not subject or not body or not _EMAIL_RE.match(email.lower()):
                errors.append(f"• {company} <{email}> → sin subject/body/email válido, omitido")
                continue
            if not live:
                preview.append(f"• **{company}** <{email}> — _{label}_: {subject}")
                continue
            try:
                # Follow-ups (step>0) van DENTRO del hilo del primer toque: el prospecto
                # ve la conversación completa (y no un "Re:" suelto que parece spam).
                thread_id = ""
                if step > 0 and lead.get("touches"):
                    last_touch = lead["touches"][-1]
                    thread_id = last_touch.get("thread_id") or ""
                    if not thread_id and last_touch.get("msg_id"):
                        thread_id = client.thread_id_of(last_touch["msg_id"])
                mid = client.send_message(to=email, subject=subject, body=body,
                                          from_name=ctx.settings.outbound_from_name,
                                          thread_id=thread_id or None)
                if not thread_id:
                    thread_id = client.thread_id_of(mid)
                ls.record_touch(store, key, step=step, channel="email",
                                msg_id=mid, subject=subject, thread_id=thread_id, today=today)
                sent_map[email] = {"company": company, "date": today, "subject": subject,
                                   "step": step, "msg_id": mid, "run_id": ctx.run_id}
                sent.append(f"• **{company}** <{email}> → ✅ {label} enviado (`{mid[:10]}`)")
            except Exception as e:
                log.error("outbound_send_failed", email=email, step=step, error=str(e))
                errors.append(f"• {company} <{email}> → ❌ {e}")

        if live:
            ls.save_store(store)
            if sent:
                _save_sent_log(sent_log)

        log.info("outbound_done", run_id=ctx.run_id, sent=len(sent),
                 preview=len(preview), errors=len(errors), live=live)

        return super().post_process(self._render_report(ctx, live, auto, sent, preview, errors, missing), ctx)

    # ── render del reporte para Discord ──

    def _summary_when_idle(self, ctx: AgentContext) -> str:
        ing = ctx.args.get("_ob_ingest", {}) or {}
        wa = ctx.args.get("_ob_wa_queue", []) or []
        parts = [
            "# 📤 Outbound — sin toques pendientes hoy",
            "",
            f"Leads nuevos ingestados del reporte: **{ing.get('nuevos', 0)}** "
            f"(ya conocidos: {ing.get('existentes', 0)}).",
            "",
            "_La secuencia no tiene emails vencidos para hoy (día 0/+2/+5/+9)._",
        ]
        if wa:
            parts += ["", "## 📱 Cola WhatsApp (sin email — clic y escribí)"]
            parts += [_wa_line(w) for w in wa]
        return "\n".join(parts)

    def _render_report(self, ctx, live, auto, sent, preview, errors, missing) -> str:
        ing = ctx.args.get("_ob_ingest", {}) or {}
        over_cap = ctx.args.get("_ob_over_cap", 0)
        wa = ctx.args.get("_ob_wa_queue", []) or []
        mode = "ENVÍO REAL" if live else ("DRY-RUN (auto_send OFF)" if not auto else "DRY-RUN (pedido)")
        parts = [
            f"# 📤 Outbound — secuencia de cold-email ({mode})",
            "",
            f"Nuevos del reporte: **{ing.get('nuevos', 0)}** · "
            + (f"**Enviados:** {len(sent)} · " if live else f"**A enviar:** {len(preview)} · ")
            + f"**Errores:** {len(errors)}"
            + (f" · **Sobre el tope:** {over_cap} (quedan para mañana)" if over_cap else ""),
            "",
        ]
        if sent:
            parts += ["## ✅ Enviados hoy", *sent, ""]
        if preview:
            parts += ["## 👀 Se enviarían (auto_send OFF o dry-run)", *preview, ""]
        if missing:
            parts += ["## ⚠️ Sin redactar (revisar)", *missing, ""]
        if errors:
            parts += ["## ⚠️ Errores", *errors, ""]
        if wa:
            parts += ["## 📱 Cola WhatsApp (sin email — clic y escribí)"]
            parts += [_wa_line(w) for w in wa]
            parts += [""]
        if not sent and not preview and not errors and not missing:
            parts += ["_Sin toques para procesar hoy._"]
        return "\n".join(parts)
