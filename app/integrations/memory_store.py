"""
memory_store — memoria GENERAL de la agencia + objetivos de growth + lecciones.

Tres cosas, todas en el schema `agency` de Supabase (con fallback JSON):
  • company_memory   — knowledge base de la empresa (seed desde Obsidian + contexto).
  • growth_objectives — objetivos de crecimiento por sector.
  • agent_lessons     — lecciones por agente (loop de mejora continua).

Expone `company_digest()` y `lessons_for(agent)` que arman bloques de texto
compactos para inyectar en el prompt de cualquier agente (esto es el sustrato
del "aprendizaje": cada corrida arranca con el contexto + lo aprendido).
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..log import get_logger

log = get_logger("memory_store")

from . import db


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _iso(v: Any) -> Any:
    return v.isoformat() if v is not None and not isinstance(v, str) else v


def _data_dir() -> Path:
    return Path(__file__).resolve().parent.parent.parent / "data"


def _json_path() -> Path:
    return _data_dir() / "agency-memory.json"


def _json_load() -> Dict[str, Any]:
    p = _json_path()
    if not p.exists():
        return {"company_memory": [], "growth_objectives": [], "agent_lessons": []}
    try:
        with p.open("r", encoding="utf-8") as f:
            data = json.load(f)
        for k in ("company_memory", "growth_objectives", "agent_lessons"):
            data.setdefault(k, [])
        return data
    except Exception:
        return {"company_memory": [], "growth_objectives": [], "agent_lessons": []}


def _json_save(store: Dict[str, Any]) -> None:
    p = _json_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(store, f, ensure_ascii=False, indent=2)
    os.replace(tmp, p)


def _next_id(items: List[Dict[str, Any]]) -> int:
    """ID incremental para el fallback JSON. max+1 (no len+1: tras un borrado,
    len+1 colisiona con un ID vivo y update/delete pegan en el registro equivocado)."""
    mx = 0
    for it in items:
        try:
            mx = max(mx, int(it.get("id", 0)))
        except (TypeError, ValueError):
            continue
    return mx + 1


# ───────────────────────── company_memory (KB general) ─────────────────────────

def upsert_company_memory(section: str, title: str, content: str,
                          source: str = "", tags: Optional[List[str]] = None) -> Dict[str, Any]:
    section = (section or "general").strip() or "general"
    tags = tags or []
    if db.enabled():
        row = db.fetchone(
            "INSERT INTO company_memory (section,title,content,source,tags,updated_at) "
            "VALUES (%s,%s,%s,%s,%s,now()) "
            "ON CONFLICT (section,title) DO UPDATE SET "
            "content=EXCLUDED.content, source=EXCLUDED.source, tags=EXCLUDED.tags, updated_at=now() "
            "RETURNING id,section,title,content,source,tags,created_at,updated_at",
            (section, title, content, source, tags),
        )
        return {**row, "created_at": _iso(row["created_at"]), "updated_at": _iso(row["updated_at"])} if row else {}
    store = _json_load()
    for m in store["company_memory"]:
        if m["section"] == section and m["title"] == title:
            m.update({"content": content, "source": source, "tags": tags, "updated_at": _now()})
            _json_save(store)
            return m
    item = {"id": _next_id(store["company_memory"]), "section": section, "title": title,
            "content": content, "source": source, "tags": tags,
            "created_at": _now(), "updated_at": _now()}
    store["company_memory"].append(item)
    _json_save(store)
    return item


def list_company_memory(section: Optional[str] = None) -> List[Dict[str, Any]]:
    if db.enabled():
        if section:
            rows = db.fetchall("SELECT id,section,title,content,source,tags,created_at,updated_at "
                               "FROM company_memory WHERE section=%s ORDER BY section,title", (section,))
        else:
            rows = db.fetchall("SELECT id,section,title,content,source,tags,created_at,updated_at "
                               "FROM company_memory ORDER BY section,title")
        return [{**r, "created_at": _iso(r["created_at"]), "updated_at": _iso(r["updated_at"])} for r in rows]
    items = _json_load()["company_memory"]
    return [m for m in items if not section or m["section"] == section]


def delete_company_memory(mem_id: Any) -> bool:
    if db.enabled():
        db.execute("DELETE FROM company_memory WHERE id=%s", (mem_id,))
        return True
    store = _json_load()
    before = len(store["company_memory"])
    store["company_memory"] = [m for m in store["company_memory"] if str(m["id"]) != str(mem_id)]
    if len(store["company_memory"]) != before:
        _json_save(store)
        return True
    return False


def update_company_memory(mem_id: Any, fields: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    allowed = {k: (v if k != "tags" else (v or []))
               for k, v in fields.items()
               if k in ("section", "title", "content", "source", "tags") and v is not None}
    if not allowed:
        return None
    if db.enabled():
        sets = ", ".join(f"{k}=%s" for k in allowed) + ", updated_at=now()"
        row = db.fetchone(f"UPDATE company_memory SET {sets} WHERE id=%s "
                          "RETURNING id,section,title,content,source,tags,created_at,updated_at",
                          list(allowed.values()) + [mem_id])
        return {**row, "created_at": _iso(row["created_at"]), "updated_at": _iso(row["updated_at"])} if row else None
    store = _json_load()
    for m in store["company_memory"]:
        if str(m["id"]) == str(mem_id):
            m.update(allowed); m["updated_at"] = _now()
            _json_save(store)
            return m
    return None


# ───────────────────────── growth_objectives ─────────────────────────

def list_growth(sector: Optional[str] = None, status: Optional[str] = None) -> List[Dict[str, Any]]:
    if db.enabled():
        clauses, params = [], []
        if sector:
            clauses.append("sector=%s"); params.append(sector)
        if status:
            clauses.append("status=%s"); params.append(status)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = db.fetchall("SELECT id,sector,objective,metric,target,status,notes,created_at,updated_at "
                           f"FROM growth_objectives{where} ORDER BY sector, status", params)
        return [{**r, "created_at": _iso(r["created_at"]), "updated_at": _iso(r["updated_at"])} for r in rows]
    items = _json_load()["growth_objectives"]
    return [o for o in items
            if (not sector or o["sector"] == sector) and (not status or o["status"] == status)]


def add_growth(sector: str, objective: str, metric: str = "", target: str = "",
               status: str = "activo", notes: str = "") -> Dict[str, Any]:
    if db.enabled():
        row = db.fetchone(
            "INSERT INTO growth_objectives (sector,objective,metric,target,status,notes) "
            "VALUES (%s,%s,%s,%s,%s,%s) "
            "RETURNING id,sector,objective,metric,target,status,notes,created_at,updated_at",
            (sector or "general", objective, metric, target, status, notes))
        return {**row, "created_at": _iso(row["created_at"]), "updated_at": _iso(row["updated_at"])} if row else {}
    store = _json_load()
    item = {"id": _next_id(store["growth_objectives"]), "sector": sector or "general",
            "objective": objective, "metric": metric, "target": target, "status": status,
            "notes": notes, "created_at": _now(), "updated_at": _now()}
    store["growth_objectives"].append(item)
    _json_save(store)
    return item


def update_growth(obj_id: Any, fields: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    allowed = {k: v for k, v in fields.items()
               if k in ("sector", "objective", "metric", "target", "status", "notes") and v is not None}
    if not allowed:
        return None
    if db.enabled():
        sets = ", ".join(f"{k}=%s" for k in allowed) + ", updated_at=now()"
        row = db.fetchone(f"UPDATE growth_objectives SET {sets} WHERE id=%s "
                          "RETURNING id,sector,objective,metric,target,status,notes,created_at,updated_at",
                          list(allowed.values()) + [obj_id])
        return {**row, "created_at": _iso(row["created_at"]), "updated_at": _iso(row["updated_at"])} if row else None
    store = _json_load()
    for o in store["growth_objectives"]:
        if str(o["id"]) == str(obj_id):
            o.update(allowed); o["updated_at"] = _now()
            _json_save(store)
            return o
    return None


def delete_growth(obj_id: Any) -> bool:
    if db.enabled():
        db.execute("DELETE FROM growth_objectives WHERE id=%s", (obj_id,))
        return True
    store = _json_load()
    before = len(store["growth_objectives"])
    store["growth_objectives"] = [o for o in store["growth_objectives"] if str(o["id"]) != str(obj_id)]
    if len(store["growth_objectives"]) != before:
        _json_save(store)
        return True
    return False


# ───────────────────────── agent_lessons (loop de mejora) ─────────────────────────

def add_lesson(agent: str, lesson: str, kind: str = "feedback", weight: int = 1) -> Dict[str, Any]:
    if db.enabled():
        row = db.fetchone(
            "INSERT INTO agent_lessons (agent,kind,lesson,weight) VALUES (%s,%s,%s,%s) "
            "RETURNING id,agent,kind,lesson,weight,active,created_at",
            (agent, kind, lesson, weight))
        return {**row, "created_at": _iso(row["created_at"])} if row else {}
    store = _json_load()
    item = {"id": _next_id(store["agent_lessons"]), "agent": agent, "kind": kind,
            "lesson": lesson, "weight": weight, "active": True, "created_at": _now()}
    store["agent_lessons"].append(item)
    _json_save(store)
    return item


def bump_lesson_weight(lesson_id: Any, by: int = 1) -> bool:
    """Suma `by` al peso de una lección (refuerzo). Mayor peso = sube en lessons_for."""
    by = max(1, int(by or 1))
    if db.enabled():
        db.execute("UPDATE agent_lessons SET weight = weight + %s WHERE id=%s", (by, lesson_id))
        return True
    store = _json_load()
    for l in store["agent_lessons"]:
        if str(l["id"]) == str(lesson_id):
            l["weight"] = int(l.get("weight", 1)) + by
            _json_save(store)
            return True
    return False


def _huella(texto: str) -> frozenset:
    """Las palabras con carga semántica de una lección, para comparar dos que dicen
    lo mismo con otras palabras."""
    import re
    from unicodedata import normalize as _n
    t = _n("NFKD", (texto or "").lower()).encode("ascii", "ignore").decode()
    vacias = {"el", "la", "los", "las", "un", "una", "de", "del", "que", "y", "o", "a",
              "en", "es", "no", "se", "con", "por", "para", "su", "sus", "al", "lo",
              "mas", "pero", "si", "ya", "cuando", "como", "sobre", "hay", "este",
              "esta", "eso", "ese", "nos", "le", "les", "ni", "sin", "the", "of"}
    return frozenset(p for p in re.findall(r"[a-z0-9]{3,}", t) if p not in vacias)


def _mismo_tema(a: str, b: str, umbral: float = 0.65) -> bool:
    """Jaccard sobre las palabras con carga. 0.65 separa bien 'la misma lección
    reescrita' de 'dos lecciones distintas del mismo tema' — medido sobre las 592
    que había el 2026-09-08."""
    ha, hb = _huella(a), _huella(b)
    if not ha or not hb:
        return False
    return len(ha & hb) / len(ha | hb) >= umbral


def record_outcome(agent: str, lesson: str, weight: int = 1) -> Optional[Dict[str, Any]]:
    """Lección automática de tipo 'outcome'. Es el motor del aprendizaje automático:
    lo dispara el pipeline cuando observa un resultado real (p.ej. un lead respondió).
    Si la lección ya existe, REFUERZA su peso en vez de duplicar — así las señales
    que se repiten suben de prioridad y se inyectan primero.

    El parecido se mide por CONTENIDO, no por string exacto. Exigir igualdad byte a
    byte no reforzaba nunca: dos lecciones escritas por un LLM jamás salen idénticas,
    así que el 2026-09-08 había 551 lecciones de 592 estancadas en peso 1 y cada
    aprendizaje nuevo empujaba al anterior fuera del prompt (sólo entran 8).
    """
    lesson = (lesson or "").strip()
    if not lesson:
        return None
    # Un pedido bloqueado NO es una lección: es un pendiente. Colarlo acá le come
    # un lugar de los 8 a un aprendizaje de verdad, y encima se repite cada corrida
    # mientras siga bloqueado.
    if re.search(r"PENDIENTE\s*\(|hace falta (acceso|presupuesto)|conseguir acceso",
                 lesson, re.IGNORECASE):
        log.info("leccion_descartada_es_pendiente", agent=agent, texto=lesson[:80])
        return None
    for l in list_lessons(agent=agent, active_only=True):
        actual = l.get("lesson", "").strip()
        if actual == lesson or _mismo_tema(actual, lesson):
            bump_lesson_weight(l.get("id"), by=weight)   # refuerzo
            return l
    return add_lesson(agent, lesson, kind="outcome", weight=weight)


def list_lessons(agent: Optional[str] = None, active_only: bool = True) -> List[Dict[str, Any]]:
    if db.enabled():
        clauses, params = [], []
        if agent:
            clauses.append("agent=%s"); params.append(agent)
        if active_only:
            clauses.append("active=true")
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = db.fetchall("SELECT id,agent,kind,lesson,weight,active,created_at "
                           f"FROM agent_lessons{where} ORDER BY weight DESC, created_at DESC", params)
        return [{**r, "created_at": _iso(r["created_at"])} for r in rows]
    items = _json_load()["agent_lessons"]
    return [l for l in items
            if (not agent or l["agent"] == agent) and (not active_only or l.get("active", True))]


def deactivate_lesson(lesson_id: Any) -> bool:
    if db.enabled():
        db.execute("UPDATE agent_lessons SET active=false WHERE id=%s", (lesson_id,))
        return True
    store = _json_load()
    for l in store["agent_lessons"]:
        if str(l["id"]) == str(lesson_id):
            l["active"] = False
            _json_save(store)
            return True
    return False


def delete_lesson(lesson_id: Any) -> bool:
    """Borrado real (no sólo desactivar)."""
    if db.enabled():
        db.execute("DELETE FROM agent_lessons WHERE id=%s", (lesson_id,))
        return True
    store = _json_load()
    before = len(store["agent_lessons"])
    store["agent_lessons"] = [l for l in store["agent_lessons"] if str(l["id"]) != str(lesson_id)]
    if len(store["agent_lessons"]) != before:
        _json_save(store)
        return True
    return False


def update_lesson(lesson_id: Any, lesson: str) -> bool:
    if db.enabled():
        db.execute("UPDATE agent_lessons SET lesson=%s WHERE id=%s", (lesson, lesson_id))
        return True
    store = _json_load()
    for l in store["agent_lessons"]:
        if str(l["id"]) == str(lesson_id):
            l["lesson"] = lesson
            _json_save(store)
            return True
    return False


# ───────────────────────── digests para inyectar en prompts ─────────────────────────

def company_digest(max_chars: int = 3500) -> str:
    """Contexto de empresa + objetivos de growth activos, compacto, para el prompt."""
    parts: List[str] = []
    mem = list_company_memory()
    if mem:
        by_section: Dict[str, List[str]] = {}
        for m in mem:
            by_section.setdefault(m["section"], []).append(f"- {m['title']}: {m['content']}")
        for section, lines in by_section.items():
            parts.append(f"### {section}\n" + "\n".join(lines))
    growth = list_growth(status="activo")
    if growth:
        gl = [f"- [{g['sector']}] {g['objective']}" +
              (f" (meta: {g['target']})" if g.get("target") else "") for g in growth]
        parts.append("### objetivos de growth (activos)\n" + "\n".join(gl))
    return ("\n\n".join(parts))[:max_chars]


def lessons_for(agent: str, max_items: int = 10, max_chars: int = 2400) -> str:
    """Lecciones aprendidas de un agente, para inyectar en su prompt.

    Mezcla a propósito DURADERAS + RECIENTES. El orden de `list_lessons` es
    `weight DESC, created_at DESC`, así que cortar los primeros N daba "las más
    nuevas" cuando casi todo pesa 1 — y una directiva del dueño de julio quedaba
    enterrada bajo el aprendizaje de anteayer. Reservando lugares para las de más
    peso, lo que se ganó a fuerza de repetirse no se cae del prompt.
    """
    rows = list_lessons(agent=agent, active_only=True)
    if not rows:
        return ""

    duraderas = [l for l in rows if int(l.get("weight") or 1) > 1][:max_items // 2]
    ids = {id(l) for l in duraderas}
    recientes = [l for l in rows if id(l) not in ids][:max_items - len(duraderas)]

    partes = []
    if duraderas:
        partes.append("Lecciones que ya se confirmaron varias veces (pesan más):\n"
                      + "\n".join(f"- {_con_fecha(l)}" for l in duraderas))
    if recientes:
        partes.append("Lo aprendido más recientemente:\n"
                      + "\n".join(f"- {_con_fecha(l)}" for l in recientes))
    if any(_tiene_numeros(l) for l in duraderas + recientes):
        partes.append("⚠️ Las lecciones con números (tasas, rankings, porcentajes) valían "
                      "en SU fecha. Un número medido hace meses puede ser falso hoy y el "
                      "peso alto sólo significa que se repitió, no que se re-verificó. Si "
                      "vas a DECIDIR sobre una de esas cifras, medila de nuevo primero.")
    return "\n\n".join(partes)[:max_chars]


_RE_NUMEROS = re.compile(r"\d+\s*%|\d+\s*/\s*\d+|\bratio\b|\branking\b", re.IGNORECASE)


def _tiene_numeros(l: Dict[str, Any]) -> bool:
    return bool(_RE_NUMEROS.search(l.get("lesson", "")))


def _con_fecha(l: Dict[str, Any]) -> str:
    """La lección con su fecha cuando afirma un número.

    Sin esto, 'manufacturing convierte 3%' se lee como una verdad presente. El
    2026-09-08 esa lección estaba en peso 33 —la más influyente del sistema— y ya
    era falsa: medida de nuevo daba 2 y 2, indistinguible. El peso venía de haberse
    repetido, no de haberse re-verificado.
    """
    texto = l.get("lesson", "")
    if not _tiene_numeros(l):
        return texto
    fecha = str(l.get("created_at") or "")[:10]
    return f"{texto}  [medido {fecha}]" if fecha else texto
