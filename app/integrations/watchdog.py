"""
watchdog — chequeo de salud de lo que se rompe EN SILENCIO.

Problema que resuelve: los fallos que NO levantan excepción en una corrida no se
alertan. El caso testigo es el refresh token de Gmail: vence cada ~7 días (app
OAuth en modo Testing) y tumba outbound/inbox/drive sin ruido — nos enterábamos
días después, con mails sin salir y respuestas sin contestar.

Este watchdog corre por cron (varias veces al día, sin LLM → sin costo de cuota) y:
  1. Verifica el token de Gmail con un refresh REAL (detecta invalid_grant antes
     de que rompa el envío del día).
  2. Detecta corridas caídas: agentes que tenían que correr hace rato y no dejaron
     reporte (mismo criterio que el parte del chief_of_staff, pero proactivo).

Alerta a Discord SOLO si hay algo roto, y deduplica por día (no spamea el mismo
problema en cada pasada). Silencio = todo sano.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Tuple
from zoneinfo import ZoneInfo

from ..config import Settings
from ..log import get_logger

log = get_logger("watchdog")

_DATA = Path(__file__).resolve().parent.parent.parent / "data"
_STATE = _DATA / "watchdog-state.json"
_TZ = ZoneInfo("America/Buenos_Aires")


# ── estado (dedup por día) ──

def _load_state() -> Dict[str, Any]:
    try:
        return json.loads(_STATE.read_text(encoding="utf-8"))
    except Exception:
        return {"alerted": {}}


def _save_state(state: Dict[str, Any]) -> None:
    try:
        from .jsonstore import write_json_atomic
        write_json_atomic(_STATE, state, indent=1)
    except Exception as e:
        log.warning("watchdog_state_save_failed", error=str(e)[:120])


# ── chequeos ──

def _check_gmail(settings: Settings) -> Tuple[str, str]:
    """('ok'|'fail'|'skip', detalle). Hace un refresh REAL del token."""
    if not settings.gmail_configured:
        return ("skip", "Gmail sin credenciales")
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        from .gmail_client import GMAIL_SCOPES, TOKEN_URI
        creds = Credentials(
            token=None, refresh_token=settings.gmail_refresh_token,
            client_id=settings.gmail_client_id, client_secret=settings.gmail_client_secret,
            token_uri=TOKEN_URI, scopes=GMAIL_SCOPES,
        )
        creds.refresh(Request())
        return ("ok", "token válido")
    except Exception as e:
        return ("fail", str(e)[:200])


def _missed_runs(settings: Settings) -> List[Tuple[str, str]]:
    """Agentes que tenían corrida vencida hoy (+gracia) y no dejaron reporte."""
    from apscheduler.triggers.cron import CronTrigger
    from ..scheduler import DEFAULT_SCHEDULES
    ahora = datetime.now(_TZ)
    arranque = ahora.replace(hour=0, minute=0, second=0, microsecond=0)
    hoy = ahora.strftime("%Y-%m-%d")
    grace = timedelta(minutes=max(0, int(settings.watchdog_grace_min)))
    missed: List[Tuple[str, str]] = []
    for nombre, cron in DEFAULT_SCHEDULES.items():
        # El chief cierra a las 21:00 y él mismo reporta las caídas; no lo vigilamos acá.
        if nombre == "chief_of_staff":
            continue
        rep = _DATA / f"{nombre.replace('_', '-')}-report-{hoy}.md"
        if rep.is_file():
            continue
        try:
            trig = CronTrigger.from_crontab(cron, timezone=_TZ)
            prox = trig.get_next_fire_time(None, arranque)
        except Exception:
            continue
        if prox is not None and prox.date() == ahora.date() and prox + grace <= ahora:
            missed.append((nombre, prox.strftime("%H:%M")))
    return missed


# Firmas de una corrida DEGRADADA (el agente "entregó" pero el output está roto).
# Salieron de incidentes reales: leadhunter inventando leads al topar turnos (2026-07-21),
# placeholders de runs fallidos, y el corte de Hermes pidiendo resumen a la mitad.
_DEGRADED_MARKERS = (
    "no devolvió output",
    "reached maximum iterations",
    "requesting summary",
    "maximum iterations",
)


def _degraded_reports(settings: Settings) -> List[Tuple[str, str]]:
    """Reportes de HOY que existen pero traen una firma de degradación."""
    hoy = datetime.now(_TZ).strftime("%Y-%m-%d")
    out: List[Tuple[str, str]] = []
    try:
        for p in _DATA.glob(f"*-report-{hoy}.md"):
            try:
                txt = p.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            low = txt.lower()
            hit = next((m for m in _DEGRADED_MARKERS if m in low), "")
            if hit:
                agente = p.stem.split("-report-")[0].replace("-", "_")
                out.append((agente, hit))
    except Exception as e:
        log.warning("watchdog_degraded_scan_failed", error=str(e)[:120])
    return out


BRAIN_STALE_HORAS = 48


def _brain_stale() -> float:
    """Horas desde la última sync del Cerebro (0 si está al día).

    El sync corre en la máquina del dueño: si la apaga, el cerebro se congela y
    los agentes siguen corriendo con la foto vieja SIN QUE NADIE SE ENTERE — que
    es justo la clase de falla silenciosa que este watchdog existe para cazar."""
    try:
        raw = json.loads((_DATA / "brain-graph.json").read_text(encoding="utf-8"))
        recibido = datetime.fromisoformat(raw["received_at"])
        horas = (datetime.now(recibido.tzinfo) - recibido).total_seconds() / 3600
        return horas if horas > BRAIN_STALE_HORAS else 0.0
    except Exception:
        return 0.0   # sin cerebro todavía: no es una regresión que alertar


# ── entrada ──

def check(settings: Settings, discord=None) -> Dict[str, Any]:
    """Corre los chequeos y alerta a Discord lo que esté roto (dedup por día).
    Devuelve un dict con el resultado. Best-effort: nunca levanta."""
    hoy = datetime.now(_TZ).strftime("%Y-%m-%d")
    state = _load_state()
    # Estado nuevo por día (limpia lo viejo de una).
    already: List[str] = state.get("alerted", {}).get(hoy, [])
    problems: List[str] = []       # texto para Discord
    fresh_keys: List[str] = []     # claves de dedup a marcar

    # 1) Gmail
    g_status, g_detail = _check_gmail(settings)
    if g_status == "fail" and "gmail" not in already:
        problems.append(
            f"🔑 **Token de Gmail caído** — el refresh falló: `{g_detail}`\n"
            "→ Re-minteá con `scripts/gmail_oauth_setup.py` logueando como "
            "**Ventas@automiq.agency** y actualizá `GMAIL_REFRESH_TOKEN` en Railway. "
            "Mientras tanto: outbound, inbox y drive-sync NO funcionan."
        )
        fresh_keys.append("gmail")

    # 2) Corridas caídas
    missed = _missed_runs(settings)
    for nombre, hora in missed:
        key = f"missed:{nombre}"
        if key in already:
            continue
        problems.append(f"⚠️ **Corrida caída**: `{nombre}` tenía que correr {hora} "
                        "y no dejó reporte hoy.")
        fresh_keys.append(key)

    # 3) Reportes degradados (entregó pero el output está roto)
    degraded = _degraded_reports(settings)
    for nombre, marker in degraded:
        key = f"degraded:{nombre}"
        if key in already:
            continue
        problems.append(f"🩹 **Reporte degradado**: `{nombre}` entregó pero el output trae "
                        f"la firma `{marker}` — revisá que no haya inventado/truncado.")
        fresh_keys.append(key)

    # 4) Cerebro congelado (el sync corre en la compu del dueño)
    stale = _brain_stale()
    if stale and "brain" not in already:
        problems.append(
            f"🧠 **Cerebro desactualizado** — última sync hace {int(stale)} h. "
            "Los agentes están corriendo con documentación vieja.\n"
            "→ Prendé la máquina del vault o corré `scripts/brain_sync.bat` a mano."
        )
        fresh_keys.append("brain")

    # 5) Token de la Biblioteca de Anuncios (es de USUARIO: se cae solo cada ~60 días
    #    o con un logout). Cuando muere, el estudio de competencia sigue "corriendo"
    #    pero con 0 avisos reales — otra falla silenciosa (pasó el 2026-08-02).
    adlib_ok = True
    try:
        from . import meta_ad_library
        adlib_ok = meta_ad_library.token_vivo()
    except Exception as e:
        log.warning("watchdog_adlib_check_failed", error=str(e)[:120])
    if not adlib_ok and "adlib" not in already:
        problems.append(
            "📢 **Token de la Biblioteca de Anuncios caído** — Meta devuelve `code 190` "
            "(sesión inválida). El estudio de competencia está corriendo con **0 anuncios "
            "reales**, solo con búsquedas web.\n"
            "→ Re-generá el token de usuario en developers.facebook.com y actualizá "
            "`META_AD_LIBRARY_TOKEN` en Railway."
        )
        fresh_keys.append("adlib")

    result = {"gmail": g_status, "gmail_detail": g_detail,
              "adlib": adlib_ok, "brain_stale_h": round(stale, 1),
              "missed": [m[0] for m in missed],
              "degraded": [d[0] for d in degraded], "alerted": len(problems)}

    if problems and discord is not None:
        try:
            from ..clients.discord import DiscordEmbed
            body = "\n\n".join(problems)
            url = settings.discord_webhook_errors or settings.discord_webhook_url
            discord.send("", url=url, embed=DiscordEmbed(
                title="🚨 Watchdog — algo se rompió en silencio",
                description=body[:4096], color=0xE74C3C, footer="Automiq Watchdog"))
        except Exception as e:
            log.error("watchdog_alert_failed", error=str(e)[:150])

    # Solo dedup si de verdad avisamos (con discord=None no alertamos → no suprimir).
    if fresh_keys and discord is not None:
        state["alerted"] = {hoy: already + fresh_keys}  # solo hoy → poda lo viejo
        _save_state(state)

    log.info("watchdog_done", gmail=g_status, missed=len(missed), alerted=len(problems))
    return result
