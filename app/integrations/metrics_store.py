"""
metrics_store — snapshots diarios de las métricas clave de la agencia.

Sirve para la línea de crecimiento del panel: MRR (USD), clientes activos, leads en
pipeline y ganancia del mes. Un job del scheduler appendea 1 snapshot/día; en lectura,
si falta el de hoy se calcula y se persiste. Persistencia: JSON en el volume.
"""
from __future__ import annotations

import json
import os
import re
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

import pytz

MAX_POINTS = 400  # ~13 meses de snapshots diarios
_LOCK = threading.Lock()  # serializa leer→modificar→guardar (job diario + lecturas del panel)
_TZ = pytz.timezone("America/Buenos_Aires")


def _data_dir() -> Path:
    return Path(__file__).resolve().parent.parent.parent / "data"


def _store_path() -> Path:
    return _data_dir() / "metrics-store.json"


def _today() -> str:
    return datetime.now(_TZ).strftime("%Y-%m-%d")


def load_store() -> Dict[str, Any]:
    p = _store_path()
    if not p.exists():
        return {"points": []}
    try:
        with p.open("r", encoding="utf-8") as f:
            data = json.load(f)
        data.setdefault("points", [])
        return data
    except Exception:
        return {"points": []}


def save_store(store: Dict[str, Any]) -> None:
    p = _store_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(store, f, ensure_ascii=False, indent=2)
    os.replace(tmp, p)


def _compute_today() -> Dict[str, Any]:
    """Snapshot del momento. Best-effort: cada métrica protegida por su try."""
    mrr = active = leads = profit = 0.0
    try:
        from . import clients_store as cs
        mrr = round(cs.mrr_usd(), 2)
        active = cs.active_count()
    except Exception:
        pass
    try:
        from . import leads_store as ls
        leads = ls.summary_counts(ls.load_store()).get("total", 0)
    except Exception:
        pass
    try:
        from . import finance_store as fs
        s = fs.finance_summary(1)
        profit = s.get("profit_month_usd", 0.0)
    except Exception:
        pass
    punto = {"date": _today(), "mrr_usd": mrr, "active_clients": active,
             "leads_total": leads, "profit_month_usd": profit}
    # El embudo de outbound: derivado, nunca escrito a mano. Ver `backfill_outbound`.
    hoy = _dias_outbound().get(punto["date"], {})
    punto["outbound_enviados"] = hoy.get("enviados", 0)
    punto["outbound_respuestas"] = hoy.get("respuestas", 0)
    punto["outbound_errores"] = _errores_outbound().get(punto["date"], 0)
    punto.update(_acumulados_outbound())
    return punto


def snapshot(force: bool = False) -> Dict[str, Any]:
    """Guarda (o refresca) el snapshot de hoy y lo devuelve."""
    pt = _compute_today()
    with _LOCK:
        store = load_store()
        points = [p for p in store["points"] if p.get("date") != pt["date"]]
        points.append(pt)
        points.sort(key=lambda p: p.get("date", ""))
        store["points"] = points[-MAX_POINTS:]
        save_store(store)
    return pt


# -- Embudo de outbound -------------------------------------------------------
# Por que vive aca y no en el reporte de outbound: entre el 2026-08-24 y el
# 2026-09-08 los agentes abrieron NUEVE pendientes distintos pidiendo lo mismo
# --"outbound tiene que reportar su serie historica"-- y ninguno se ejecuto. El
# diagnostico de fondo era otro: data_analyst, cuyo trabajo es medir el negocio,
# nunca tuvo UN numero del embudo. El snapshot diario guardaba MRR, clientes,
# `leads_total` (acumulado, sube cuando leadhunter carga leads y no dice nada de
# si salio un mail) y ganancia. Estaba ciego, y lo diagnostico bien nueve veces.
#
# Se resuelve en la fuente en vez de pedirle a un agente que le narre numeros a
# otro: los toques y las respuestas YA estan en leads_store con su fecha, asi que
# la serie se DERIVA. Nadie la escribe a mano, ningun modelo la puede inventar
# --que es justo el modo de falla que ya nos costo caro-- y arranca con todo el
# historial, no desde cero.


_RE_DIA = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _dia_valido(v: Any) -> str:
    """Un dato con fecha rota no puede meter una columna fantasma en la serie."""
    d = str(v or "")[:10]
    return d if _RE_DIA.match(d) else ""


def _dias_outbound() -> Dict[str, Dict[str, int]]:
    """Envios y respuestas por dia, derivados de leads_store. {fecha: {...}}"""
    out: Dict[str, Dict[str, int]] = {}
    try:
        from . import leads_store as ls
        leads = ls.load_store().get("leads", {})
    except Exception:
        return out
    for lead in leads.values():
        for toque in lead.get("touches", []) or []:
            dia = _dia_valido(toque.get("date"))
            if dia:
                out.setdefault(dia, {"enviados": 0, "respuestas": 0})["enviados"] += 1
        dia = _dia_valido(lead.get("last_reply_at"))
        if dia:
            out.setdefault(dia, {"enviados": 0, "respuestas": 0})["respuestas"] += 1
    return out


