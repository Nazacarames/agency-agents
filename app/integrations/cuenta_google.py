"""
cuenta_google — el estado de la CUENTA de Google Cloud, para que el panel lo sepa
antes que el cliente.

Ojo con el nombre: `facturacion.py` de al lado es otra cosa —emite Facturas C por
ARCA— y esto es la cuenta de Google. Son dos facturaciones distintas.

Existe por el 2026-09-24: Google cortó Vertex por una factura impaga
(`403 "Lightning dunning decision is deny"`), el asistente de CLAMEVET quedó mudo
toda la mañana, y nos enteramos porque lo dijo el cliente. Al levantar la alfombra,
la cuenta **no tenía un solo presupuesto configurado**: no había nada que pudiera
avisar. Ya había pasado una vez, el 2026-07-08.

Dos señales, y cada una agarra un corte distinto:
  · `abierta`      — el flag `open` de la cuenta. En julio estaba en `false` y los
    proyectos igual figuraban con `billingEnabled: true`, así que ESTE es el que
    hay que mirar, no el otro.
  · `presupuestos` — cero presupuestos = ninguna alerta de gasto configurada.

⚠️ Ninguna de las dos habría agarrado el corte de septiembre: el dunning es
cobranza, y la cuenta figura abierta igual. Para eso está la sonda que hace una
llamada REAL a Vertex (`asistente_ok` en el resumen de CLAMEVET). Las tres juntas
cubren: cuenta cerrada, gasto desbocado, y servicio denegado.

Leer esto NO gasta —la Budgets API es gratis y la credencial es de sólo lectura
(`roles/billing.viewer` sobre la cuenta)—, así que a propósito no pasa por
`gasto_permitido()`, que es el freno de la generación en Vertex.

Nunca levanta: un problema leyendo la cuenta no puede voltear el panel.
"""
from __future__ import annotations

import json
import threading
import time
from typing import Any, Dict, List, Optional

import requests

from ..config import get_settings
from ..log import get_logger

log = get_logger("cuenta_google")

TIMEOUT = 30.0
CACHE_SEG = 3600          # cambia de mes a mes, no de minuto a minuto
_SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]

_lock = threading.Lock()
_cache: Dict[str, Any] = {"cuando": 0.0, "datos": None}

# Dónde cae el export de facturación a BigQuery. El export se prende a mano en la
# consola (no hay API ni comando de gcloud para eso) y Google crea la tabla sola,
# con el id de la cuenta y los guiones cambiados por guiones bajos. Hasta que
# aterrice la primera tanda —tarda horas— la tabla NO existe, y eso no es un error.
BQ_PROYECTO = "project-aa6a207a-826d-45a2-a63"
BQ_DATASET = "facturacion_google"
_gasto_lock = threading.Lock()
_gasto_cache: Dict[str, Any] = {"cuando": 0.0, "datos": None}


def _sa_info() -> Dict[str, Any]:
    crudo = get_settings().google_service_account_json
    if not crudo:
        raise RuntimeError("sin GOOGLE_SERVICE_ACCOUNT_JSON")
    return json.loads(crudo)


def _headers(info: Dict[str, Any]) -> Dict[str, str]:
    import google.auth.transport.requests as gar
    if info.get("type") == "authorized_user":
        from google.oauth2.credentials import Credentials as UserCreds
        creds = UserCreds.from_authorized_user_info(info, scopes=_SCOPES)
    else:
        from google.oauth2 import service_account
        creds = service_account.Credentials.from_service_account_info(info, scopes=_SCOPES)
    creds.refresh(gar.Request())
    # `x-goog-user-project` es obligatorio: la Budgets API factura la cuota contra
    # un proyecto, y sin este encabezado responde 403 hablando de "quota project",
    # que se lee igual que un problema de permisos y manda a buscar donde no es.
    return {"Authorization": "Bearer %s" % creds.token,
            "x-goog-user-project": info.get("project_id") or info.get("quota_project_id", "")}


def _presupuesto(b: Dict[str, Any]) -> Dict[str, Any]:
    monto = (b.get("amount", {}) or {}).get("specifiedAmount", {}) or {}
    return {
        "nombre": b.get("displayName", ""),
        "moneda": monto.get("currencyCode", ""),
        "monto": int(monto.get("units") or 0),
        "proyectos": (b.get("budgetFilter", {}) or {}).get("projects") or [],
        "umbrales": [t.get("thresholdPercent") for t in b.get("thresholdRules", [])],
    }


def _consultar() -> Dict[str, Any]:
    info = _sa_info()
    h = _headers(info)

    r = requests.get("https://cloudbilling.googleapis.com/v1/billingAccounts",
                     headers=h, timeout=TIMEOUT)
    r.raise_for_status()
    cuentas = r.json().get("billingAccounts") or []
    if not cuentas:
        return {"leible": True, "cuenta": "", "cuenta_id": "", "abierta": None,
                "presupuestos": [],
                "detalle": "la credencial no ve ninguna cuenta de facturación"}
    c = cuentas[0]

    r2 = requests.get("https://billingbudgets.googleapis.com/v1/%s/budgets" % c["name"],
                      headers=h, timeout=TIMEOUT)
    r2.raise_for_status()
    presupuestos = [_presupuesto(b) for b in (r2.json().get("budgets") or [])]

    return {"leible": True,
            "cuenta": c.get("displayName") or c["name"],
            # `billingAccounts/0174EE-6A84D5-404B1C` → `0174EE-6A84D5-404B1C`, que
            # es lo que Google usa para nombrar la tabla del export.
            "cuenta_id": c["name"].rsplit("/", 1)[-1],
            "abierta": c.get("open"),
            "presupuestos": presupuestos,
            "detalle": ""}


