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

_DATA = Path(__file__).resolve().parent.parent.parent / "data"
_FILE = _DATA / "brain-graph.json"
# Material creativo/de competencia que hasta ahora se inyectaba ENTERO en el
# prompt de los 4 agentes de contenido (33 mil caracteres, iguales para todos).
# Indexado acá, se sirve por relevancia como el resto del cerebro.
#
# Se pide el texto EFECTIVO a cada módulo en vez de leer el .md: varios traen un
# SEED en código que se usa mientras el archivo del volumen no exista, y leyendo
# solo el archivo un deploy limpio se quedaría sin material.
_MATERIAL = {
    "playbook de competencia": ("competitor_playbook", "load_playbook"),
    "dirección de arte": ("creative_direction", "load"),
    "scout visual (edición/hooks)": ("competitor_playbook", "visual_scout_text"),
    "estudio de reels del competidor": ("reel_study", "digest_text"),
}
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


_MATERIAL_FILES = ("competitor-playbook.md", "creative-direction.md",
                   "visual-scout.md", "reel-study.md")


def _mtimes() -> tuple:
    """Huella de todas las fuentes: si cambia cualquiera, se reindexa."""
    out = []
    for p in [_FILE] + [_DATA / f for f in _MATERIAL_FILES]:
        try:
            out.append(p.stat().st_mtime)
        except Exception:
            out.append(0.0)
    return tuple(out)


def _secciones_md(texto: str, limite: int) -> list:
    """Parte un .md por encabezado y devuelve (título, cuerpo) por sección.

    Mismo criterio que usa brain_sync con el vault, pero acá el archivo vive en
    el volumen de Railway y se refresca por cron, así que se secciona al vuelo."""
    out, titulo, buf = [], "", []
    for linea in texto.splitlines():
        if linea.startswith("#"):
            if buf:
                cuerpo = " ".join(" ".join(buf).split())[:limite]
                if len(cuerpo) >= 60:
                    out.append((titulo, cuerpo))
            titulo, buf = linea.lstrip("# ").strip()[:120], []
        else:
            buf.append(linea.strip())
    if buf:
        cuerpo = " ".join(" ".join(buf).split())[:limite]
        if len(cuerpo) >= 60:
            out.append((titulo, cuerpo))
    return out


def _index() -> Dict[str, Any]:
    """Índice en memoria, reconstruido cuando cambia alguna de sus fuentes."""
    mtime = _mtimes()
    if _cache["mtime"] == mtime:
        return _cache
    import json
    try:
        raw = json.loads(_FILE.read_text(encoding="utf-8"))
    except Exception:
        raw = {}     # sin cerebro todavía: la capa material igual sirve
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
    from importlib import import_module
    for etiqueta, (modulo, fn) in _MATERIAL.items():
        try:
            txt = getattr(import_module(f".{modulo}", __package__), fn)() or ""
        except Exception as e:
            log.warning("material_load_failed", fuente=etiqueta, error=str(e)[:100])
            continue
        for titulo, cuerpo in _secciones_md(txt, 600):
            add("material", f"{etiqueta} {titulo}", cuerpo,
                {"fuente": etiqueta, "titulo": titulo})

    _cache.update({"mtime": mtime, "docs": docs, "df": df, "n": len(docs)})
    log.info("brain_indexed", docs=len(docs),
             material=sum(1 for d in docs if d["layer"] == "material"))
    return _cache


def search(query: str, k: int = 3, layer: str = "", min_terms: int = 0) -> List[Dict[str, Any]]:
    """Pasajes más relevantes. Por defecto exige 2 términos en común: con uno solo
    entraba cualquier cosa que compartiera una palabra suelta.

    La capa `material` es la excepción y pide uno: son decenas de secciones
    curadas, todas del dominio creativo, así que el riesgo no es traer ruido sino
    dejar al agente sin nada."""
    idx = _index()
    if not idx["n"]:
        return []
    if not min_terms:
        min_terms = 1 if layer == "material" else 2
    qt = _terms(query)
    if not qt:
        return []
    df, n = idx["df"], idx["n"]
    scored = []
    # Probado y descartado: aceptar un único término RARO para mejorar el recall.
    # En un corpus chico los términos raros son los accidentes — "milanesas
    # napolitanas" pasaba a devolver resultados. Dos términos o nada.
    for d in idx["docs"]:
        # Sin capa pedida se busca doctrina (vault + código). El material de
        # competencia se pide aparte: si compitiera acá, sus 33 mil caracteres
        # de tácticas taparían las decisiones propias de la agencia.
        if (d["layer"] != layer) if layer else (d["layer"] == "material"):
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
    if layer == "material":
        # Tope de 2 por fuente: el estudio de reels tiene secciones largas y con
        # mucho vocabulario, y se llevaba 3 de los 5 lugares aun para el agente
        # que arma el calendario de posts. Sirve más un pasaje de cada cosa.
        por_fuente, diverso = {}, []
        for s, d in scored:
            f = d["meta"].get("fuente", "")
            if por_fuente.get(f, 0) >= 2:
                continue
            por_fuente[f] = por_fuente.get(f, 0) + 1
            diverso.append((s, d))
        scored = diverso
    return [{"layer": d["layer"], "head": d["head"], "text": d["body"],
             "score": round(s, 2), **d["meta"]} for s, d in scored[:k]]


def block(query: str, k: int = 3, layer: str = "") -> str:
    """Bloque listo para el prompt, o "" si no hay nada relevante (o si el cerebro
    todavía no se sincronizó — el agente sigue corriendo igual)."""
    try:
        hits = search(query, k=k, layer=layer)
    except Exception as e:
        log.warning("brain_search_failed", error=str(e)[:120])
        return ""
    if not hits and layer != "material":
        return ""
    if layer == "material":
        # Piso: si nada matcheó, el agente igual sale con las reglas base. Antes
        # recibía el material entero, así que quedarse en cero sería un retroceso.
        if len(hits) < 2:
            vistos = {h.get("titulo") for h in hits}
            for d in _index()["docs"]:
                if d["layer"] == "material" and d["meta"].get("titulo") not in vistos:
                    hits.append({"layer": "material", "text": d["body"], **d["meta"]})
                    if len(hits) >= 2:
                        break
        parts = ["## 🎯 MATERIAL DE COMPETENCIA APLICABLE A ESTA PIEZA",
                 "Del playbook, la dirección de arte y el estudio de la competencia, esto es "
                 "lo que aplica a lo que estás haciendo hoy. Usalo; lo que no está acá no "
                 "hace falta para esta pieza."]
        if not hits:
            return ""
        for h in hits:
            parts.append(f"### {h.get('fuente')} › {h.get('titulo') or '—'}\n{h['text']}")
        return "\n".join(parts)
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