def _errores_outbound() -> Dict[str, int]:
    """Errores de envio por dia. Unico dato del embudo que NO se puede derivar de
    leads_store --un envio que fallo no deja toque--, asi que outbound lo anota en
    su propio log."""
    try:
        with (_data_dir() / "outbound-sent.json").open(encoding="utf-8") as f:
            crudos = (json.load(f).get("errores") or {}).items()
            return {_dia_valido(k): int(v) for k, v in crudos if _dia_valido(k)}
    except Exception:
        return {}


def _acumulados_outbound() -> Dict[str, int]:
    """Fotos del pipeline: cuantos leads esperan turno, cuantos ya se tocaron."""
    try:
        from . import leads_store as ls
        leads = ls.load_store().get("leads", {})
    except Exception:
        return {}
    estados: Dict[str, int] = {}
    for lead in leads.values():
        e = lead.get("state") or "nuevo"
        estados[e] = estados.get(e, 0) + 1
    return {
        "outbound_sin_tocar": estados.get("nuevo", 0),
        "outbound_contactados": estados.get("contactado", 0),
        "outbound_respondieron": estados.get("respondió", 0),
        "outbound_agotados": estados.get("sin_respuesta", 0),
    }


def backfill_outbound() -> int:
    """Reescribe el embudo en TODOS los puntos guardados, desde el historial real.

    Idempotente: se puede correr las veces que sea. Se llama al leer la serie, asi
    que el dia que se arregle un dato viejo en leads_store la serie se corrige sola.
    Devuelve cuantos puntos quedaron.
    """
    dias, errores = _dias_outbound(), _errores_outbound()
    if not dias and not errores:
        return 0
    with _LOCK:
        store = load_store()
        vistos = {p.get("date") for p in store["points"]}
        # Dias con actividad que nunca tuvieron snapshot (el store arranco despues, o
        # el job no corrio): se crean con el embudo solo. Es preferible un punto con
        # el embudo y sin MRR a un agujero en la serie.
        for dia in sorted(set(dias) | set(errores)):
            if dia not in vistos:
                store["points"].append({"date": dia})
        for punto in store["points"]:
            d = dias.get(punto.get("date"), {})
            punto["outbound_enviados"] = d.get("enviados", 0)
            punto["outbound_respuestas"] = d.get("respuestas", 0)
            punto["outbound_errores"] = errores.get(punto.get("date"), 0)
        store["points"].sort(key=lambda p: p.get("date", ""))
        store["points"] = store["points"][-MAX_POINTS:]
        save_store(store)
        return len(store["points"])


def resumen_outbound(dias: int = 21) -> str:
    """Tabla del embudo lista para pegar en un reporte. Sin modelo de por medio."""
    backfill_outbound()
    pts = [p for p in load_store()["points"] if p.get("outbound_enviados") is not None][-dias:]
    if not pts:
        return "_Sin historial de outbound todavia._"
    filas = ["| Dia | Enviados | Respuestas | Errores |", "|---|---:|---:|---:|"]
    for p in pts:
        filas.append("| {} | {} | {} | {} |".format(
            p.get("date"), p.get("outbound_enviados", 0),
            p.get("outbound_respuestas", 0), p.get("outbound_errores", 0)))
    env = sum(p.get("outbound_enviados", 0) for p in pts)
    resp = sum(p.get("outbound_respuestas", 0) for p in pts)
    tasa = "{:.1f}%".format(resp / env * 100) if env else "—"
    filas += ["", "**{}d:** {} enviados · {} respuestas · **{}** de respuesta".format(
        len(pts), env, resp, tasa)]
    acum = _acumulados_outbound()
    if acum:
        filas.append(
            "**Pipeline:** {} sin tocar · {} en secuencia · {} respondieron · "
            "{} agotaron la secuencia sin responder".format(
                acum.get("outbound_sin_tocar", 0), acum.get("outbound_contactados", 0),
                acum.get("outbound_respondieron", 0), acum.get("outbound_agotados", 0)))
    # La alarma que los agentes venian pidiendo, ahora con el dato para dispararla.
    ceros = 0
    for p in reversed(pts):
        if p.get("outbound_enviados", 0):
            break
        ceros += 1
    if ceros >= 3:
        filas.append("\n> ⛔ **{} dias seguidos sin un solo envio.** Outbound esta parado: "
                     "revisa el cupo diario, el token de Gmail y si quedan leads con turno."
                     .format(ceros))
    return "\n".join(filas)


def series() -> Dict[str, Any]:
    """Serie para los charts. Garantiza que el punto de hoy exista."""
    store = load_store()
    today = _today()
    if not any(p.get("date") == today for p in store["points"]):
        snapshot()
        store = load_store()
    backfill_outbound()
    pts = load_store()["points"]
    return {
        "dates": [p.get("date") for p in pts],
        "mrr_usd": [p.get("mrr_usd", 0) for p in pts],
        "active_clients": [p.get("active_clients", 0) for p in pts],
        "leads_total": [p.get("leads_total", 0) for p in pts],
        "profit_month_usd": [p.get("profit_month_usd", 0) for p in pts],
        "outbound_enviados": [p.get("outbound_enviados", 0) for p in pts],
        "outbound_respuestas": [p.get("outbound_respuestas", 0) for p in pts],
        "outbound_errores": [p.get("outbound_errores", 0) for p in pts],
    }
