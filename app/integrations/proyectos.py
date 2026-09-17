"""
proyectos — los sistemas que OPERAMOS, su salud y quién los usa.

No confundir con `clients_store`, que es lo comercial: ahí vive si CLAMEVET paga
y cuánto. Acá vive si la plataforma de CLAMEVET está viva, si su base responde y
cuántos socios entraron esta semana. Un cliente puede no tener proyecto (todavía)
y un proyecto puede no tener cliente (la landing, los agentes).

El registro va EN CÓDIGO y no en una tabla a propósito: son cuatro sistemas que
cambian cada varios meses. Una tabla con su CRUD sería más pantalla que dato.
Cuando sean quince, se mueve.

Cómo se mide la salud, y por qué así: **cada proyecto reporta lo suyo**. El panel
sólo pregunta y junta. La alternativa —que este módulo se conecte a la base de
cada sistema— significaría tener acá las credenciales de todas las bases, que es
exactamente el radio de explosión que estuvimos achicando.

Dos niveles:
  · `sonda`   — el endpoint público de salud. Barato, sin auth, dice si está vivo.
  · `resumen` — el endpoint autenticado de cada proyecto, que devuelve SUS
    números (socios, empresas, usuarios, errores). Si no lo tiene, se omite:
    un proyecto sin resumen igual aparece con su salud.

Nunca levanta: un proyecto caído no puede voltear el panel entero.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

import httpx

from ..config import get_settings
from ..log import get_logger

log = get_logger("proyectos")

TIMEOUT = 20.0

PROYECTOS: List[Dict[str, Any]] = [
    {
        "id": "clamevet",
        "nombre": "Plataforma CLAMEVET",
        "tipo": "plataforma",
        "cliente": "CLAMEVET",
        "que_es": ("Memoria regulatoria para ~50 laboratorios veterinarios: foro, "
                   "asistente que cita y no inventa, ingesta del Boletín y alertas."),
        "url": "https://ia.clamevet.com.ar",
        "sonda": "https://ia.clamevet.com.ar/health",
        "resumen": "https://ia.clamevet.com.ar/health/resumen",
        "repo": "clamevet-platform",
        "railway": "clamevet",
        "notas": "Único sistema que usa Vertex (y factura). Deploy con `railway up`.",
    },
    {
        "id": "crm",
        "nombre": "CRM Automiq",
        "tipo": "crm",
        "cliente": None,        # multi-tenant: los clientes viven adentro
        "que_es": ("CRM multi-empresa con WhatsApp, agente de IA por cliente y "
                   "pipeline. Cada cliente es un tenant."),
        "url": "https://crm.automiq.agency",
        "sonda": "https://crm.automiq.agency/health",
        "resumen": "https://crm.automiq.agency/health/resumen",
        "repo": "CRM-AUTOMIQ",
        "railway": "crm",
        "notas": "NO auto-deploya con el push: hay que hacer `railway up`.",
    },
    {
        "id": "agentes",
        "nombre": "Equipo de agentes",
        "tipo": "agentes",
        "cliente": None,
        "que_es": "Los agentes de la agencia, sus departamentos y este mismo panel.",
        "url": "https://app.automiq.agency",
        # Es ESTE servicio: se contesta local y NO se pega a sí mismo por HTTP.
        # Pegarse a sí mismo se cuelga: el pedido a `/healthz` espera al worker
        # que justo está atendiendo el pedido de `/api/proyectos`. Medido: 20 s de
        # ReadTimeout y el panel reportando "los agentes no responden" desde
        # adentro de los agentes.
        "propio": True,
        "sonda": None,
        "resumen": None,
        "repo": "agency-agents-render",
        "railway": "automiq-agents",
        "notas": "Se despliega solo al pushear a main.",
    },
    {
        "id": "landing",
        "nombre": "Web automiq.agency",
        "tipo": "web",
        "cliente": None,
        "que_es": "La landing y sus 18 páginas satélite de SEO/GEO.",
        "url": "https://automiq.agency",
        "sonda": "https://automiq.agency",
        "resumen": None,
        "repo": "(sin repo: la fuente de verdad es el deploy de Vercel)",
        "railway": None,
        "notas": ("⚠️ La copia local NO es producción. Bajar la fuente del último "
                  "deploy antes de tocar, o se borran páginas vivas."),
    },
]


def _uno(pid: str) -> Optional[Dict[str, Any]]:
    return next((p for p in PROYECTOS if p["id"] == pid), None)


def _sondear(p: Dict[str, Any]) -> Dict[str, Any]:
    """Pregunta si está vivo. Devuelve estado, latencia y lo que conteste."""
    if p.get("propio"):
        # Si este código está corriendo, este servicio está vivo. No hay nada
        # que preguntar, y preguntarlo por HTTP se cuelga (ver el registro).
        return {"estado": "ok", "ms": 0, "detalle": "es este mismo servicio"}
    url = p.get("sonda")
    if not url:
        return {"estado": "sin_sonda", "ms": None, "detalle": ""}
    t0 = time.perf_counter()
    try:
        with httpx.Client(timeout=TIMEOUT, follow_redirects=True) as c:
            r = c.get(url)
        ms = int((time.perf_counter() - t0) * 1000)
        if r.status_code >= 400:
            return {"estado": "caido", "ms": ms, "detalle": f"HTTP {r.status_code}"}
        cuerpo: Any = {}
        try:
            cuerpo = r.json()
        except Exception:
            cuerpo = {}
        # CLAMEVET devuelve {"ok":true,"db":true}: si la base está mal, el
        # servicio "responde" igual y eso NO es estar sano.
        if isinstance(cuerpo, dict) and cuerpo.get("db") is False:
            return {"estado": "degradado", "ms": ms, "detalle": "la base no responde"}
        return {"estado": "ok", "ms": ms,
                "detalle": ", ".join(f"{k}={v}" for k, v in list(cuerpo.items())[:4])}
    except Exception as e:                                  # noqa: BLE001
        return {"estado": "caido", "ms": int((time.perf_counter() - t0) * 1000),
                "detalle": f"{type(e).__name__}"}


def _resumen_remoto(p: Dict[str, Any]) -> Dict[str, Any]:
    """Los números propios del proyecto. {} si no expone resumen o si falla.

    Va con el mismo secreto que usamos entre nuestros servicios. Un proyecto que
    todavía no implementó el endpoint devuelve 404 y no pasa nada: aparece con su
    salud y sin números, que es mejor que no aparecer.
    """
    url = p.get("resumen")
    if not url:
        return {}
    sec = get_settings().panel_secret
    if not sec:
        return {}
    try:
        with httpx.Client(timeout=TIMEOUT) as c:
            r = c.get(url, headers={"X-Panel-Secret": sec})
        if r.status_code == 200:
            d = r.json()
            return d if isinstance(d, dict) else {}
        if r.status_code != 404:
            log.warning("proyecto_resumen_http", proyecto=p["id"], status=r.status_code)
    except Exception as e:                                  # noqa: BLE001
        log.warning("proyecto_resumen_falló", proyecto=p["id"], error=str(e)[:120])
    return {}


def _resumen_propio() -> Dict[str, Any]:
    """Los números de ESTE servicio. No sale a la red para preguntarse a sí mismo."""
    datos: Dict[str, Any] = {}
    try:
        from ..agents.registry import list_agents
        datos["agentes"] = len(list_agents())
    except Exception:
        pass
    try:
        from . import eventos
        ultimos = eventos.ultimos(200)
        datos["eventos_recientes"] = len(ultimos)
        datos["fallas_recientes"] = sum(1 for e in ultimos if not e.get("ok"))
        datos["esperando_ok"] = sum(1 for e in ultimos
                                    if e.get("estado") == "esperando_ok")
    except Exception:
        pass
    try:
        from . import video_bank
        datos["clips_en_banco"] = video_bank.resumen().get("por_estado", {}).get("listo", 0)
    except Exception:
        pass
    return datos


def salud(pid: Optional[str] = None) -> List[Dict[str, Any]]:
    """Estado de todos los proyectos (o de uno). Nunca levanta."""
    elegidos = [p for p in PROYECTOS if pid is None or p["id"] == pid]
    salida = []
    for p in elegidos:
        sonda = _sondear(p)
        resumen = _resumen_propio() if p.get("propio") else _resumen_remoto(p)
        salida.append({**{k: v for k, v in p.items()
                          if k not in ("sonda", "resumen", "propio")},
                       "salud": sonda, "numeros": resumen})
    log.info("proyectos_salud", n=len(salida),
             caidos=[s["id"] for s in salida if s["salud"]["estado"] == "caido"])
    return salida


def caidos() -> List[Dict[str, Any]]:
    """Los que no están sanos. Es lo que mira el watchdog."""
    return [p for p in salud() if p["salud"]["estado"] in ("caido", "degradado")]


# ──────────────────────────────────────────────────────────────────────
# Auditoría
#
# Deterministas y ANTES del modelo. Un chequeo escrito dice siempre lo mismo,
# se puede probar, y cuesta cero. Lo que el agente agrega arriba es criterio —
# qué atender primero, qué significa — no la detección. Al revés (que el modelo
# mire números crudos y decida si hay problema) es como se inventan hallazgos,
# que ya nos pasó con el "H1 vacío" que estuvo 22 días siendo falso.
# ──────────────────────────────────────────────────────────────────────

ALTA, MEDIA, BAJA = "alta", "media", "baja"


def _hallazgo(pid: str, sev: str, que: str, por_que: str) -> Dict[str, str]:
    return {"proyecto": pid, "severidad": sev, "que": que, "por_que": por_que}


def _auditar_clamevet(n: Dict[str, Any]) -> List[Dict[str, str]]:
    h = []
    if n.get("documentos_con_error"):
        h.append(_hallazgo("clamevet", ALTA,
                           f"{n['documentos_con_error']} documento(s) en estado error",
                           "No están indexados: el asistente contesta sin ese material "
                           "y no avisa que le falta."))
    if n.get("documentos") and not n.get("fragmentos"):
        h.append(_hallazgo("clamevet", ALTA, "Hay documentos pero cero fragmentos",
                           "Sin chunks no hay búsqueda: el RAG está vacío."))
    if n.get("socios") is not None and n.get("empresas") and n["socios"] < n["empresas"]:
        h.append(_hallazgo("clamevet", MEDIA,
                           f"{n['empresas'] - n['socios']} empresa(s) sin cuenta activa",
                           "Socios de la cámara que todavía no pueden entrar."))
    if n.get("consultas_7d") == 0:
        h.append(_hallazgo("clamevet", MEDIA, "Cero consultas en 7 días",
                           "La plataforma está viva pero nadie la usa. Es un problema "
                           "de adopción, y el pago depende de que la usen."))
    ultimo = n.get("ultimo_boletin") or ""
    if ultimo:
        try:
            from datetime import datetime, timezone
            d = datetime.fromisoformat(ultimo.replace("Z", "+00:00"))
            dias = (datetime.now(timezone.utc) - d).days
            if dias > 14:
                h.append(_hallazgo("clamevet", ALTA,
                                   f"El último boletín entró hace {dias} días",
                                   "La ingesta se frenó. El valor del producto es estar "
                                   "al día; sin boletín nuevo, no lo está."))
        except Exception:
            pass
    return h


def _auditar_crm(n: Dict[str, Any]) -> List[Dict[str, str]]:
    h = []
    if n.get("canales_activos") and n.get("mensajes_24h") == 0:
        h.append(_hallazgo("crm", ALTA, "Canales activos y cero mensajes en 24 h",
                           "O se cortó el webhook de Meta o venció un token. Los "
                           "mensajes que entran mientras tanto NO se recuperan."))
    for e in n.get("empresas_detalle") or []:
        if e.get("activa") and not e.get("canales"):
            h.append(_hallazgo("crm", MEDIA,
                               f"«{e.get('nombre')}» activa y sin canal conectado",
                               "Una cuenta que no recibe nada. O falta terminar el "
                               "alta, o quedó abierta de más."))
        if e.get("activa") and not e.get("usuarios"):
            h.append(_hallazgo("crm", MEDIA,
                               f"«{e.get('nombre')}» sin ningún usuario",
                               "Nadie puede entrar a ver sus conversaciones."))
    for t in n.get("tokens") or []:
        if t.get("status") in ("expired", "error", "unreachable"):
            h.append(_hallazgo("crm", ALTA,
                               f"Token {t.get('status')} en «{t.get('name')}» "
                               f"({t.get('channel_type')})",
                               (t.get("detail") or "")[:140] or
                               "Ese canal dejó de poder mandar y recibir."))
    return h


def _auditar_agentes(n: Dict[str, Any], credenciales_en_vivo: bool = True) -> List[Dict[str, str]]:
    h = []
    if n.get("fallas_recientes"):
        h.append(_hallazgo("agentes", MEDIA,
                           f"{n['fallas_recientes']} corrida(s) fallada(s) en la bitácora",
                           "Un agente que falla callado deja de hacer su trabajo sin "
                           "que se note."))
    if n.get("esperando_ok"):
        h.append(_hallazgo("agentes", MEDIA,
                           f"{n['esperando_ok']} acción(es) esperando aprobación",
                           "Están frenadas hasta que alguien decida. Si nadie mira, "
                           "no salen nunca."))
    # Sale a pedir un token de verdad contra cada proveedor: segundos, no
    # milisegundos, y con el consentimiento de Gmail en Testing conviene no
    # gatillarlo en cada corrida. El cierre diario lo apaga; la auditoría a
    # pedido lo quiere.
    if credenciales_en_vivo:
        try:
            from . import credenciales
            for c in credenciales.caidas():
                h.append(_hallazgo("agentes", ALTA,
                                   f"Credencial caída: {c['clave']}",
                                   c.get("rompe") or "Rompe lo que dependa de ella."))
        except Exception:
            pass
    return h


_AUDITORES = {"clamevet": _auditar_clamevet, "crm": _auditar_crm,
              "agentes": _auditar_agentes}


def _tokens_del_crm() -> List[Dict[str, Any]]:
    """Los tokens de Meta del CRM. Endpoint aparte del resumen porque sale a
    consultarle a Meta por cada canal y es lento."""
    sec = get_settings().panel_secret
    if not sec:
        return []
    try:
        with httpx.Client(timeout=45.0) as c:
            r = c.get("https://crm.automiq.agency/health/whatsapp-tokens",
                      headers={"X-Panel-Secret": sec})
        return r.json().get("tokens", []) if r.status_code == 200 else []
    except Exception as e:                                  # noqa: BLE001
        log.warning("tokens_crm_falló", error=str(e)[:120])
        return []


def auditar(pid: Optional[str] = None) -> Dict[str, Any]:
    """Auditoría de uno o de todos. Devuelve hallazgos ordenados por gravedad."""
    estados = salud(pid)
    hallazgos: List[Dict[str, str]] = []
    for e in estados:
        i = e["id"]
        if e["salud"]["estado"] == "caido":
            hallazgos.append(_hallazgo(i, ALTA, f"{e['nombre']} no responde",
                                       e["salud"]["detalle"] or "La sonda falló."))
            continue
        if e["salud"]["estado"] == "degradado":
            hallazgos.append(_hallazgo(i, ALTA, f"{e['nombre']} degradado",
                                       e["salud"]["detalle"]))
        numeros = dict(e["numeros"])
        if i == "crm" and numeros:
            numeros["tokens"] = _tokens_del_crm()
        auditor = _AUDITORES.get(i)
        if auditor and numeros:
            hallazgos.extend(auditor(numeros))

    orden = {ALTA: 0, MEDIA: 1, BAJA: 2}
    hallazgos.sort(key=lambda x: orden.get(x["severidad"], 9))
    log.info("proyectos_auditoria", n=len(hallazgos),
             altas=sum(1 for x in hallazgos if x["severidad"] == ALTA))
    return {"proyectos": estados, "hallazgos": hallazgos,
            "altas": sum(1 for x in hallazgos if x["severidad"] == ALTA)}
