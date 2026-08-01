"""
vault_search — los agentes consultan la documentación del vault de Obsidian.

El cerebro (`data/brain-graph.json`, que sube `scripts/brain_sync.py` desde la
máquina del dueño) trae un extracto por nota además del título y los links. Esto
lo vuelve BUSCABLE: dado el tema de la corrida, devuelve los pasajes más
relevantes para inyectarlos al prompt del agente. Así el agente cita la doctrina
propia de la agencia en vez de improvisar.

Sin dependencias ni índice persistido: 350 notas se escanean en milisegundos y
el resultado se cachea en memoria hasta que cambia el archivo.
"""
from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any, Dict, List

from ..log import get_logger

log = get_logger("vault_search")

_FILE = Path(__file__).resolve().parent.parent.parent / "data" / "brain-graph.json"
_WORD = re.compile(r"[a-záéíóúüñ0-9]{4,}")
# Ruido del español + palabras que aparecen en CASI toda nota nuestra (agencia,
# agente, automiq…) y que sin filtrar hacen matchear cualquier cosa con todo.
_STOP = {
    "para", "como", "pero", "porque", "cuando", "donde", "desde", "hasta", "sobre",
    "entre", "todo", "toda", "todos", "todas", "esto", "esta", "este", "estos",
    "estas", "otro", "otra", "otros", "otras", "cada", "ser", "hacer", "tiene",
    "tienen", "hace", "hacen", "puede", "pueden", "debe", "deben", "está", "están",
    "esta", "estan", "también", "tambien", "solo", "sólo", "más", "menos", "muy",
    "bien", "nota", "notas", "cosa", "cosas", "algo", "nada", "quiere", "quiero",
    "vamos", "ahora", "luego", "antes", "después", "despues", "mismo", "misma",
    "automiq", "agencia", "agente", "agentes", "usuario", "dueño", "dueno",
}
_cache: Dict[str, Any] = {"mtime": None, "notes": [], "df": {}, "n": 0}


def _terms(text: str) -> set:
    return {w for w in _WORD.findall((text or "").lower()) if w not in _STOP}


def _index() -> Dict[str, Any]:
    """Índice en memoria, reconstruido solo cuando cambia brain-graph.json."""
    try:
        mtime = _FILE.stat().st_mtime
    except Exception:
        return {"notes": [], "df": {}, "n": 0}
    if _cache["mtime"] == mtime:
        return _cache
    import json
    try:
        raw = json.loads(_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        log.warning("vault_index_failed", error=str(e)[:120])
        return {"notes": [], "df": {}, "n": 0}
    notes, df = [], {}
    for nd in raw.get("nodes") or []:
        title = nd.get("id") or ""
        excerpt = nd.get("excerpt") or ""
        if not title:
            continue
        # El título de nuestras notas es la mejor señal: viene con fecha y tema
        # (`2026-07-24-Presupuesto-CLAMEVET-Enviado`), por eso pesa el triple.
        t_title = _terms(title.replace("-", " "))
        t_all = t_title | _terms(excerpt)
        if not t_all:
            continue
        notes.append({"id": title, "folder": nd.get("folder") or "",
                      "excerpt": excerpt, "title_terms": t_title, "terms": t_all})
        for t in t_all:
            df[t] = df.get(t, 0) + 1
    _cache.update({"mtime": mtime, "notes": notes, "df": df, "n": len(notes)})
    return _cache


def search(query: str, k: int = 3, min_terms: int = 2) -> List[Dict[str, Any]]:
    """Notas más relevantes para `query`. Exige `min_terms` términos en común —
    con uno solo entraba cualquier nota que compartiera una palabra suelta."""
    idx = _index()
    if not idx["n"]:
        return []
    qt = _terms(query)
    if not qt:
        return []
    df, n = idx["df"], idx["n"]
    scored = []
    for note in idx["notes"]:
        hits = qt & note["terms"]
        if len(hits) < min_terms:
            continue
        score = sum(math.log(1 + n / df.get(t, 1)) for t in hits)
        score += 2 * sum(math.log(1 + n / df.get(t, 1)) for t in qt & note["title_terms"])
        scored.append((score, note))
    scored.sort(key=lambda x: -x[0])
    return [{"id": s[1]["id"], "folder": s[1]["folder"], "excerpt": s[1]["excerpt"],
             "score": round(s[0], 2)} for s in scored[:k]]


def block(query: str, k: int = 3) -> str:
    """Bloque listo para el prompt, o "" si no hay nada relevante (o si el
    cerebro todavía no se sincronizó — el agente sigue funcionando igual)."""
    try:
        hits = search(query, k=k)
    except Exception as e:
        log.warning("vault_search_failed", error=str(e)[:120])
        return ""
    if not hits:
        return ""
    parts = ["## 📚 DE NUESTRA DOCUMENTACIÓN (vault de Obsidian)",
             "Lo que la agencia YA aprendió sobre este tema. Es doctrina propia: "
             "respetala y citala en vez de improvisar. Si la contradecís, decí por qué."]
    for h in hits:
        parts.append(f"### {h['id'].replace('-', ' ')}  ·  _{h['folder']}_\n{h['excerpt']}")
    return "\n".join(parts)
