"""
Inbox Assistant — lee la bandeja de la cuenta dedicada de Automiq
(automiqaiagency@gmail.com) y redacta BORRADORES de respuesta para revisión humana.

Flujo (determinístico + LLM):
  1. build_user_message: trae los hilos NO leídos vía Gmail API (Python, no tool-use)
     y los mete en el prompt.
  2. El LLM (MiniMax-M3) decide por hilo si conviene responder y redacta la respuesta.
  3. post_process: parsea el JSON del LLM y crea un BORRADOR por respuesta (drafts.create).
     NUNCA envía: el humano revisa y manda desde Gmail.

Esto NO usa Claude Code (es composición de texto pura → liviano en cuota MiniMax).
La I/O de Gmail corre en el proceso principal (que tiene las env vars), no en el sandbox.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List

from .base import BaseAgent, AgentContext
from ._common import get_context_block
from ..integrations.gmail_client import get_gmail_client, GmailError
from ..log import get_logger

log = get_logger("inbox_assistant")


INBOX_INSTRUCTIONS = """
# Inbox Assistant — Automiq

Sos el asistente de bandeja de entrada de Automiq. Recibís hilos de email NO leídos
de la casilla de la agencia y, por cada uno, decidís si corresponde responder y
redactás un BORRADOR de respuesta listo para que un humano lo revise y mande.

## Cómo decidir si responder (should_reply)
- ✅ Respondé: consultas de prospectos/clientes, pedidos de info, preguntas
  comerciales, follow-ups de gente real, partners.
- ❌ NO respondas (should_reply=false): newsletters, notificaciones automáticas,
  no-reply@, facturas/recibos, spam, promociones, confirmaciones de plataformas,
  o cualquier cosa que claramente no espera respuesta humana.

## Cómo redactar la respuesta (draft_reply)
- Español argentino, tono humano y profesional (no robótico, no plantilla obvia).
- Breve y al grano (máx ~120 palabras). 1 saludo, respondé lo que preguntan, 1 CTA claro.
- Si es un prospecto, alineá con la oferta de Automiq (agentes IA / automatización /
  landings / ads para PyMEs argentinas), pero sin ser vendedor agresivo.
- Si NO tenés info suficiente para responder con certeza (precio exacto, dato interno),
  redactá una respuesta que pida los datos faltantes o proponga una llamada — NO inventes.
- Firmá como "Equipo Automiq".
- NUNCA prometas algo que no podés cumplir. NUNCA inventes precios o plazos concretos.

