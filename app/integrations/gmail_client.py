"""
Gmail client — integración para el Inbox Assistant.

Cuenta dedicada: automiqaiagency@gmail.com. Auth OAuth2 con refresh token
(client_id + client_secret + refresh_token en env / Settings).

Scopes usados: gmail.readonly + gmail.compose → LEER + crear/enviar.
(gmail.compose habilita messages.send, así que el cliente puede enviar.)

Métodos:
  - list_unread_threads() / get_thread()  → lectura
  - create_draft()  → BORRADOR (drafts.create), no envía
  - send_message()  → ENVÍA un email nuevo (outbound cold-email)
  - send_reply()    → ENVÍA una respuesta dentro de un hilo (inbox_assistant auto-send)

⚠️ El ENVÍO está gateado por settings (outbound_auto_send / inbox_auto_send):
con esos flags en False, los agentes sólo crean borradores / previews.
"""
from __future__ import annotations

import base64
import re
from dataclasses import dataclass, field
from email.mime.text import MIMEText
from email.utils import parseaddr
from typing import List, Optional

from ..config import Settings
from ..log import get_logger

log = get_logger("gmail")

# Scopes mínimos: leer + componer borradores. NO incluimos gmail.send.
GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
]

TOKEN_URI = "https://oauth2.googleapis.com/token"


class GmailError(RuntimeError):
    pass


@dataclass
class GmailMessage:
    msg_id: str
    thread_id: str
    sender: str          # "Nombre <email>"
    sender_email: str
    to: str
    subject: str
    date: str
    snippet: str
    body_text: str
    label_ids: List[str] = field(default_factory=list)

    @property
    def is_unread(self) -> bool:
        return "UNREAD" in self.label_ids


@dataclass
class GmailThread:
    thread_id: str
    subject: str
    last_from: str          # remitente del último mensaje
    last_from_email: str
    participants: List[str]
    messages: List[GmailMessage]

    @property
    def last_message(self) -> GmailMessage:
        return self.messages[-1]

    def transcript(self, max_chars: int = 4000) -> str:
        """Texto plano del hilo, para meter en el prompt del LLM."""
        out = []
        for m in self.messages:
            out.append(f"--- De: {m.sender} | {m.date}\n{m.body_text.strip()}")
        joined = "\n\n".join(out)
        return joined[:max_chars]


def _b64url_decode(data: str) -> bytes:
    if not data:
        return b""
    pad = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + pad)


def _extract_body(payload: dict) -> str:
    """Recorre las partes MIME y devuelve el text/plain (o text/html limpio)."""
    if not payload:
        return ""

    # Caso simple: cuerpo directo
    mime = payload.get("mimeType", "")
    body = payload.get("body", {})
    data = body.get("data")

    parts = payload.get("parts")
    if parts:
        # Preferir text/plain; si no hay, caer a text/html
        plain = ""
        html = ""
        for p in parts:
            t = _extract_body(p)
            if p.get("mimeType", "").startswith("text/plain") and t:
                plain = plain or t
            elif p.get("mimeType", "").startswith("text/html") and t:
                html = html or t
            elif t:
                plain = plain or t
        return plain or html

    if data:
        raw = _b64url_decode(data).decode("utf-8", errors="replace")
        if mime == "text/html":
            raw = re.sub(r"<[^>]+>", " ", raw)
            raw = re.sub(r"\s+", " ", raw)
        return raw
    return ""


def _header(headers: List[dict], name: str) -> str:
    for h in headers or []:
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


