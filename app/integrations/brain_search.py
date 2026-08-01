"""
brain_search — los agentes consultan el Cerebro (Obsidian + Graphify combinados).

`data/brain-graph.json` (lo sube scripts/brain_sync.py desde la máquina del dueño)
trae dos capas:

  · VAULT  — pasajes del vault de Obsidian, uno por sección de nota. Es la
             doctrina de la agencia: qué decidimos, qué cobramos, qué falló.
  · CÓDIGO — módulos, funciones y docstrings del sistema (app/, packs/, scripts/)
             según el grafo de Graphify. Es cómo está construido lo que operamos.

Dado el tema de una corrida devuelve los pasajes relevantes de ambas para
inyectarlos al prompt. Sin dependencias ni índice en disco: se arma en memoria y
se cachea hasta que el archivo cambia.
"""
from __future__ import annotations

import math
import re
import unicodedata
from pathlib import Path
from typing import Any, Dict, List

from ..log import get_logger

log = get_logger("brain_search")

_FILE = Path(__file__).resolve().parent.parent.parent / "data" / "brain-graph.json"
_WORD = re.compile(r"[a-záéíóúüñ0-9]{4,}")
# Ruido del español + palabras que aparecen en CASI todo lo nuestro (agencia,
# agente, automiq…): sin filtrarlas, cualquier consulta matchea con todo.
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
REF_PENALTY = 0.35   # cuánto pesa la biblioteca de terceros frente a lo propio
_cache: Dict[str, Any] = {"mtime": None, "docs": [], "df": {}, "n": 0}


def _terms(text: str) -> set:
    # Sin plegar los acentos, "cámara" y "camara" son términos distintos y la
    # mitad de las búsquedas falla en silencio: la doctrina está escrita con
    # tildes y las consultas casi nunca las llevan.
    plano = "".join(c for c in unicodedata.normalize("NFD", (text or "").lower())
                    if unicodedata.category(c) != "Mn")
    return {w for w in _WORD.findall(plano) if w not in _STOP}


def _index() -> Dict[str, Any]:
    """Índice en memoria, reconstruido solo cuando cambia brain-graph.json."""
    try:
        mtime = _FILE.stat().st_mtime
    except Exception:
        return {"docs": [], "df": {}, "n": 0}
    if _cache["mtime"] == mtime:
        return _cache
    import json
    try:
        raw = json.loads(_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        log.warning("brain_index_failed", error=str(e)[:120])
        return {"docs": [], "df": {}, "n": 0}
    docs, df = [], {}

    def add(layer: str, head: str, body: str, meta: dict, ref: bool = False) -> None:
        # El encabezado (título de nota/sección, o la firma de la función) es la
        # señal más fuerte, por eso se puntúa aparte y pesa el doble.
        t_head, t_body = _terms(head), _terms(body)
        if not (t_head or t_body):
            return
        docs.append({"layer": layer, "head": head, "body": body, "meta": meta,
                     "head_terms": t_head, "terms": t_head | t_body, "ref": ref})
        for t in t_head | t_body:
            df[t] = df.get(t, 0) + 1

    for s in raw.get("sections") or []:
        note = s.get("note") or ""
        add("vault", f"{note} {s.get('title') or ''}".replace("-", " "),
            s.get("text") or "", {"note": note, "folder": s.get("folder") or "",
                                  "title": s.get("title") or ""}, bool(s.get("ref")))
    # Notas sin secciones (una nota corta, sin encabezados) igual tienen que ser
    # encontrables: caen por su extracto.
    con_sec = {(s.get("note") or "") for s in raw.get("sections") or []}
    for nd in raw.get("nodes") or []:
        if nd.get("id") in con_sec or not nd.get("excerpt"):
            continue
        add("vault", (nd.get("id") or "").replace("-", " "), nd["excerpt"],
            {"note": nd.get("id") or "", "folder": nd.get("folder") or "", "title": ""},
            bool(nd.get("ref")))
    for c in raw.get("code") or []:
        add("code", c.get("label") or "", c.get("file") or "",
            {"file": c.get("file") or "", "kind": c.get("kind") or ""})

    _cache.update({"mtime": mtime, "docs": docs, "df": df, "n": len(docs)})
    log.info("brain_indexed", docs=len(docs))
    return _cache


def search(query: str, k: int = 3, layer: str = "", min_terms: int = 2) -> List[Dict[str, Any]]:
    """Pasajes más relevantes. Exige `min_terms` términos en común: con uno solo
    entraba cualquier cosa que compartiera una palabra suelta."""
    idx = _index()
    if not idx["n"]:
        return []
    qt = _terms(query)
    if not qt:
        return []
    df, n = idx["df"], idx["n"]
    scored = []
    for d in idx["docs"]:
        if layer and d["layer"] != layer:
            continue
        hits = qt & d["terms"]
        if len(hits) < min_terms:
            continue
        score = sum(math.log(1 + n / df.get(t, 1)) for t in hits)
        score += sum(math.log(1 + n / df.get(t, 1)) for t in qt & d["head_terms"])
        # Material de terceros (biblioteca de plantillas) por debajo de lo propio:
        # aparece cuando no tenemos doctrina del tema, no en lugar de ella.
        if d.get("ref"):
            score *= REF_PENALTY
        scored.append((score, d))
    scored.sort(key=lambda x: -x[0])
    return [{"layer": d["layer"], "head": d["head"], "text": d["body"],
             "score": round(s, 2), **d["meta"]} for s, d in scored[:k]]


def block(query: str, k: int = 3) -> str:
    """Bloque listo para el prompt, o "" si no hay nada relevante (o si el cerebro
    todavía no se sincronizó — el agente sigue corriendo igual)."""
    try:
        hits = search(query, k=k)
    except Exception as e:
        log.warning("brain_search_failed", error=str(e)[:120])
        return ""
    if not hits:
        return ""
    parts = ["## 🧠 DEL CEREBRO DE LA EMPRESA (Obsidian + código)",
             "Lo que la agencia YA sabe sobre este tema. Es doctrina propia: "
             "respetala y citala en vez de improvisar. Si la contradecís, decí por qué."]
    for h in hits:
        if h["layer"] == "code":
            parts.append(f"### ⚙️ `{h.get('file')}` · {h['head']}")
        else:
            src = h.get("note") or ""
            tit = f" › {h['title']}" if h.get("title") else ""
            parts.append(f"### 📄 {src.replace('-', ' ')}{tit}  ·  _{h.get('folder')}_\n{h['text']}")
    return "\n".join(parts)