## Formato de salida (OBLIGATORIO)
Devolvé EXCLUSIVAMENTE un array JSON válido (sin texto antes ni después, sin ```),
un objeto por hilo recibido, en el MISMO orden:

[
  {
    "thread_id": "<el thread_id que te pasé>",
    "should_reply": true,
    "reason": "por qué sí/no responder (1 frase)",
    "draft_reply": "el cuerpo completo de la respuesta (vacío si should_reply=false)"
  }
]
""".strip()


def _parse_llm_json(text: str) -> List[Dict[str, Any]]:
    """Extrae el array JSON de la respuesta del LLM de forma robusta."""
    if not text:
        return []
    # Quitar fences ```json ... ```
    fence = re.search(r"```(?:json)?\s*(.+?)```", text, re.DOTALL)
    candidate = fence.group(1) if fence else text
    # Tomar desde el primer [ hasta el último ]
    start = candidate.find("[")
    end = candidate.rfind("]")
    if start == -1 or end == -1 or end <= start:
        return []
    blob = candidate[start : end + 1]
    try:
        data = json.loads(blob)
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        return []


class InboxAssistantAgent(BaseAgent):
    name = "inbox_assistant"
    description = "Lee la bandeja de Automiq y redacta borradores de respuesta (read + drafts, no envía)"
    schedule = "0 9 * * *"   # diario 09:00 ART — liviano, no usa Claude Code
    timezone = "America/Buenos_Aires"
    max_tokens = 6000
    temperature = 0.6
    use_claude_code = False   # composición de texto pura → no consume como un run CC

    @property
    def system_prompt(self) -> str:
        return f"{get_context_block()}\n\n{INBOX_INSTRUCTIONS}"

    def build_user_message(self, ctx: AgentContext) -> str:
        if not ctx.settings.gmail_configured:
            ctx.args["_inbox_status"] = "not_configured"
            return (
                "El Inbox Assistant todavía NO está configurado (faltan las credenciales "
                "GMAIL_* en las env vars). Respondé EXACTAMENTE con este texto y nada más: "
                "'⚙️ Inbox Assistant pendiente de configuración OAuth (Gmail). Ver "
                "scripts/gmail_oauth_setup.py.'"
            )

        max_threads = int(ctx.args.get("max_threads", ctx.settings.inbox_max_threads)) if isinstance(ctx.args, dict) else ctx.settings.inbox_max_threads
        try:
            client = get_gmail_client(ctx.settings)
            threads = client.list_unread_threads(max_threads=max_threads)
        except GmailError as e:
            ctx.args["_inbox_status"] = "gmail_error"
            ctx.args["_inbox_error"] = str(e)
            return (
                f"No pude leer la bandeja (error de Gmail: {e}). Respondé EXACTAMENTE: "
                f"'⚠️ Inbox Assistant: error de acceso a Gmail — {e}'"
            )

        # Guardar lookup determinístico por thread para post_process (to/subject confiables)
        lookup: Dict[str, Dict[str, Any]] = {}
        blocks: List[str] = []
        for i, th in enumerate(threads, 1):
            last = th.last_message
            lookup[th.thread_id] = {
                "to": th.last_from_email or last.sender_email,
                "to_display": th.last_from,
                "subject": th.subject,
                "last_msg_id": last.msg_id,
            }
            blocks.append(
                f"### Hilo {i}\n"
                f"- thread_id: {th.thread_id}\n"
                f"- De: {th.last_from}\n"
                f"- Asunto: {th.subject}\n"
                f"- Conversación:\n{th.transcript(max_chars=3500)}"
            )

        ctx.args["_inbox_status"] = "ok"
        ctx.args["_inbox_threads"] = lookup
        ctx.args["_inbox_count"] = len(threads)

        if not threads:
            ctx.args["_inbox_status"] = "empty"
            return (
                "No hay hilos no leídos en la bandeja en este momento. Respondé EXACTAMENTE: "
                "'📭 Bandeja al día — sin emails no leídos para responder.'"
            )

        header = (
            f"Tenés {len(threads)} hilo(s) de email NO leídos en la bandeja de Automiq. "
            "Por cada hilo decidí si corresponde responder y, si sí, redactá el borrador. "
            "Devolvé el array JSON especificado (un objeto por hilo, mismo orden).\n\n"
        )
        return header + "\n\n".join(blocks)

    def post_process(self, response_text: str, ctx: AgentContext) -> str:
        status = ctx.args.get("_inbox_status") if isinstance(ctx.args, dict) else None

        # Estados sin drafting: persistir el texto tal cual (lo hace el base).
        if status in (None, "not_configured", "gmail_error", "empty"):
            return super().post_process(response_text, ctx)

        lookup: Dict[str, Dict[str, Any]] = ctx.args.get("_inbox_threads", {})
        items = _parse_llm_json(response_text)
        if not items:
            log.warning("inbox_no_json_parsed", run_id=ctx.run_id)
            summary = (
                "⚠️ Inbox Assistant: no pude parsear las respuestas del modelo en JSON. "
                "No se crearon borradores. Salida cruda guardada.\n\n" + (response_text or "")
            )
            return super().post_process(summary, ctx)

        dry_run = bool(ctx.args.get("dry_run")) if isinstance(ctx.args, dict) else False
        client = None
        if not dry_run:
            try:
                client = get_gmail_client(ctx.settings)
            except GmailError as e:
                log.error("inbox_gmail_unavailable_postprocess", error=str(e))

        created, skipped, errors = [], [], []
        for it in items:
            tid = (it or {}).get("thread_id", "")
            meta = lookup.get(tid)
            should = bool(it.get("should_reply"))
            reply = (it.get("draft_reply") or "").strip()
            reason = (it.get("reason") or "").strip()
            subj = meta["subject"] if meta else it.get("subject", "(sin asunto)")
            to = meta["to"] if meta else it.get("to", "")

            if not should or not reply:
                skipped.append(f"• **{subj}** → no responder ({reason or 's/d'})")
                continue
            if not meta:
                errors.append(f"• thread_id desconocido `{tid}` — borrador NO creado")
                continue
            if dry_run or client is None:
                created.append(f"• **{subj}** → (dry-run) borrador para {to}:\n  > {reply[:200]}")
                continue
            try:
                draft_id = client.create_draft(
                    thread_id=tid, to=to, subject=subj, body=reply,
                    in_reply_to_msg_id=meta.get("last_msg_id"),
                )
                created.append(f"• **{subj}** → ✅ borrador `{draft_id}` para {to}")
            except Exception as e:
                log.error("inbox_draft_failed", thread_id=tid, error=str(e))
                errors.append(f"• **{subj}** → ❌ falló crear borrador: {e}")

        log.info("inbox_done", run_id=ctx.run_id,
                 created=len(created), skipped=len(skipped), errors=len(errors))

        parts = [
            f"# 📬 Inbox Assistant — {ctx.args.get('_inbox_count', 0)} hilo(s) no leídos",
            "",
            f"**Borradores creados:** {len(created)} · **Omitidos:** {len(skipped)} · **Errores:** {len(errors)}",
            "",
        ]
        if created:
            parts += ["## ✅ Borradores creados (revisá y mandá desde Gmail)", *created, ""]
        if skipped:
            parts += ["## ⏭️ Omitidos (no requieren respuesta)", *skipped, ""]
        if errors:
            parts += ["## ⚠️ Errores", *errors, ""]
        summary = "\n".join(parts)
        return super().post_process(summary, ctx)
