"""payments_store — libro de pagos: la plata que ENTRÓ de verdad.

Por qué existe: `clients_store.billed_year` devenga desde la ficha del cliente
(alta + fee). Sirve para estimar "cuánto genera el año", pero no para conciliar
con el banco, y tiene un agujero: sin historial de estados, un cliente dado de
baja hace bajar el histórico retroactivamente. Acá cada cobro es un hecho con
fecha, y no se mueve nunca más.

Decisión central: **`amount_usd` se congela al FX del día del cobro**. Si se
recalculara con la cotización de hoy, un pago en ARS cambiaría de valor cada vez
que se mueve el dólar y el histórico no cerraría nunca.

Vive en DB (schema `agency`) y no en JSON del volumen como los gastos, porque
cada pago referencia un cliente y se consulta por cliente y por período.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

from . import db

CONCEPTOS = ["unico", "mensual", "otro"]
DEFAULT_CONCEPTO = "mensual"

_COLS = ("id, client_id, fecha, concepto, amount, currency, amount_usd, "
         "periodo, metodo, notes, created_at")


def enabled() -> bool:
    """Sin DB no hay libro de pagos: es lo único del panel que NO tiene fallback
    a JSON. Un libro contable a medias (que se pierde al reiniciar) es peor que
    no tenerlo, porque igual se le cree."""
    return db.enabled()


def _num(v: Any) -> float:
    try:
        return round(float(v or 0), 2)
    except (TypeError, ValueError):
        return 0.0


def _row(r: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(r)
    for k in ("fecha", "created_at"):
        v = out.get(k)
        if v is not None and not isinstance(v, str):
            out[k] = v.isoformat()
    for k in ("amount", "amount_usd"):
        if out.get(k) is not None:
            out[k] = float(out[k])
    return out


def add_payment(data: Dict[str, Any]) -> Dict[str, Any]:
    """Registra un cobro. `amount_usd` se calcula ACÁ y queda fijo."""
    from . import fx_store

    concepto = (data.get("concepto") or DEFAULT_CONCEPTO).lower().strip()
    if concepto not in CONCEPTOS:
        concepto = DEFAULT_CONCEPTO
    currency = (data.get("currency") or "USD").upper().strip()
    amount = _num(data.get("amount"))
    fecha = str(data.get("fecha") or date.today().isoformat())[:10]
    # `periodo` sólo tiene sentido en los mensuales; en los demás va NULL para
    # que el índice único parcial no bloquee dos pagos únicos del mismo cliente.
    periodo = (str(data.get("periodo") or "")[:7] or None) if concepto == "mensual" else None
    if concepto == "mensual" and not periodo:
        periodo = fecha[:7]

    pid = uuid.uuid4().hex[:12]
    db.execute(
        f"INSERT INTO payments ({_COLS.replace(', created_at', '')}) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (pid, data.get("client_id"), fecha, concepto, amount, currency,
         fx_store.to_usd(amount, currency), periodo,
         (data.get("metodo") or "").strip(), (data.get("notes") or "").strip()),
    )
    return get_payment(pid) or {"id": pid}


def get_payment(pid: str) -> Optional[Dict[str, Any]]:
    r = db.fetchone(f"SELECT {_COLS} FROM payments WHERE id=%s", (pid,))
    return _row(r) if r else None


def delete_payment(pid: str) -> bool:
    if not get_payment(pid):
        return False
    db.execute("DELETE FROM payments WHERE id=%s", (pid,))
    return True


def list_payments(client_id: Optional[str] = None, anio: Optional[int] = None,
                  limit: int = 200) -> List[Dict[str, Any]]:
    where, params = [], []
    if client_id:
        where.append("p.client_id=%s")
        params.append(client_id)
    if anio:
        where.append("date_part('year', p.fecha)=%s")
        params.append(int(anio))
    sql = ("SELECT p.id, p.client_id, p.fecha, p.concepto, p.amount, p.currency, "
           "p.amount_usd, p.periodo, p.metodo, p.notes, p.created_at, "
           "c.name AS client_name FROM payments p "
           "LEFT JOIN clients c ON c.id = p.client_id")
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY p.fecha DESC, p.created_at DESC LIMIT %s"
    params.append(int(limit))
    return [_row(r) for r in db.fetchall(sql, params)]


def collected_by_month(months: int = 12) -> Dict[str, float]:
    """Cobrado por mes (USD), desde pagos reales. La clave es `YYYY-MM`.

    Existe para que finanzas muestre la plata que ENTRÓ: hasta ahora el panel
    sólo graficaba el MRR devengado de los clientes activos, así que un cobro
    real no movía ni el ingreso ni la ganancia del mes.
    """
    filas = db.fetchall(
        "SELECT to_char(p.fecha, 'YYYY-MM') AS mes, SUM(p.amount_usd) AS usd "
        "FROM payments p WHERE p.fecha >= (CURRENT_DATE - INTERVAL '%s months') "
        "GROUP BY 1" % int(max(1, months)))
    return {r["mes"]: round(float(r["usd"] or 0), 2) for r in filas if r.get("mes")}


def collected_year(anio: Optional[int] = None) -> Dict[str, Any]:
    """Cobrado del año, desde pagos reales. Este SÍ concilia con el banco."""
    y = int(anio or datetime.now(timezone.utc).year)
    filas = db.fetchall(
        "SELECT p.concepto, SUM(p.amount_usd) AS usd, COUNT(*) AS n "
        "FROM payments p WHERE date_part('year', p.fecha)=%s GROUP BY p.concepto", (y,))
    por_concepto = {r["concepto"]: {"usd": float(r["usd"] or 0), "n": int(r["n"])}
                    for r in filas}
    por_cliente = [
        {"client_id": r["client_id"], "name": r["client_name"],
         "usd": float(r["usd"] or 0), "n": int(r["n"])}
        for r in db.fetchall(
            "SELECT p.client_id, c.name AS client_name, SUM(p.amount_usd) AS usd, "
            "COUNT(*) AS n FROM payments p LEFT JOIN clients c ON c.id=p.client_id "
            "WHERE date_part('year', p.fecha)=%s GROUP BY p.client_id, c.name "
            "ORDER BY 3 DESC", (y,))]
    return {
        "anio": y,
        "unico_usd": round(por_concepto.get("unico", {}).get("usd", 0.0), 2),
        "mensual_usd": round(por_concepto.get("mensual", {}).get("usd", 0.0), 2),
        "otro_usd": round(por_concepto.get("otro", {}).get("usd", 0.0), 2),
        "total_usd": round(sum(v["usd"] for v in por_concepto.values()), 2),
        "pagos": sum(v["n"] for v in por_concepto.values()),
        "por_cliente": por_cliente,
    }
