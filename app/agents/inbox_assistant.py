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
from ..integrations.calendar_client import get_calendar_client, CalendarError
from ..integrations import inbox_state
from ..integrations import leads_store as ls
from ..integrations import meetings_store as ms
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
- Si NO tenés un dato puntual (precio exacto, algo interno), NO lo inventes: usá eso mismo
  como excusa perfecta para la reunión ("eso lo vemos en 15 min según tu caso").
- Firmá como "Equipo Automiq". NUNCA prometas algo que no podés cumplir ni inventes precios/plazos.

## Dos situaciones para el CTA (MUY IMPORTANTE)
**(A) Todavía NO acordaron un horario concreto** → proponé y pedí que confirmen:
  - Con LINK DE AGENDA: "Si querés lo charlamos 15 min, reservá el horario que te quede cómodo acá: <link>".
  - Sin link: proponé 2 ventanas concretas: "¿Te viene bien un Meet de 15 min mañana 11h o pasado 16h (ART)? Decime cuál y te paso el invite con el link."
  En este caso dejá `book.confirm` en false.

**(B) El prospecto YA eligió/confirmó un día y hora puntual** (en su último mensaje dice algo
  como "dale, el jueves a las 15h", "me sirve mañana 11", etc.) → cerralo: poné
  `book.confirm=true` con la fecha/hora en ISO-8601 con offset ART (-03:00) y, en `reply`,
  CONFIRMÁ la reunión e incluí LITERALMENTE el token `{{MEET_LINK}}` donde irá el link del Meet
  (yo lo reemplazo por el link real). Ej. de reply: "¡Listo! Te agendé para el jueves 15h.
  Acá tenés el link del Meet: {{MEET_LINK}} — nos vemos ahí. Equipo Automiq."