def estado(cada: int = CACHE_SEG) -> Dict[str, Any]:
    """Cómo está la cuenta de Google. Cacheado; nunca levanta."""
    ahora = time.monotonic()
    with _lock:
        if _cache["datos"] is not None and ahora - _cache["cuando"] < cada:
            return dict(_cache["datos"], cacheado=True)
    try:
        datos = _consultar()
    except Exception as e:                                  # noqa: BLE001
        log.warning("cuenta_google_no_legible", error=type(e).__name__, detalle=str(e)[:160])
        datos = {"leible": False, "cuenta": "", "cuenta_id": "", "abierta": None,
                 "presupuestos": [],
                 "detalle": "%s: %s" % (type(e).__name__, str(e)[:160])}
    with _lock:
        _cache.update(cuando=ahora, datos=datos)
    return dict(datos, cacheado=False)


def _tabla() -> str:
    cuenta = (estado().get("cuenta_id") or "").replace("-", "_")
    return "%s.%s.gcp_billing_export_v1_%s" % (BQ_PROYECTO, BQ_DATASET, cuenta)


_CONSULTA_GASTO = """
SELECT
  project.id AS proyecto,
  ROUND(SUM(cost) + SUM(IFNULL((SELECT SUM(c.amount) FROM UNNEST(credits) c), 0)), 2) AS costo,
  ANY_VALUE(currency) AS moneda
FROM `%s`
WHERE invoice.month = FORMAT_DATE('%%Y%%m', CURRENT_DATE())
GROUP BY proyecto
ORDER BY costo DESC
"""


def gasto_mes(cada: int = CACHE_SEG) -> Dict[str, Any]:
    """Lo gastado en el mes en curso, por proyecto. Nunca levanta.

    Sale del export a BigQuery, que es la ÚNICA forma de tener el número: no hay
    API de costos. Si el export todavía no se prendió (o no aterrizó la primera
    tanda) la tabla no existe, y eso se informa como «sin datos», no como falla —
    son dos cosas distintas y confundirlas es cómo se inventa un problema.

    El costo va NETO de créditos: sin restarlos, un mes con crédito aplicado se
    lee como si hubiéramos gastado de más.
    """
    ahora = time.monotonic()
    with _gasto_lock:
        if _gasto_cache["datos"] is not None and ahora - _gasto_cache["cuando"] < cada:
            return dict(_gasto_cache["datos"], cacheado=True)

    vacio = {"hay_datos": False, "total": None, "moneda": "", "por_proyecto": [],
             "detalle": ""}
    try:
        info = _sa_info()
        h = _headers(info)
        r = requests.post(
            "https://bigquery.googleapis.com/bigquery/v2/projects/%s/queries" % BQ_PROYECTO,
            headers=h, timeout=TIMEOUT,
            json={"query": _CONSULTA_GASTO % _tabla(), "useLegacySql": False,
                  "timeoutMs": 20000})
        if r.status_code == 404 or (r.status_code == 400 and "Not found" in r.text):
            datos = dict(vacio, detalle="el export a BigQuery todavía no dejó datos")
        elif r.status_code != 200:
            datos = dict(vacio, detalle="BigQuery respondió %s: %s"
                                        % (r.status_code, r.text[:160]))
        else:
            filas = r.json().get("rows") or []
            por = [{"proyecto": f["f"][0]["v"] or "(sin proyecto)",
                    "costo": float(f["f"][1]["v"] or 0),
                    "moneda": f["f"][2]["v"] or ""} for f in filas]
            datos = {"hay_datos": True,
                     "total": round(sum(p["costo"] for p in por), 2),
                     "moneda": por[0]["moneda"] if por else "",
                     "por_proyecto": por, "detalle": ""}
    except Exception as e:                                  # noqa: BLE001
        log.warning("gasto_mes_falló", error=type(e).__name__, detalle=str(e)[:160])
        datos = dict(vacio, detalle="%s: %s" % (type(e).__name__, str(e)[:160]))

    with _gasto_lock:
        _gasto_cache.update(cuando=ahora, datos=datos)
    return dict(datos, cacheado=False)


def resumen() -> Dict[str, Any]:
    """Lo que va al panel: números, no el detalle entero."""
    e = estado()
    g = gasto_mes()
    return {"google_legible": e["leible"],
            "cuenta_abierta": e["abierta"],
            "presupuestos": len(e["presupuestos"]),
            "presupuestos_detalle": e["presupuestos"],
            "google_detalle": e["detalle"],
            "gasto_mes": g["total"],
            "gasto_moneda": g["moneda"],
            "gasto_por_proyecto": g["por_proyecto"],
            "gasto_detalle": g["detalle"]}


def tope_de(proyecto_numero: Optional[str] = None) -> List[Dict[str, Any]]:
    """Los presupuestos que cubren un proyecto (o los de toda la cuenta si no se
    pasa ninguno). Un presupuesto sin `proyectos` cubre la cuenta entera."""
    todos = estado()["presupuestos"]
    if proyecto_numero is None:
        return [p for p in todos if not p["proyectos"]]
    aguja = "projects/%s" % proyecto_numero
    return [p for p in todos if aguja in p["proyectos"]]
