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


# Un reporte MUCHO más chico que los del propio agente está roto aunque no traiga
# ninguna firma. Caso testigo (2026-08-10): leadhunter entregó 723 bytes — "el
# reporte completo de 10 leads está impreso en la respuesta" — cuando sus otros
# días son de 28 a 42 KB. Los 10 leads se perdieron, outbound ingestó 0 y nadie se
# enteró hasta que el Chief lo leyó a la noche. No hay marcador que lo delate: el
# run terminó bien, lo que falló fue el mensaje final del modelo.
_ENANO_RATIO = 0.25
_ENANO_MAX_BYTES = 4000


def _reporte_enano(p: Path, agente: str, hoy: str) -> str:
    """'' si el tamaño es normal; si no, la descripción de lo chico que quedó.

    Se compara contra el propio agente y no contra un piso fijo: hay agentes que
    entregan tres líneas siempre, y para ésos 700 bytes es su día normal."""
    try:
        size = p.stat().st_size
        if size > _ENANO_MAX_BYTES:
            return ""
        previos = sorted(x.stat().st_size for x in
                         _DATA.glob(f"{agente.replace('_', '-')}-report-*.md")
                         if hoy not in x.name)[-7:]
        if len(previos) < 3:
            return ""       # sin historia suficiente no hay con qué comparar
        tipico = previos[len(previos) // 2]      # mediana
        if size < tipico * _ENANO_RATIO:
            return f"{size} bytes contra {tipico} típicos"
    except Exception:
        pass
    return ""


def _degraded_reports(settings: Settings) -> List[Tuple[str, str]]:
    """Reportes de HOY que existen pero llegaron rotos: por firma o por tamaño."""
    hoy = datetime.now(_TZ).strftime("%Y-%m-%d")
    out: List[Tuple[str, str]] = []
    try:
        for p in _DATA.glob(f"*-report-{hoy}.md"):
            try:
                txt = p.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            low = txt.lower()
            agente = p.stem.split("-report-")[0].replace("-", "_")
            hit = next((m for m in _DEGRADED_MARKERS if m in low), "")
            if not hit:
                enano = _reporte_enano(p, agente, hoy)
                hit = f"quedó en {enano} — el entregable no llegó al reporte" if enano else ""
            if hit:
                out.append((agente, hit))
    except Exception as e:
        log.warning("watchdog_degraded_scan_failed", error=str(e)[:120])
    return out


BRAIN_STALE_HORAS = 48

# Escalones de nagging para los pendientes del dueño: se avisa al aparecer y al
# cruzar cada uno. Sin escalones habría que elegir entre avisar una sola vez (y
# que se olvide) o todos los días (y que se ignore).
_HITOS_DIAS = (3, 7, 14, 21, 30)


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

    # 6) DMARC: quién manda mail diciendo ser automiq.agency y NO alinea. Con
    #    `p=none` esos mensajes hoy se entregan igual; el día que endurezcamos la
    #    política se caen. Los informes llegan una vez por día, así que chequeamos
    #    una sola vez por día (la marca `dmarc:visto`) y no en cada pasada.
    dmarc: Dict[str, Any] = {}
    if "dmarc:visto" not in already:
        try:
            from . import dmarc_reports
            dmarc = dmarc_reports.resumen(settings)
        except Exception as e:
            log.warning("watchdog_dmarc_check_failed", error=str(e)[:120])
        if dmarc.get("ok"):
            fresh_keys.append("dmarc:visto")
            for f in dmarc.get("fallas", []):
                if f.get("reenvio_de_lead"):
                    continue    # nuestro propio mail repartido por el servidor del prospecto
                key = f"dmarc:{f['ip']}:{f['dkim']}"
                if key in already:
                    continue
                problems.append(
                    f"📨 **Mail no autorizado como automiq.agency** — {f['mensajes']} "
                    f"mensajes desde `{f['ip']}` firmados por `{f['dkim']}` "
                    f"(SPF: `{f['spf']}`) no alinean ni por DKIM ni por SPF.\n"
                    "→ Si es un remitente nuestro, hay que hacerlo firmar como "
                    "automiq.agency; si no lo conocemos, alguien está usando el dominio."
                )
                fresh_keys.append(key)

    # 7) Lo que sólo puede destrabar el dueño → canal #agencia.
    #    No es "algo se rompió", así que no va al embed de errores: es la lista de
    #    lo que está esperando por él. Avisa cuando el pendiente aparece y después
    #    sólo al cruzar 3/7/14/21/30 días. Repetirlo todos los días es lo que hace
    #    que un aviso deje de leerse — y es exactamente cómo el trío de la web
    #    sobrevivió 22 días apareciendo en todos los briefs.
    mios: List[str] = []
    mios_keys: List[str] = []
    try:
        from . import backlog
        for it in backlog.abiertos("humano"):
            # Si el dueño ya contestó sobre este ítem, dejamos de recordárselo: nos
            # dijo que se ocupa él. Insistirle sobre algo que ya nos contestó es
            # exactamente lo que hace que el canal se vuelva ruido y se deje de leer.
            if it.get("notas"):
                continue
            hito = max((h for h in _HITOS_DIAS if it["dias"] >= h), default=0)
            key = f"humano:{it['id']}:{hito}"
            if key in already:
                continue
            edad = ("recién anotado" if it["dias"] < 1
                    else f"abierto hace **{it['dias']} día(s)**")
            mios.append(f"• {it['titulo']}\n  ↳ {edad} · `{it['id']}`")
            mios_keys.append(key)
    except Exception as e:
        log.warning("watchdog_backlog_humano_failed", error=str(e)[:120])

    # Las claves se marcan SÓLO si el aviso salió de verdad: darlas por avisadas
    # sin webhook (o con el POST fallado) silencia el pendiente hasta el próximo
    # escalón, que puede ser una semana después.
    if mios and discord is not None and settings.discord_agencia_webhook_url:
        try:
            from ..clients.discord import DiscordEmbed
            discord.send("", url=settings.discord_agencia_webhook_url, embed=DiscordEmbed(
                title="🙋 Esto lo tenés que destrabar vos",
                description=("Ningún agente puede hacerlo: son decisiones, aprobaciones, "
                             "pagos o credenciales.\n\n" + "\n".join(mios))[:4096],
                color=0xF1C40F, footer="Automiq · backlog humano"))
            fresh_keys.extend(mios_keys)
        except Exception as e:
            log.error("watchdog_agencia_alert_failed", error=str(e)[:150])

    result = {"gmail": g_status, "gmail_detail": g_detail,
              "adlib": adlib_ok, "brain_stale_h": round(stale, 1),
              "missed": [m[0] for m in missed],
              "degraded": [d[0] for d in degraded],
              "dmarc_fallan": dmarc.get("fallan", 0) if dmarc else None,
              "backlog_humano_avisados": len(mios),
              "alerted": len(problems)}

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
