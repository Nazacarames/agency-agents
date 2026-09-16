"""
eventos — UNA línea de tiempo de lo que hicieron los agentes.

El problema que resuelve: `write_run_log` persistía en `logs/agent_runs.jsonl`,
adentro del contenedor y sin disco montado, así que el archivo moría en cada
deploy; y guardaba tokens y latencia, no acciones. Qué mail salió, a quién, qué
se publicó y con qué link estaba repartido entre 13 JSON de `data/`, Discord y
el backlog. Sin un solo lugar donde mirar, un agente que hace macanas durante un
mes no se nota hasta que alguien escarba.

Acá se anota lo que SALE AL MUNDO (mail, post, video) y el resultado de cada
corrida, en `agency.agent_events`. Con fallback a JSON si no hay DB, igual que
el resto de los stores.

Dos reglas:
  • Nunca levanta. Una bitácora que voltea una corrida es peor que no tenerla.
  • El agente no se pasa a mano por toda la pila: `en_curso()` lo deja en un
    contextvar y `gmail_client` o `social_publish` lo leen solos.
"""
from __future__ import annotations

import contextvars
import json
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..log import get_logger
from . import db
from .jsonstore import write_json_atomic

log = get_logger("eventos")

# Cuántos eventos se guardan en el fallback JSON. No es el registro bueno: es lo
# que queda cuando no hay DB, y un archivo que crece sin techo se come el disco.
MAX_JSON = 2000

_CTX: contextvars.ContextVar[tuple] = contextvars.ContextVar("evento_ctx", default=("", ""))


@contextmanager
def en_curso(agente: str, run_id: str = ""):
    """Marca de quién es lo que pase acá adentro."""
    token = _CTX.set((agente or "", run_id or ""))
    try:
        yield
    finally:
        _CTX.reset(token)


def actor() -> tuple:
    """(agente, run_id) de la corrida en curso, o ('', '') si nadie lo marcó."""
    return _CTX.get()


def _json_path() -> Path:
    return Path(__file__).resolve().parent.parent.parent / "data" / "agent-events.json"


def _json_load() -> List[Dict[str, Any]]:
    p = _json_path()
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def registrar(tipo: str, resumen: str, *, agente: str = "", run_id: str = "",
              destino: str = "", ref: str = "", ok: bool = True,
              estado: str = "hecho",
              detalle: Optional[Dict[str, Any]] = None) -> Optional[int]:
    """Anota un evento. Devuelve su id (o None si no pudo anotarlo en ningún lado)."""
    ag, rid = actor()
    fila = {
        "tipo": (tipo or "")[:40],
        "agente": (agente or ag)[:80],
        "run_id": (run_id or rid)[:80],
        "resumen": (resumen or "")[:500],
        "destino": (destino or "")[:200],
        "ref": (ref or "")[:300],
        "ok": bool(ok),
        "estado": (estado or "hecho")[:20],
        "detalle": detalle or {},
    }
    if db.enabled():
        try:
            row = db.fetchone(
                "INSERT INTO agent_events (tipo, agente, run_id, resumen, destino, ref,"
                " ok, estado, detalle) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                (fila["tipo"], fila["agente"], fila["run_id"], fila["resumen"],
                 fila["destino"], fila["ref"], fila["ok"], fila["estado"],
                 json.dumps(fila["detalle"], ensure_ascii=False)),
            )
            return int(row["id"]) if row else None
        except Exception as e:
            log.warning("evento_db_fallo", tipo=fila["tipo"], error=str(e)[:200])
    try:
        items = _json_load()
        fila["id"] = max((int(i.get("id", 0)) for i in items), default=0) + 1
        fila["ts"] = datetime.now(timezone.utc).isoformat()
        items.append(fila)
        write_json_atomic(_json_path(), items[-MAX_JSON:], indent=2)
        return int(fila["id"])
    except Exception as e:
        log.warning("evento_json_fallo", tipo=fila["tipo"], error=str(e)[:200])
        return None


def ultimos(limite: int = 50, *, tipo: str = "", agente: str = "",
            estado: str = "") -> List[Dict[str, Any]]:
    """La línea de tiempo, lo más nuevo primero. Sin esto la bitácora vuelve a
    ser de sólo escritura, que es el bug que vinimos a arreglar."""
    limite = max(1, min(int(limite or 50), 500))
    if db.enabled():
        try:
            where, params = [], []
            for col, val in (("tipo", tipo), ("agente", agente), ("estado", estado)):
                if val:
                    where.append(f"{col} = %s")
                    params.append(val)
            sql = "SELECT * FROM agent_events"
            if where:
                sql += " WHERE " + " AND ".join(where)
            sql += " ORDER BY ts DESC, id DESC LIMIT %s"
            params.append(limite)
            filas = db.fetchall(sql, params)
            for f in filas:
                if f.get("ts") is not None and not isinstance(f["ts"], str):
                    f["ts"] = f["ts"].isoformat()
            return filas
        except Exception as e:
            log.warning("eventos_db_fallo", error=str(e)[:200])
    items = _json_load()
    if tipo:
        items = [i for i in items if i.get("tipo") == tipo]
    if agente:
        items = [i for i in items if i.get("agente") == agente]
    if estado:
        items = [i for i in items if i.get("estado") == estado]
    return list(reversed(items))[:limite]
