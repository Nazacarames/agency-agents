"""
credenciales — el llavero: qué credencial existe, quién la usa y qué se rompe al rotarla.

Dos problemas concretos que resuelve.

1. **Una sola llave abre todo.** `GOOGLE_SERVICE_ACCOUNT_JSON` se pide con scope
   `cloud-platform` y la usan imágenes, video, Drive, Search Console y YouTube.
   Quien la tenga puede hacer cualquier cosa en el proyecto de Google Cloud. Darle
   a cada agente su propia identidad —lo que haría cualquiera— está bloqueado por
   la política `iam.disableServiceAccountKeyCreation` de la organización: no se
   pueden crear claves nuevas. Lo que sí se puede, y es lo que falta, es saber el
   radio de explosión ANTES de rotar, en vez de descubrirlo cuando algo deja de
   andar.

2. **Se mueren en silencio.** El watchdog hace un refresh REAL del token de Gmail
   —que vence cada 7 días porque el consentimiento está en Testing— y avisa. El
   resto del llavero no tenía ninguna verificación: un token de Meta vencido o una
   service account revocada degradaban sin un solo aviso, igual que los dos
   proveedores de LLM que estuvieron un mes muertos sin que nadie se enterara.

Regla dura: acá NUNCA sale el valor de una credencial. Sale si está, si anda, y
qué se cae si no está. El `client_email` de la service account sí sale: no es un
secreto, es la identidad que hay que buscar en la consola para rotarla.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple

from ..config import get_settings
from ..log import get_logger

log = get_logger("credenciales")


# ── verificadores: cada uno devuelve ('ok'|'fail'|'sin_verificador', detalle) ──

def _vertex(s) -> Tuple[str, str]:
    """Pide un token de verdad con la service account. Es la única forma de saber
    si la clave sigue viva: una revocada se ve idéntica a una buena en el env."""
    try:
        from google.oauth2 import service_account
        from google.auth.transport.requests import Request
        info = json.loads(s.google_service_account_json)
        creds = service_account.Credentials.from_service_account_info(
            info, scopes=["https://www.googleapis.com/auth/cloud-platform"])
        creds.refresh(Request())
        return ("ok", f"token vivo para {info.get('client_email', '?')}")
    except Exception as e:
        return ("fail", f"{type(e).__name__}: {e}"[:200])


def _meta(s) -> Tuple[str, str]:
    try:
        import httpx
        r = httpx.get(f"https://graph.facebook.com/{s.meta_graph_version}/me",
                      params={"access_token": s.meta_page_token}, timeout=15)
        d = r.json() if r.content else {}
        if r.status_code >= 400 or d.get("error"):
            return ("fail", str(d.get("error", {}).get("message", r.status_code))[:200])
        return ("ok", f"token vivo ({d.get('name', d.get('id', '?'))})")
    except Exception as e:
        return ("fail", f"{type(e).__name__}: {e}"[:200])


def _gmail(s) -> Tuple[str, str]:
    # Reusa la verificación que ya hacía el watchdog: es un refresh real.
    from .watchdog import _check_gmail
    estado, detalle = _check_gmail(s)
    return ("sin_verificador" if estado == "skip" else estado, detalle)


# ── el llavero ───────────────────────────────────────────────────────────────
# `usan` y `rompe` no son documentación de adorno: son la diferencia entre rotar
# una clave en diez minutos y pasar una tarde averiguando qué se cayó.

INVENTARIO: List[Dict[str, Any]] = [
    {
        "clave": "vertex_sa",
        "env": "GOOGLE_SERVICE_ACCOUNT_JSON",
        "presente": lambda s: bool(s.google_service_account_json),
        "alcance": "cloud-platform — acceso total al proyecto de Google Cloud",
        # 2026-09-16: se le sacaron Imagen, Veo y Gemini (era lo único que
        # facturaba). Lo que le queda son APIs GRATIS, con cuota y sin cargo.
        "usan": ["drive_client", "search_console",
                 "youtube_client (si no hay YOUTUBE_OAUTH_JSON)"],
        "rompe": "se corta el sync de Drive y los datos de Search Console",
        "nota": ("ya NO genera imágenes ni video: eso pasó a Higgsfield, y la visión "
                 "y el texto a NVIDIA. Los servicios que le quedan no facturan"),
        "verificar": _vertex,
    },
    {
        "clave": "gmail_oauth",
        "env": "GMAIL_CLIENT_ID / GMAIL_CLIENT_SECRET / GMAIL_REFRESH_TOKEN",
        "presente": lambda s: bool(s.gmail_configured),
        "alcance": "readonly + compose + calendar.events sobre la casilla de ventas",
        "usan": ["outbound", "inbox_assistant", "meeting_prep"],
        "rompe": "no sale ni entra un mail: se frena la secuencia entera de cold-email",
        "nota": ("el consentimiento está en Testing → el refresh token muere cada ~7 días "
                 "EN SILENCIO. Se re-mintea con scripts/gmail_oauth_setup.py"),
        "verificar": _gmail,
    },
    {
        "clave": "meta_page",
        "env": "META_PAGE_TOKEN",
        "presente": lambda s: bool(s.meta_page_token),
        "alcance": "publicar en la página de Facebook y en la cuenta de Instagram",
        "usan": ["social_publish", "comment_gate", "ig_discovery"],
        "rompe": "no se publica nada en IG ni en FB",
        "verificar": _meta,
    },
    {
        "clave": "google_ads",
        "env": "GOOGLE_ADS_REFRESH_TOKEN (+ developer token, client id/secret)",
        "presente": lambda s: bool(s.google_ads_refresh_token
                                   and s.google_ads_developer_token),
        "alcance": "leer la cuenta de Ads",
        "usan": ["media_auditor"],
        "rompe": "el media_auditor deja de ver el gasto y el rendimiento de las campañas",
        "verificar": None,
    },
    {
        "clave": "meta_ads",
        "env": "META_ADS_TOKEN",
        "presente": lambda s: bool(s.meta_ads_token),
        "alcance": "leer la cuenta publicitaria de Meta",
        "usan": ["media_auditor"],
        "rompe": "se pierde la mitad del reporte de medios",
        "verificar": None,
    },
    {
        "clave": "tiktok",
        "env": "TIKTOK_CLIENT_KEY / TIKTOK_CLIENT_SECRET",
        "presente": lambda s: bool(s.tiktok_client_key and s.tiktok_client_secret),
        "alcance": "subir videos a la cuenta de TikTok",
        "usan": ["tiktok_creator"],
        "rompe": "los shorts se generan pero no se suben",
        "verificar": None,
    },
    {
        "clave": "linkedin",
        "env": "LINKEDIN_CLIENT_ID / LINKEDIN_CLIENT_SECRET",
        "presente": lambda s: bool(s.linkedin_client_id and s.linkedin_client_secret),
        "alcance": "publicar y enriquecer leads en LinkedIn",
        "usan": ["leadhunter", "social_media"],
        "rompe": "no hay enriquecimiento ni publicación en LinkedIn",
        "verificar": None,
    },
    {
        "clave": "higgsfield",
        "env": "HIGGSFIELD_KEY_ID / HIGGSFIELD_KEY_SECRET",
        "presente": lambda s: bool(getattr(s, "higgsfield_key_id", "")
                                   and getattr(s, "higgsfield_key_secret", "")),
        "alcance": "generar imagen y video; consume el pool de creditos prepago",
        "usan": ["image_gen", "tiktok_creator"],
        "rompe": ("no se genera ni un video; las imagenes caen a MiniMax, que anda "
                  "pero da menos calidad"),
        "nota": ("no hay endpoint de saldo: el credito se mira en cloud.higgsfield.ai. "
                 "El plan ilimitado es solo web/manual, la API cobra"),
        "verificar": None,
    },
    {
        "clave": "database",
        "env": "DATABASE_URL",
        "presente": lambda s: bool(s.database_url),
        "alcance": "schema `agency` en Supabase (memoria, lecciones, bitácora, clientes)",
        "usan": ["todos los agentes", "el panel", "la bitácora de eventos"],
        "rompe": ("todo cae al fallback JSON del contenedor, que se borra en cada "
                  "deploy: se pierde la memoria y la bitácora"),
        "verificar": None,
    },
]


def estado(verificar: bool = False,
           omitir: Optional[set] = None) -> List[Dict[str, Any]]:
    """El llavero con su estado. Sin valores, nunca.

    `verificar=False` (default) sólo dice si la credencial está configurada, que
    es instantáneo. `verificar=True` sale a pedir un token de verdad contra cada
    proveedor que tenga verificador — es lo único que distingue una clave viva de
    una revocada, y por eso es opt-in: tarda segundos, no milisegundos.

    `omitir` saltea la verificación de esas claves. Lo usa el watchdog, que ya
    hace su propio refresh de Gmail: sin esto pediría dos refresh del mismo token
    en cada corrida, contra un consentimiento en Testing que ya es frágil.
    """
    s = get_settings()
    omitir = omitir or set()
    salida = []
    for item in INVENTARIO:
        try:
            presente = bool(item["presente"](s))
        except Exception:
            presente = False
        fila = {k: v for k, v in item.items() if k not in ("presente", "verificar")}
        fila["presente"] = presente
        fila["estado"] = "ausente" if not presente else "sin_verificar"
        fila["detalle"] = ""
        if presente and verificar and item.get("verificar") \
                and item["clave"] not in omitir:
            try:
                fila["estado"], fila["detalle"] = item["verificar"](s)
            except Exception as e:                              # pragma: no cover
                fila["estado"], fila["detalle"] = "fail", f"{type(e).__name__}: {e}"[:200]
        elif presente and not item.get("verificar"):
            fila["estado"] = "sin_verificador"
        salida.append(fila)
    return salida


def caidas(estados: Optional[List[Dict[str, Any]]] = None,
           omitir: Optional[set] = None) -> List[Dict[str, Any]]:
    """Las que están configuradas y NO andan. Lo que el watchdog tiene que gritar."""
    filas = estados if estados is not None else estado(verificar=True, omitir=omitir)
    return [f for f in filas if f["estado"] == "fail"]


def radio_de_explosion(clave: str) -> Dict[str, Any]:
    """Qué toca esta credencial. Para contestar «¿qué se rompe si la roto?» sin
    tener que leer el repo entero."""
    for item in INVENTARIO:
        if item["clave"] == clave:
            return {k: v for k, v in item.items() if k not in ("presente", "verificar")}
    raise KeyError(clave)