class GmailClient:
    def __init__(self, settings: Settings):
        self.s = settings
        self.user_id = settings.gmail_user_id or "me"
        self._service = None

    # ── auth ──
    def _build_service(self):
        if self._service is not None:
            return self._service
        try:
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build
        except ImportError as e:  # pragma: no cover
            raise GmailError(
                "Faltan dependencias de Gmail (google-api-python-client / google-auth). "
                "Agregalas a requirements.txt y redeployá."
            ) from e

        if not self.s.gmail_configured:
            raise GmailError(
                "Gmail no configurado: faltan GMAIL_CLIENT_ID / GMAIL_CLIENT_SECRET / "
                "GMAIL_REFRESH_TOKEN en las env vars."
            )

        creds = Credentials(
            token=None,
            refresh_token=self.s.gmail_refresh_token,
            client_id=self.s.gmail_client_id,
            client_secret=self.s.gmail_client_secret,
            token_uri=TOKEN_URI,
            scopes=GMAIL_SCOPES,
        )
        self._service = build("gmail", "v1", credentials=creds, cache_discovery=False)
        return self._service

    # ── lectura ──
    def list_unread_threads(
        self, max_threads: Optional[int] = None, lookback_days: Optional[int] = None
    ) -> List[GmailThread]:
        """Lista los hilos con mensajes no leídos en la bandeja (excluye spam/promociones)."""
        svc = self._build_service()
        max_threads = max_threads or self.s.inbox_max_threads
        lookback_days = lookback_days or self.s.inbox_lookback_days

        # is:unread en INBOX, no categorías promo/social, ventana reciente
        query = f"is:unread in:inbox newer_than:{lookback_days}d -category:promotions -category:social"
        resp = (
            svc.users()
            .threads()
            .list(userId=self.user_id, q=query, maxResults=max_threads)
            .execute()
        )
        threads_meta = resp.get("threads", []) or []
        out: List[GmailThread] = []
        for tm in threads_meta[:max_threads]:
            try:
                out.append(self.get_thread(tm["id"]))
            except Exception as e:
                log.warning("gmail_thread_fetch_failed", thread_id=tm.get("id"), error=str(e))
        log.info("gmail_listed_unread", count=len(out), query=query)
        return out

    def get_thread(self, thread_id: str) -> GmailThread:
        svc = self._build_service()
        t = (
            svc.users()
            .threads()
            .get(userId=self.user_id, id=thread_id, format="full")
            .execute()
        )
        messages: List[GmailMessage] = []
        for m in t.get("messages", []):
            payload = m.get("payload", {})
            headers = payload.get("headers", [])
            sender = _header(headers, "From")
            _, sender_email = parseaddr(sender)
            messages.append(
                GmailMessage(
                    msg_id=m.get("id", ""),
                    thread_id=thread_id,
                    sender=sender,
                    sender_email=sender_email,
                    to=_header(headers, "To"),
                    subject=_header(headers, "Subject"),
                    date=_header(headers, "Date"),
                    snippet=m.get("snippet", ""),
                    body_text=_extract_body(payload),
                    label_ids=m.get("labelIds", []) or [],
                )
            )
        last = messages[-1] if messages else None
        subject = messages[0].subject if messages else "(sin asunto)"
        participants = sorted({m.sender_email for m in messages if m.sender_email})
        return GmailThread(
            thread_id=thread_id,
            subject=subject,
            last_from=last.sender if last else "",
            last_from_email=last.sender_email if last else "",
            participants=participants,
            messages=messages,
        )

    # ── escritura (SOLO borradores) ──
    def send_message(self, to: str, subject: str, body: str, from_name: Optional[str] = None) -> str:
        """Envía un email nuevo (outbound). Devuelve el message id.
        Usado por el agente outbound para cold-email automático (10/día, dedup)."""
        svc = self._build_service()
        mime = MIMEText(body, "plain", "utf-8")
        mime["To"] = to
        mime["Subject"] = subject
        if from_name:
            # El address lo fija Gmail (la cuenta del token); sólo personalizamos el display name.
            try:
                addr = svc.users().getProfile(userId=self.user_id).execute().get("emailAddress", "")
                if addr:
                    mime["From"] = f"{from_name} <{addr}>"
            except Exception:
                pass
        raw = base64.urlsafe_b64encode(mime.as_bytes()).decode("utf-8")
        sent = svc.users().messages().send(userId=self.user_id, body={"raw": raw}).execute()
        msg_id = sent.get("id", "")
        log.info("gmail_message_sent", to=to, msg_id=msg_id, subject=subject[:60])
        return msg_id

    def send_reply(
        self, thread_id: str, to: str, subject: str, body: str, from_name: Optional[str] = None
    ) -> str:
        """ENVÍA una respuesta DENTRO del hilo (no borrador). Devuelve el message id.
        Usado por el inbox_assistant cuando inbox_auto_send=True: responde solo,
        apuntando a agendar una reunión. Threadea por `threadId` + asunto 'Re:'."""
        svc = self._build_service()
        mime = MIMEText(body, "plain", "utf-8")
        mime["To"] = to
        mime["Subject"] = subject if subject.lower().startswith("re:") else f"Re: {subject}"
        if from_name:
            try:
                addr = svc.users().getProfile(userId=self.user_id).execute().get("emailAddress", "")
                if addr:
                    mime["From"] = f"{from_name} <{addr}>"
            except Exception:
                pass
        raw = base64.urlsafe_b64encode(mime.as_bytes()).decode("utf-8")
        sent = (
            svc.users()
            .messages()
            .send(userId=self.user_id, body={"raw": raw, "threadId": thread_id})
            .execute()
        )
        msg_id = sent.get("id", "")
        log.info("gmail_reply_sent", thread_id=thread_id, msg_id=msg_id, to=to)
        return msg_id

    def create_draft(
        self, thread_id: str, to: str, subject: str, body: str, in_reply_to_msg_id: Optional[str] = None
    ) -> str:
        """Crea un BORRADOR de respuesta dentro del hilo. Devuelve el draft id.
        NO envía. El humano revisa y manda desde Gmail."""
        svc = self._build_service()
        mime = MIMEText(body, "plain", "utf-8")
        mime["To"] = to
        mime["Subject"] = subject if subject.lower().startswith("re:") else f"Re: {subject}"
        raw = base64.urlsafe_b64encode(mime.as_bytes()).decode("utf-8")
        message_body = {"raw": raw, "threadId": thread_id}
        draft = (
            svc.users()
            .drafts()
            .create(userId=self.user_id, body={"message": message_body})
            .execute()
        )
        draft_id = draft.get("id", "")
        log.info("gmail_draft_created", thread_id=thread_id, draft_id=draft_id, to=to)
        return draft_id


def get_gmail_client(settings: Settings) -> GmailClient:
    return GmailClient(settings)
