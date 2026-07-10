"""
calendar_client — crea eventos de Google Calendar con link de Google Meet.

Usado por el Inbox Assistant: cuando un prospecto CONFIRMA un horario, el agente
crea el evento (con Meet) en el calendario de la cuenta de Automiq, invita al
prospecto (le llega el .ics + el link) y devuelve el link del Meet para ponerlo
en la respuesta. La reunión queda registrada en el panel (meetings_store).

Reutiliza las MISMAS credenciales OAuth que Gmail (mismo client_id/secret/refresh
token). El scope calendar.events viene en GMAIL_SCOPES; si el refresh token todavía
NO tiene ese scope otorgado (no se re-autorizó), la creación falla con gracia
(CalendarError) y el inbox cae a proponer horarios en texto, sin romperse.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from ..config import Settings
from ..log import get_logger
from .gmail_client import GMAIL_SCOPES, TOKEN_URI

log = get_logger("calendar")


class CalendarError(RuntimeError):
    pass


class CalendarClient:
    def __init__(self, settings: Settings):
        self.s = settings
        self._service = None

    def configured(self) -> bool:
        return bool(self.s.gmail_client_id and self.s.gmail_client_secret and self.s.gmail_refresh_token)

    def _build_service(self):
        if self._service is not None:
            return self._service
        try:
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build
        except ImportError as e:
            raise CalendarError(f"falta dependencia google-api-python-client: {e}")
        if not self.configured():
            raise CalendarError(
                "Calendar no configurado: faltan GMAIL_CLIENT_ID / GMAIL_CLIENT_SECRET / "
                "GMAIL_REFRESH_TOKEN."
            )
        creds = Credentials(
            token=None,
            refresh_token=self.s.gmail_refresh_token,
            client_id=self.s.gmail_client_id,
            client_secret=self.s.gmail_client_secret,
            token_uri=TOKEN_URI,
            scopes=GMAIL_SCOPES,
        )
        # Timeout explícito (mismo motivo que gmail_client): default None colgaba
        # el thread del job para siempre.
        try:
            import httplib2
            from google_auth_httplib2 import AuthorizedHttp
            http = AuthorizedHttp(creds, http=httplib2.Http(timeout=60))
            self._service = build("calendar", "v3", http=http, cache_discovery=False)
        except ImportError:
            self._service = build("calendar", "v3", credentials=creds, cache_discovery=False)
        return self._service

    def list_events(self, time_min: str, time_max: str, max_results: int = 250) -> list:
        """Lista eventos del calendario primario entre time_min y time_max (RFC3339).
        Devuelve dicts simplificados para el panel."""
        svc = self._build_service()
        res = (
            svc.events()
            .list(calendarId="primary", timeMin=time_min, timeMax=time_max,
                  singleEvents=True, orderBy="startTime", maxResults=max_results)
            .execute()
        )
        out = []
        for ev in res.get("items", []):
            start = ev.get("start", {}) or {}
            end = ev.get("end", {}) or {}
            out.append({
                "id": ev.get("id", ""),
                "title": ev.get("summary", "(sin título)"),
                "start": start.get("dateTime") or start.get("date"),
                "end": end.get("dateTime") or end.get("date"),
                "all_day": "date" in start and "dateTime" not in start,
                "meet_link": _extract_meet_link(ev),
                "html_link": ev.get("htmlLink", ""),
                "attendees": [a.get("email") for a in ev.get("attendees", []) if a.get("email")],
                "description": ev.get("description", ""),
                "location": ev.get("location", ""),
            })
        return out

    def delete_event(self, event_id: str) -> None:
        svc = self._build_service()
        svc.events().delete(calendarId="primary", eventId=event_id, sendUpdates="all").execute()

    def create_meet_event(
        self,
        summary: str,
        start_iso: str,
        duration_min: int = 20,
        attendee_email: Optional[str] = None,
        description: str = "",
        timezone: str = "America/Argentina/Buenos_Aires",
    ) -> Dict[str, Any]:
        """Crea un evento con Google Meet. Devuelve {event_id, meet_link, html_link, start, end}.

        `start_iso` debe ser ISO-8601 con offset (ej. '2026-06-27T11:00:00-03:00').
        Si no trae offset, se asume la timezone pasada.
        """
        svc = self._build_service()
        start_dt = _parse_dt(start_iso)
        end_dt = start_dt + timedelta(minutes=max(10, int(duration_min or 20)))

        body: Dict[str, Any] = {
            "summary": summary or "Reunión Automiq",
            "description": description or "",
            "start": {"dateTime": start_dt.isoformat(), "timeZone": timezone},
            "end": {"dateTime": end_dt.isoformat(), "timeZone": timezone},
            "conferenceData": {
                "createRequest": {
                    "requestId": uuid.uuid4().hex,
                    "conferenceSolutionKey": {"type": "hangoutsMeet"},
                }
            },
            "reminders": {"useDefault": True},
        }
        if attendee_email:
            body["attendees"] = [{"email": attendee_email}]

        ev = (
            svc.events()
            .insert(
                calendarId="primary",
                body=body,
                conferenceDataVersion=1,
                sendUpdates="all",   # le manda la invitación al prospecto
            )
            .execute()
        )
        meet_link = _extract_meet_link(ev)
        result = {
            "event_id": ev.get("id", ""),
            "meet_link": meet_link,
            "html_link": ev.get("htmlLink", ""),
            "start": start_dt.isoformat(),
            "end": end_dt.isoformat(),
        }
        log.info("calendar_event_created", event_id=result["event_id"],
                 meet=bool(meet_link), attendee=attendee_email or "")
        if not meet_link:
            # El evento se creó pero sin Meet (cuenta sin Meet habilitado, p.ej.).
            log.warning("calendar_no_meet_link", event_id=result["event_id"])
        return result


def _parse_dt(value: str) -> datetime:
    v = (value or "").strip()
    if not v:
        raise CalendarError("start_iso vacío")
    # Acepta 'Z' y offsets; si no hay tz, queda naive (Calendar usa timeZone del body).
    try:
        return datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError as e:
        raise CalendarError(f"start_iso inválido '{value}': {e}")


def _extract_meet_link(ev: Dict[str, Any]) -> str:
    # 1) entryPoints de conferenceData
    cd = ev.get("conferenceData", {}) or {}
    for ep in cd.get("entryPoints", []) or []:
        if ep.get("entryPointType") == "video" and ep.get("uri"):
            return ep["uri"]
    # 2) fallback: hangoutLink
    return ev.get("hangoutLink", "") or ""


def get_calendar_client(settings: Settings) -> CalendarClient:
    return CalendarClient(settings)
