"""
Inbox Assistant — lee la bandeja de la cuenta dedicada de Automiq
(automiqaiagency@gmail.com) y RESPONDE los hilos apuntando SIEMPRE a agendar una reunión.

Flujo (determinístico + LLM):
  1. build_user_message: trae los hilos NO leídos vía Gmail API (Python, no tool-use)
     y los mete en el prompt, con el link de agenda / horarios para ofrecer.
  2. El LLM (MiniMax-M3) decide por hilo si conviene responder y redacta la respuesta
     orientada a cerrar una reunión.
  3. post_process: parsea el JSON del LLM y, según `inbox_auto_send`:
     - True  → ENVÍA la respuesta dentro del hilo (send_reply). Cierra el loop solo.
     - False → crea un BORRADOR (drafts.create) para revisión humana.

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
from ..integrations import leads_store as ls
from ..log import get_logger

log = get_logger("inbox_assistant")


INBOX_INSTRUCTIONS = """
# Inbox Assistant — Automiq (cierra reuniones)

Sos el asistente de bandeja de Automiq. Recibís hilos de email NO leídos de la casilla
de la agencia y, por cada uno, decidís si corresponde responder y redactás la respuesta.
Tu RESPUESTA SE MANDA SOLA, así que escribila lista para enviar.

## Objetivo nº1 de CADA respuesta: AGENDAR UNA REUNIÓN
Toda respuesta a una persona real tiene que terminar empujando, de forma natural y sin
ser pesado, a una llamada/reunión corta (15-20 min) para mostrarles cómo Automiq les
resuelve su problema. La reunión es la conversión: priorizá cerrarla por encima de
responder cada detalle por mail.

## Cómo decidir si responder (should_reply)
- ✅ Respondé: consultas de prospectos/clientes, pedidos de info, preguntas comerciales,
  follow-ups de gente real, partners, cualquiera que muestre interés.
- ❌ NO respondas (should_reply=false): newsletters, notificaciones automáticas,
  no-reply@, facturas/recibos, spam, promociones, confirmaciones de plataformas,
  o cualquier cosa que claramente no espera respuesta humana.

## Cómo redactar la respuesta (reply)  — se ENVÍA tal cual
- Español argentino, tono humano y cálido (no robótico, no plantilla obvia, sin "Estimado señor").
- Breve y al grano (máx ~110 palabras): 1 saludo + respondé lo justo que preguntan + el CTA a reunión.
- Conectá lo que preguntan con la oferta de Automiq (agentes IA / automatización / landings /
  ads para PyMEs) en 1 frase concreta de beneficio, sin ser vendedor agresivo.
- **CTA a reunión (OBLIGATORIO si should_reply=true):**
  - Si te paso un LINK DE AGENDA, ofrecelo claro: "Si querés lo charlamos 15 min, agendá el
    horario que te quede cómodo acá: <link>".
  - Si NO hay link, proponé 2 ventanas concretas y pedí que confirmen: "¿Te viene bien un
    Meet de 15 min mañana 11h o pasado 16h (ART)? Decime cuál y te paso el invite."
- Si NO tenés un dato puntual (precio exacto, algo interno), NO lo inventes: usá eso mismo
  como excusa perfecta para la reunión ("eso lo vemos en 15 min según tu caso").
- Firmá como "Equipo Automiq". NUNCA prometas algo que no podés cumplir ni inventes precios/plazos.