## Formato de salida (OBLIGATORIO)
Devolvé EXCLUSIVAMENTE un array JSON válido (sin texto antes ni después, sin ```),
un objeto por hilo recibido, en el MISMO orden:

[
  {
    "thread_id": "<el thread_id que te pasé>",
    "should_reply": true,
    "reason": "por qué sí/no responder (1 frase)",
    "reply": "el cuerpo completo de la respuesta, listo para enviar (vacío si should_reply=false)",
    "book": {
      "confirm": false,
      "datetime_iso": "",
      "duration_min": 20,
      "title": ""
    }
  }
]

En `book`: `confirm` true SOLO si el prospecto ya eligió un horario puntual (situación B).
`datetime_iso` ej. "2026-06-27T15:00:00-03:00". `title` ej. "Automiq × <empresa> — demo".
Si no hay horario confirmado, dejá `confirm:false` y `datetime_iso:""`.
""".strip()


def _parse_llm_json(text: str) -> List[Dict[str, Any]]:
    """Extrae el array JSON de la respuesta del LLM (parser robusto único en
    _common: el parse frágil de acá era el mismo que dejó a outbound un día
    entero en 0 mails con OpenCode+GLM — narración alrededor, \\n crudos)."""
    from ._common import extract_json_array
    return extract_json_array(text, required_key="thread_id")


class InboxAssistantAgent(BaseAgent):
    name = "inbox_assistant"
    description = "Responde la bandeja de Automiq apuntando a agendar reuniones (auto-send o borradores)"
    # Varias pasadas al día = speed-to-lead: contestar rápido dispara las reuniones.
    schedule = "0 9,12,15,18 * * *"   # 09/12/15/18 ART — liviano, no usa Claude Code
    timezone = "America/Buenos_Aires"
    max_tokens = 6000
    temperature = 0.6
    use_claude_code = False   # composición de texto pura → no consume como un run CC
    llm_provider = "glm"      # OpenCode+GLM: harness con skills (gratis); fallback MiniMax
    claude_code_skill = "humanizer"

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

    def _link_replies(self, ctx: AgentContext, threads, own_email: str) -> List[Dict[str, Any]]:
        """Marca "respondió" a todo lead que haya escrito en alguno de estos hilos
        (frena su secuencia de outbound) y devuelve los LEADS CALIENTES nuevos.
        Sólo entra al aviso 🔥 si su estado CAMBIÓ en esta corrida (si ya estaba
        "respondió" no se re-alerta cada 3 horas)."""
        hot: List[Dict[str, Any]] = []
        _quiet_states = ("respondió", "reunión", "propuesta", "cerrado")
        try:
            store = ls.load_store()
            seen_keys = set()
            for th in threads:
                emails = {th.last_from_email, *(th.participants or [])}
                for em in emails:
                    if not em or (own_email and em.lower() == own_email):
                        continue
                    prev = next((l.get("state") for l in store.get("leads", {}).values()
                                 if ls.normalize_email(l.get("email", "")) == ls.normalize_email(em)), None)
                    lead = ls.mark_replied(store, email=em)
                    if lead and lead.get("key") not in seen_keys and prev not in _quiet_states:
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
        return hot

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
            # LEÍDOS O NO: si el operador abre un mail en el teléfono, el hilo deja de
            # estar unread pero la respuesta sigue sin atender. El dedup de "ya lo
            # procesé" lo lleva inbox_state, no el estado de lectura de Gmail.
            all_threads = client.list_recent_threads(max_threads=max_threads * 3)
            own_email = client.profile_email()
        except GmailError as e:
            ctx.args["_inbox_status"] = "gmail_error"
            ctx.args["_inbox_error"] = str(e)
            return (
                f"No pude leer la bandeja (error de Gmail: {e}). Respondé EXACTAMENTE: "
                f"'⚠️ Inbox Assistant: error de acceso a Gmail — {e}'"
            )

        # ── Cierre del loop de ventas SOBRE TODOS LOS HILOS (antes de filtrar) ──
        # Si un lead nuestro escribió EN CUALQUIER mensaje del hilo, marcarlo
        # "respondió" (frena su secuencia) aunque el último mensaje sea nuestro.
        # Caso real: la respuesta no se detectó a tiempo y outbound le mandó otro
        # follow-up al mismo hilo → el hilo termina en nosotros, pero el lead
        # RESPONDIÓ y su secuencia tiene que frenar igual.
        hot = self._link_replies(ctx, all_threads, own_email)

        threads = []
        for th in all_threads:
            last = th.last_message
            # Guard determinístico anti-doble-respuesta: si el último mensaje del hilo
            # es NUESTRO (ya respondimos, o lo mandamos nosotros), no hay nada que
            # atender. Antes esto dependía de que el LLM "se diera cuenta".
            if own_email and (last.sender_email or "").lower() == own_email:
                inbox_state.mark_processed(th.thread_id, last.msg_id, action="own_last")
                continue
            # Ya atendido en una corrida previa y sin mensajes nuevos → skip.
            if inbox_state.already_processed(th.thread_id, last.msg_id):
                continue
            threads.append(th)
        threads = threads[:max_threads]

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

        ctx.args["_inbox_hot"] = hot
        ctx.args["_inbox_status"] = "ok"
        ctx.args["_inbox_threads"] = lookup
        ctx.args["_inbox_count"] = len(threads)

        if not threads:
            ctx.args["_inbox_status"] = "empty"
            return (
                "No hay hilos nuevos por atender en la bandeja en este momento. Respondé EXACTAMENTE: "
                "'📭 Bandeja al día — sin emails nuevos para responder.'"
            )

        header = (
            f"Tenés {len(threads)} hilo(s) de email con mensajes NUEVOS en la bandeja de Automiq. "
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

    def _fire_booked_alert(self, ctx: AgentContext, booked: List[str]) -> None:
        """Aviso prominente al canal de ventas cuando se cierra una reunión."""
        if not ctx.discord:
            return
        try:
            ctx.discord.send_agent_output(
                agent_name="🎉 Reunión agendada",
                text="**El Inbox Assistant cerró una reunión (Meet creado + en el panel):**\n\n"
                     + "\n".join(booked),
                run_id=ctx.run_id,
                url=ctx.settings.discord_webhook_for("outbound"),
                color=0x2ECC71,  # verde "ganamos"
            )
        except Exception as e:
            log.warning("inbox_booked_alert_failed", error=str(e))

    def _book_meeting(self, ctx: AgentContext, book: Dict[str, Any], company: str, email: str):
        """Crea el evento con Google Meet y lo registra en el panel (meetings_store).
        Devuelve (meet_link, cuando_legible). Si falla, (None, '')."""
        dt_iso = (book.get("datetime_iso") or "").strip()
        title = (book.get("title") or f"Automiq × {company}").strip()
        try:
            dur = int(book.get("duration_min") or 20)
        except (TypeError, ValueError):
            dur = 20
        try:
            cal = get_calendar_client(ctx.settings)
            ev = cal.create_meet_event(
                summary=title, start_iso=dt_iso, duration_min=dur,
                attendee_email=email or None,
                description=f"Reunión agendada automáticamente por el Inbox Assistant de Automiq.\nContacto: {email}",
            )
        except (CalendarError, Exception) as e:
            log.error("inbox_book_failed", email=email, error=str(e))
            return None, ""

        meet_link = ev.get("meet_link") or ev.get("html_link") or ""
        # Registrar en el panel (agenda de la agencia) para que meeting_prep la prepare.
        try:
            ms.create_meeting(
                client_id=None, client_name=company or email or "Prospecto",
                title=title, scheduled_at=ev.get("start") or dt_iso,
                location=meet_link, notes=f"Agendada por Inbox Assistant · {email}",
            )
        except Exception as e:
            log.warning("inbox_meeting_log_failed", error=str(e))
        when = (ev.get("start") or dt_iso or "").replace("T", " ")[:16]
        return meet_link, when

    def _reformat_via_minimax(self, ctx: AgentContext, raw: str) -> List[Dict[str, Any]]:
        """Convierte una salida no-parseable al array JSON del contrato (1 intento)."""
        raw = (raw or "").strip()
        if not raw or ctx.minimax is None:
            return []
        try:
            resp = ctx.minimax.complete(
                system=("Sos un conversor de formato. Te paso la salida de otro modelo que "
                        "debía devolver un array JSON con objetos "
                        '{"thread_id","should_reply","reason","reply","book"} pero vino en '
                        "otro formato. Extraé esos datos y devolvé EXCLUSIVAMENTE el array "
                        "JSON válido, sin texto adicional. Si no hay datos, devolvé []."),
                messages=[{"role": "user", "content": raw[:20000]}],
                max_tokens=self.max_tokens,
                temperature=0.1,
            )
            items = _parse_llm_json(resp.text)
            log.info("inbox_reformat_minimax", got=len(items))
            return items
        except Exception as e:
            log.error("inbox_reformat_failed", error=str(e)[:200])
            return []

    def post_process(self, response_text: str, ctx: AgentContext) -> str:
        status = ctx.args.get("_inbox_status") if isinstance(ctx.args, dict) else None

        # Estados sin drafting: persistir el texto tal cual (lo hace el base).
        if status in (None, "not_configured", "gmail_error", "empty"):
            return super().post_process(response_text, ctx)

        lookup: Dict[str, Dict[str, Any]] = ctx.args.get("_inbox_threads", {})
        items = _parse_llm_json(response_text)
        if not items:
            # Red de seguridad (mismo espíritu que _redraft_missing de outbound):
            # las respuestas suelen estar redactadas en el texto, solo que en un
            # formato que no parsea → UNA pasada de MiniMax lo re-formatea.
            items = self._reformat_via_minimax(ctx, response_text)
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
        created, skipped, errors, booked = [], [], [], []
        for it in items:
            tid = (it or {}).get("thread_id", "")
            meta = lookup.get(tid)
            should = bool(it.get("should_reply"))
            # `reply` es el campo nuevo; toleramos `draft_reply` por compatibilidad.
            reply = (it.get("reply") or it.get("draft_reply") or "").strip()
            reason = (it.get("reason") or "").strip()
            subj = meta["subject"] if meta else it.get("subject", "(sin asunto)")
            to = meta["to"] if meta else it.get("to", "")
            book = it.get("book") if isinstance(it.get("book"), dict) else {}
            wants_book = bool(book.get("confirm")) and bool((book.get("datetime_iso") or "").strip())

            if not should or not reply:
                skipped.append(f"• **{subj}** → no responder ({reason or 's/d'})")
                if meta:
                    inbox_state.mark_processed(tid, meta.get("last_msg_id", ""), action="skipped")
                continue
            if not meta:
                errors.append(f"• thread_id desconocido `{tid}` — {verb} NO creada")
                continue
            if client is None:
                errors.append(f"• **{subj}** → ❌ Gmail no disponible, sin {verb}")
                continue

            # ── Agendar reunión (crear Meet) si el prospecto confirmó horario ──
            # Sólo en modo live (crear un evento real es una acción, como enviar).
            if wants_book and live:
                meet_link, when = self._book_meeting(ctx, book, company=subj, email=to)
                if meet_link:
                    reply = reply.replace("{{MEET_LINK}}", meet_link)
                    booked.append(f"• **{subj}** <{to}> → 📅 {when} · Meet: {meet_link}")
                else:
                    # No se pudo crear el Meet: que la respuesta no quede rota.
                    reply = reply.replace(
                        "{{MEET_LINK}}",
                        "te lo confirmo en un toque por acá")
            else:
                # Sin booking (o draft): limpiar el token si quedó.
                reply = reply.replace(
                    "{{MEET_LINK}}",
                    "(coordinamos el link cuando confirmes el horario)")

            if not live:
                try:
                    draft_id = client.create_draft(
                        thread_id=tid, to=to, subject=subj, body=reply,
                        in_reply_to_msg_id=meta.get("last_msg_id"),
                    )
                    created.append(f"• **{subj}** → 📝 borrador `{draft_id}` para {to}")
                    inbox_state.mark_processed(tid, meta.get("last_msg_id", ""), action="draft")
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
                inbox_state.mark_processed(tid, meta.get("last_msg_id", ""), action="replied")
            except Exception as e:
                log.error("inbox_send_failed", thread_id=tid, error=str(e))
                errors.append(f"• **{subj}** → ❌ falló enviar: {e}")

        ctx.args["_inbox_booked"] = booked
        log.info("inbox_done", run_id=ctx.run_id, live=live, booked=len(booked),
                 created=len(created), skipped=len(skipped), errors=len(errors))

        hot = ctx.args.get("_inbox_hot", []) if isinstance(ctx.args, dict) else []
        booked = ctx.args.get("_inbox_booked", []) if isinstance(ctx.args, dict) else []
        parts = [
            f"# 📬 Inbox Assistant — {ctx.args.get('_inbox_count', 0)} hilo(s) con mensajes nuevos",
            "",
        ]
        if booked:
            parts += [
                "## 🎉 REUNIONES AGENDADAS (Meet creado + cargado al panel)",
                *booked, "",
            ]
            self._fire_booked_alert(ctx, booked)
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
