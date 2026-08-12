"""
missions_store — misiones del CEO.

Una misión = un objetivo del operador que se reparte a varios agentes de una.
El operador (o yo como CEO) define el objetivo + a qué agentes mandárselo; cada
agente lo recibe como tarea prioritaria. Backend: Postgres (schema `agency`) con
fallback JSON.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import db


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _iso(v: Any) -> Any:
    return v.isoformat() if v is not None and not isinstance(v, str) else v


def _data_dir() -> Path:
    return Path(__file__).resolve().parent.parent.parent / "data"


def _json_path() -> Path:
    return _data_dir() / "missions-store.json"


def _json_load() -> Dict[str, Any]:
    p = _json_path()
    if not p.exists():
        return {"missions": []}
    try:
        data = json.load(p.open(encoding="utf-8"))
        data.setdefault("missions", [])
        return data
    except Exception:
        return {"missions": []}


def _json_save(store: Dict[str, Any]) -> None:
    p = _json_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    json.dump(store, tmp.open("w", encoding="utf-8"), ensure_ascii=False, indent=2)
    os.replace(tmp, p)


def _row(r: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(r)
    for k in ("created_at", "updated_at"):
        if k in out:
            out[k] = _iso(out[k])
    return out


_COLS = "id,objective,agents,client_id,status,run_ids,plan,notes,created_at,updated_at"


def create_mission(objective: str, agents: List[str], client_id: Optional[str] = None,
                   run_ids: Optional[Dict[str, str]] = None, notes: str = "",
                   plan: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    run_ids = run_ids or {}
    plan = plan or []
    if db.enabled():
        r = db.fetchone(
            "INSERT INTO missions (objective,agents,client_id,run_ids,plan,notes) "
            "VALUES (%s,%s,%s,%s,%s,%s) RETURNING " + _COLS,
            (objective, agents, client_id or None, json.dumps(run_ids), json.dumps(plan), notes or ""))
        return _row(r) if r else {}
    store = _json_load()
    mid = (max([int(m.get("id", 0)) for m in store["missions"]], default=0)) + 1
    m = {"id": mid, "objective": objective, "agents": agents, "client_id": client_id,
         "status": "lanzada", "run_ids": run_ids, "plan": plan, "notes": notes,
         "created_at": _now(), "updated_at": _now()}
    store["missions"].insert(0, m)
    _json_save(store)
    return m


def list_missions(limit: int = 50) -> List[Dict[str, Any]]:
    if db.enabled():
        rows = db.fetchall(f"SELECT {_COLS} FROM missions ORDER BY created_at DESC LIMIT %s", (limit,))
        return [_row(r) for r in rows]
    return _json_load()["missions"][:limit]


def update_mission(mission_id: Any, fields: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    # `plan` entra acá porque es donde vive el veredicto por agente de cada
    # delegación. Sin eso una misión no tenía forma de cerrarse: las 15 que había al
    # 2026-08-12 estaban todas en "lanzada" y `update_mission` no la llamaba nadie.
    allowed = {k: v for k, v in fields.items()
               if k in ("status", "notes", "plan") and v is not None}
    if not allowed:
        return None
    if db.enabled():
        vals = [json.dumps(v) if k == "plan" else v for k, v in allowed.items()]
        sets = ", ".join(f"{k}=%s" for k in allowed) + ", updated_at=now()"
        r = db.fetchone(f"UPDATE missions SET {sets} WHERE id=%s RETURNING " + _COLS,
                        vals + [mission_id])
        return _row(r) if r else None
    store = _json_load()
    for m in store["missions"]:
        if str(m.get("id")) == str(mission_id):
            m.update(allowed); m["updated_at"] = _now()
            _json_save(store)
            return m
    return None


def delete_mission(mission_id: Any) -> bool:
    if db.enabled():
        db.execute("DELETE FROM missions WHERE id=%s", (mission_id,))
        return True
    store = _json_load()
    before = len(store["missions"])
    store["missions"] = [m for m in store["missions"] if str(m.get("id")) != str(mission_id)]
    if len(store["missions"]) != before:
        _json_save(store)
        return True
    return False


# ───────────────── delegaciones: veredicto y cumplimiento ─────────────────
#
# El Chief reparte trabajo todas las noches y guarda cada tanda como una misión
# "Delegaciones del cierre del <fecha>". Hasta el 2026-08-12 esas misiones nacían
# en `lanzada` y ahí morían: eran 15, todas lanzadas, y `update_mission` no la
# llamaba nadie. El Chief SÍ evaluaba si se habían cumplido —lo escribía en prosa
# en su brief con ✅ / ⏫ / 🗑️— pero ese veredicto no volvía nunca al registro.
# Resultado: un contador que subía 1 por día y no distinguía delegar bien de
# delegar al vacío.

_PREFIJO_DELEG = "Delegaciones del cierre"


def _es_delegacion(m: Dict[str, Any]) -> bool:
    return str(m.get("objective", "")).startswith(_PREFIJO_DELEG)


def marcar_delegacion(agente: str, cumplida: bool, nota: str = "",
                      limite: int = 6) -> Optional[Dict[str, Any]]:
    """Marca la delegación pendiente MÁS RECIENTE de `agente` como cumplida o no.

    Devuelve la misión actualizada, o None si ese agente no tenía nada pendiente.
    El estado de la misión se recalcula solo: `cumplida` si todos sus ítems se
    hicieron, `incumplida` si ninguno, `parcial` si quedó a medias.
    """
    agente = (agente or "").strip().lower()
    nota = " ".join((nota or "").split())[:300]
    if not agente:
        return None
    for m in list_missions(limit=limite):
        if not _es_delegacion(m) or m.get("status") not in ("lanzada", "parcial"):
            continue
        plan = m.get("plan") or []
        if isinstance(plan, str):
            try:
                plan = json.loads(plan)
            except Exception:
                continue
        item = next((p for p in plan if isinstance(p, dict)
                     and str(p.get("agent", "")).lower() == agente
                     and "hecho" not in p), None)
        if item is None:
            continue
        item["hecho"] = bool(cumplida)
        item["veredicto"] = nota
        item["cerrado_at"] = _now()
        juzgados = [p for p in plan if isinstance(p, dict) and "hecho" in p]
        if len(juzgados) < len([p for p in plan if isinstance(p, dict)]):
            estado = "parcial"
        else:
            hechos = sum(1 for p in juzgados if p.get("hecho"))
            estado = "cumplida" if hechos == len(juzgados) else (
                "incumplida" if hechos == 0 else "parcial")
        return update_mission(m.get("id"), {"plan": plan, "status": estado})
    return None


def cumplimiento(agente: str, limite: int = 8) -> Dict[str, Any]:
    """Track record del agente en sus delegaciones ya juzgadas.

    Es el insumo del bucle de mejora: un agente que ve "cumpliste 2 de 5, y esta
    quedó sin hacer" tiene el dato para corregirse. Antes ese resultado existía
    sólo en la prosa del brief de esa noche y se perdía al día siguiente.
    """
    agente = (agente or "").strip().lower()
    hechas = fallidas = 0
    pendiente = ultima_fallida = ""
    for m in list_missions(limit=limite):
        if not _es_delegacion(m):
            continue
        plan = m.get("plan") or []
        if isinstance(plan, str):
            try:
                plan = json.loads(plan)
            except Exception:
                continue
        for p in plan:
            if not isinstance(p, dict) or str(p.get("agent", "")).lower() != agente:
                continue
            if "hecho" not in p:
                pendiente = pendiente or str(p.get("task", ""))[:200]
            elif p.get("hecho"):
                hechas += 1
            else:
                fallidas += 1
                ultima_fallida = ultima_fallida or (
                    f"{str(p.get('task',''))[:140]} → {str(p.get('veredicto',''))[:100]}")
    return {"cumplidas": hechas, "juzgadas": hechas + fallidas,
            "pendiente": pendiente, "ultima_fallida": ultima_fallida}


def bloque_cumplimiento(agente: str) -> str:
    """El track record como texto para meter en el prompt del agente."""
    c = cumplimiento(agente)
    if not c["juzgadas"] and not c["pendiente"]:
        return ""
    partes = ["### Tu historial con las órdenes de Dirección"]
    if c["juzgadas"]:
        partes.append(f"Cumpliste **{c['cumplidas']} de {c['juzgadas']}** delegaciones juzgadas.")
    if c["ultima_fallida"]:
        partes.append(f"La última que NO cumpliste: {c['ultima_fallida']}\n"
                      "Si te la vuelven a pedir y seguís sin poder, decí por qué en tu "
                      "reporte en vez de dejarla pasar de nuevo.")
    if c["pendiente"]:
        partes.append(f"Tenés una pendiente de ser juzgada: {c['pendiente']}")
    return "\n".join(partes)