## Formato de salida (OBLIGATORIO)
Devolvé EXCLUSIVAMENTE un array JSON válido (sin texto antes ni después, sin ```),
un objeto por hilo recibido, en el MISMO orden:

[
  {
    "thread_id": "<el thread_id que te pasé>",
    "should_reply": true,
    "reason": "por qué sí/no responder (1 frase)",
    "reply": "el cuerpo completo de la respuesta, listo para enviar (vacío si should_reply=false)"
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
    description = "Responde la bandeja de Automiq apuntando a agendar reuniones (auto-send o borradores)"
    # Varias pasadas al día = speed-to-lead: contestar rápido dispara las reuniones.
    schedule = "0 9,12,15,18 * * *"   # 09/12/15/18 ART — liviano, no usa Claude Code
    timezone = "America/Buenos_Aires"
    max_tokens = 6000
    temperature = 0.6
    use_claude_code = False   # composición de texto pura → no consume como un run CC

    @property
    def system_prompt(self) -> str:
        return f"{get_context_block()}\n\n{INBOX_INSTRUCTIONS}"

    def _booking_block(self, ctx: AgentContext) -> str:
        """Contexto de agenda para que el CTA de cada respuesta cierre la reunión."""
        url = (ctx.settings.booking_url or "").strip()
        if url:
            return (
                f"\n\n## LINK DE AGENDA (usalo en el CTA de cada respuesta)\n"
                f"Ofrecé este link para que reserven el horario que quieran: {url}\n"
            )
        return (
            "\n\n## SIN LINK DE AGENDA\n"
            "No hay link de agenda configurado: proponé 2 ventanas concretas de 15 min "
            "(ej. 'mañana 11h o pasado 16h ART') y pedí que confirmen cuál les sirve.\n"
        )

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

        # ── Cierre del loop de ventas: ¿alguno que respondió es un lead nuestro? ──
        # Si el remitente matchea un lead en seguimiento, lo marcamos "respondió"
        # (frena la secuencia de outbound) y lo levantamos como LEAD CALIENTE.
        hot: List[Dict[str, Any]] = []
        try:
            store = ls.load_store()
            seen_keys = set()
            for th in threads:
                emails = {th.last_from_email, *(th.participants or [])}
                for em in emails:
                    if not em:
                        continue
                    lead = ls.mark_replied(store, email=em)
                    if lead and lead.get("key") not in seen_keys:
                        seen_keys.add(lead.get("key"))
                        hot.append({
                            "company": lead.get("company", "?"),
                            "email": lead.get("email", em),
                            "decisor": lead.get("decisor", ""),
                            "subject": th.subject,
                            "thread_id": th.thread_id,
                        })
            if hot:
                ls.save_store(store)
                log.info("inbox_hot_leads", run_id=ctx.run_id, count=len(hot))
        except Exception as e:
            log.warning("inbox_lead_linking_failed", error=str(e))
        ctx.args["_inbox_hot"] = hot

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
            "Por cada hilo decidí si corresponde responder y, si sí, redactá la respuesta "
            "lista para enviar, SIEMPRE empujando a agendar una reunión. "
            "Devolvé el array JSON especificado (un objeto por hilo, mismo orden)."
            + self._booking_block(ctx) + "\n"
        )
        return header + "\n\n".join(blocks)

    def _fire_hot_alert(self, ctx: AgentContext, hot: List[Dict[str, Any]]) -> None:
        """Aviso separado y prominente al canal de ventas cuando un lead responde.
        Va aparte del reporte normal del inbox para que NO se pase por alto."""
        if not ctx.discord:
            return
        lines = ["**Respondieron y ya frené su secuencia. Andá a cerrar la reunión:**", ""]
        for h in hot:
            who = f" · {h['decisor']}" if h.get("decisor") else ""
            lines.append(f"• **{h['company']}** <{h['email']}>{who}\n  asunto: _{h.get('subject', '')}_")
        try:
            ctx.discord.send_agent_output(
                agent_name="🔥 Lead respondió",
                text="\n".join(lines),
                run_id=ctx.run_id,
                url=ctx.settings.discord_webhook_for("outbound"),
                color=0xF1C40F,  # amarillo "atención"
            )
        except Exception as e:
            log.warning("inbox_hot_alert_failed", error=str(e))

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
        auto = bool(ctx.settings.inbox_auto_send)
        live = auto and not dry_run   # True → ENVÍA; False → crea borrador
        client = None
        try:
            client = get_gmail_client(ctx.settings)
        except GmailError as e:
            log.error("inbox_gmail_unavailable_postprocess", error=str(e))

        verb = "respuesta enviada" if live else "borrador"
        created, skipped, errors = [], [], []
        for it in items:
            tid = (it or {}).get("thread_id", "")
            meta = lookup.get(tid)
            should = bool(it.get("should_reply"))
            # `reply` es el campo nuevo; toleramos `draft_reply` por compatibilidad.
            reply = (it.get("reply") or it.get("draft_reply") or "").strip()
            reason = (it.get("reason") or "").strip()
            subj = meta["subject"] if meta else it.get("subject", "(sin asunto)")
            to = meta["to"] if meta else it.get("to", "")

            if not should or not reply:
                skipped.append(f"• **{subj}** → no responder ({reason or 's/d'})")
                continue
            if not meta:
                errors.append(f"• thread_id desconocido `{tid}` — {verb} NO creada")
                continue
            if client is None:
                errors.append(f"• **{subj}** → ❌ Gmail no disponible, sin {verb}")
                continue
            if not live:
                try:
                    draft_id = client.create_draft(
                        thread_id=tid, to=to, subject=subj, body=reply,
                        in_reply_to_msg_id=meta.get("last_msg_id"),
                    )
                    created.append(f"• **{subj}** → 📝 borrador `{draft_id}` para {to}")
                except Exception as e:
                    log.error("inbox_draft_failed", thread_id=tid, error=str(e))
                    errors.append(f"• **{subj}** → ❌ falló crear borrador: {e}")
                continue
            try:
                msg_id = client.send_reply(
                    thread_id=tid, to=to, subject=subj, body=reply,
                    from_name=ctx.settings.outbound_from_name,
                )
                created.append(f"• **{subj}** → ✅ respondido a {to} (`{msg_id[:10]}`)")
            except Exception as e:
                log.error("inbox_send_failed", thread_id=tid, error=str(e))
                errors.append(f"• **{subj}** → ❌ falló enviar: {e}")

        log.info("inbox_done", run_id=ctx.run_id, live=live,
                 created=len(created), skipped=len(skipped), errors=len(errors))

        hot = ctx.args.get("_inbox_hot", []) if isinstance(ctx.args, dict) else []
        parts = [
            f"# 📬 Inbox Assistant — {ctx.args.get('_inbox_count', 0)} hilo(s) no leídos",
            "",
        ]
        if hot:
            parts += [
                "## 🔥 LEADS QUE RESPONDIERON — ¡cerrá la reunión!",
                "_Estos contestaron y ya frené su secuencia automática. Entrá vos a cerrar:_",
            ]
            for h in hot:
                who = f" · {h['decisor']}" if h.get("decisor") else ""
                parts.append(f"• **{h['company']}** <{h['email']}>{who} — _{h.get('subject', '')}_")
            parts.append("")
        mode = "RESPUESTAS ENVIADAS" if live else "BORRADORES (auto-send OFF)"
        label_count = "Respondidos" if live else "Borradores"
        parts += [
            f"_Modo: **{mode}**_",
            f"**{label_count}:** {len(created)} · **Omitidos:** {len(skipped)} · **Errores:** {len(errors)}",
            "",
        ]
        if hot:
            self._fire_hot_alert(ctx, hot)
        if created:
            title = ("## ✅ Respuestas enviadas (apuntando a reunión)" if live
                     else "## 📝 Borradores creados (revisá y mandá desde Gmail)")
            parts += [title, *created, ""]
        if skipped:
            parts += ["## ⏭️ Omitidos (no requieren respuesta)", *skipped, ""]
        if errors:
            parts += ["## ⚠️ Errores", *errors, ""]
        summary = "\n".join(parts)
        return super().post_process(summary, ctx)
