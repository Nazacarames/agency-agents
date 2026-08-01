"""
brain_sync — el Cerebro de Automiq: Obsidian + Graphify combinados en un grafo.

Corre LOCAL (en la máquina donde vive el vault, NO en Railway) y arma UN cerebro
con dos capas:

  · VAULT  — el vault de Obsidian. Graphify lo secciona por encabezado y acá cada
             sección se enriquece con su texto: el agente recibe el pasaje exacto,
             no el arranque de la nota.
  · CÓDIGO — el sistema mismo (app/, packs/, scripts/) según el grafo de Graphify:
             módulos, funciones, docstrings y sus relaciones (calls/imports).

Los dos grafos los une `graphify merge-graphs`; este script los destila a un JSON
liviano y lo POSTea a /api/brain/graph. El Brain Explorer del panel lo dibuja y
`brain_search` lo consulta para inyectarle contexto a TODOS los agentes.

Programado diario vía el Task Scheduler de Windows (ver brain_sync.bat).
Secretos: WEBHOOK_SECRET de la env o de scripts/.brain_sync_env (gitignored).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

VAULT = Path(os.environ.get("VAULT_PATH", r"C:\Users\Administrator\Documents\Obsidian Vault"))
REPO = Path(__file__).resolve().parent.parent
PANEL = os.environ.get("BRAIN_PANEL_URL", "https://automiq-agents-production-e5a4.up.railway.app")
GRAPHIFY = os.environ.get("GRAPHIFY_BIN", str(Path.home() / ".local" / "bin" / "graphify"))

LINK_RE = re.compile(r"\[\[([^\]|#]+)")
FM_RE = re.compile(r"\A---\n.*?\n---\n", re.S)      # frontmatter YAML
MD_RE = re.compile(r"[#>*`_\[\]]|!\[.*?\]\(.*?\)")   # ruido de markdown
EXCERPT_CHARS = 700         # resumen de la nota (lo muestra el panel)
SECTION_CHARS = 400         # pasaje por sección (lo buscan los agentes)
MIN_SECTION = 60            # menos que esto es un índice o un encabezado suelto
CODE_ROOTS = ("app/", "packs/", "scripts/")
MAX_BYTES = 4_500_000
# Carpetas del vault que son BIBLIOTECA DE TERCEROS, no doctrina de la agencia
# (06-Resources son plantillas de agentes bajadas de internet). Se indexan igual
# —a veces sirven— pero marcadas `ref` para que no le ganen a lo propio: sin
# esto, "paid media para distribuidoras" devolvía tres READMEs ajenos y ni un
# solo pasaje nuestro sobre distribuidoras.
REF_FOLDERS = tuple(f.strip() for f in
                    os.environ.get("BRAIN_REF_FOLDERS", "06-Resources").split(",") if f.strip())


# ── Paso 0: lo que aprendieron los agentes vuelve al vault ──

LESSONS_DIR = "07-Knowledge/Lecciones-de-los-Agentes"


def pull_lessons() -> dict:
    """Baja las lecciones de los agentes y las escribe como notas del vault.

    Cierra el círculo: hasta ahora los agentes LEÍAN el vault pero lo que
    aprendían moría en Supabase. Ahora una lección de `media_auditor` sobre un
    formato que funcionó queda documentada y —vía el cerebro— puede llegarle a
    `content_creator` cuando trabaje ese tema.

    Una nota POR AGENTE (no por lección): 239 lecciones sueltas inundarían el
    vault. Van a una carpeta propia y se reescriben enteras en cada corrida, así
    que no pisan nada escrito a mano."""
    secret = os.environ.get("WEBHOOK_SECRET", "")
    if not secret:
        return {}
    req = urllib.request.Request(PANEL.rstrip("/") + "/api/lessons",
                                 headers={"X-Webhook-Secret": secret})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            lessons = json.loads(r.read().decode()).get("lessons", [])
    except Exception as e:
        print(f"  (no se pudieron bajar las lecciones: {str(e)[:80]})")
        return {}
    por_agente: dict[str, list] = {}
    for l in lessons:
        if l.get("active") and (l.get("lesson") or "").strip():
            por_agente.setdefault(l.get("agent") or "sin-agente", []).append(l)
    destino = VAULT / LESSONS_DIR
    destino.mkdir(parents=True, exist_ok=True)
    for agente, ls in por_agente.items():
        ls.sort(key=lambda x: (-(x.get("weight") or 1), x.get("created_at") or ""))
        cuerpo = [f"# Lecciones de {agente.replace('_', ' ')}", "",
                  "> [!info] Generada por `brain_sync` desde las corridas del agente.",
                  "> Se reescribe entera en cada sync — no la edites a mano.", ""]
        for l in ls:
            peso = l.get("weight") or 1
            fecha = (l.get("created_at") or "")[:10]
            refuerzo = f" `×{peso}`" if peso > 1 else ""
            cuerpo.append(f"- {l['lesson'].strip()} —{refuerzo} _{fecha}_")
        cuerpo += ["", "Relacionado: [[MOC-07-Knowledge]] · [[Gotchas-y-Lecciones]]", ""]
        (destino / f"Lecciones-{agente.replace('_', '-')}.md").write_text(
            "\n".join(cuerpo), encoding="utf-8")
    # Índice, para que las notas cuelguen del MOC y no queden huérfanas
    idx = ["# Lecciones de los Agentes", "",
           "Lo que cada agente aprendió de sus propias corridas (`LECCION:` en su "
           "output → memoria → esta carpeta). El número es cuántas veces se reforzó.", ""]
    for agente, ls in sorted(por_agente.items()):
        idx.append(f"- [[Lecciones-{agente.replace('_', '-')}|{agente.replace('_', ' ')}]] "
                   f"— {len(ls)} lecciones")
    idx += ["", "Relacionado: [[MOC-07-Knowledge]]", ""]
    (destino / "Lecciones-de-los-Agentes.md").write_text("\n".join(idx), encoding="utf-8")
    return por_agente


def _lessons_layer(por_agente: dict) -> list:
    """Cada lección es UN pasaje del cerebro.

    No alcanza con escribirlas al vault y dejar que Graphify las seccione: la
    nota de un agente es una lista larga bajo un solo encabezado, y el corte por
    sección se comería todas menos las primeras. Una lección es exactamente una
    unidad de conocimiento, así que va como pasaje propio."""
    out = []
    for agente, ls in por_agente.items():
        for l in ls:
            texto = (l.get("lesson") or "").strip()
            if len(texto) < MIN_SECTION:
                continue
            peso = l.get("weight") or 1
            out.append({"note": f"Lecciones-{agente.replace('_', '-')}",
                        "folder": "07-Knowledge",
                        "title": f"lección de {agente.replace('_', ' ')}"
                                 + (f" (reforzada ×{peso})" if peso > 1 else ""),
                        "text": texto[:SECTION_CHARS]})
    return out


# ── Capa 1: el vault (notas + secciones) ──

def _excerpt(txt: str) -> str:
    body = MD_RE.sub("", FM_RE.sub("", txt))
    return " ".join(body.split())[:EXCERPT_CHARS]


def _notes_layer() -> tuple[list, list, dict, dict]:
    """Notas del vault con su extracto + los [[wikilinks]] entre ellas."""
    nodes, edges, domains, texts = [], [], {}, {}
    ids = set()
    notes = [p for p in VAULT.rglob("*.md") if ".obsidian" not in p.parts]
    for p in notes:
        parts = p.relative_to(VAULT).parts
        folder = parts[0] if len(parts) > 1 else "(raiz)"
        try:
            texts[p] = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            texts[p] = ""
        ids.add(p.stem)
        nd = {"id": p.stem, "folder": folder, "excerpt": _excerpt(texts[p])}
        if folder.startswith(REF_FOLDERS):
            nd["ref"] = True
        nodes.append(nd)
        domains[folder] = domains.get(folder, 0) + 1
    for p in notes:
        for m in LINK_RE.finditer(texts[p]):
            target = m.group(1).strip()
            if target and target != p.stem and target in ids:
                edges.append([p.stem, target])
    return nodes, edges, domains, texts


def _sections_layer(graph: dict) -> list:
    """Secciones del vault (una por encabezado, según Graphify) con SU texto.

    Graphify da el encabezado y la línea donde empieza; el cuerpo lo cortamos
    hasta el encabezado siguiente. Es la unidad que hace útil la búsqueda: una
    nota de 4.000 caracteres deja de verse solo por su arranque."""
    por_archivo: dict[str, list] = {}
    for nd in graph.get("nodes", []):
        if nd.get("repo") != "vault" or nd.get("file_type") != "document":
            continue
        sf = nd.get("source_file") or ""
        if not sf.endswith(".md"):
            continue
        try:
            ln = int((nd.get("source_location") or "L1")[1:])
        except ValueError:
            continue
        por_archivo.setdefault(sf, []).append((ln, nd.get("label") or ""))
    out = []
    for sf, secs in por_archivo.items():
        p = VAULT / sf
        try:
            lines = p.read_text(encoding="utf-8", errors="ignore").splitlines()
        except Exception:
            continue
        secs.sort(key=lambda t: t[0])
        note = Path(sf).stem
        folder = Path(sf).parts[0] if len(Path(sf).parts) > 1 else "(raiz)"
        # El frontmatter YAML cae dentro de la primera sección y la ensucia con
        # `tags:`/`fecha:`; lo salteamos por número de línea (no se puede quitar
        # del texto antes, porque correría los offsets que da Graphify).
        fm_end = 0
        if lines and lines[0].strip() == "---":
            for j, l in enumerate(lines[1:], start=1):
                if l.strip() == "---":
                    fm_end = j + 1
                    break
        for i, (ln, label) in enumerate(secs):
            end = secs[i + 1][0] - 1 if i + 1 < len(secs) else len(lines)
            body = MD_RE.sub("", " ".join(l.strip() for l in lines[max(ln, fm_end):end] if l.strip()))
            body = " ".join(body.split())[:SECTION_CHARS]
            if len(body) >= MIN_SECTION:
                sec = {"note": note, "folder": folder, "title": label[:120], "text": body}
                if folder.startswith(REF_FOLDERS):
                    sec["ref"] = True
                out.append(sec)
    return out


# ── Capa 2: el código (el sistema mismo) ──

def _code_layer(graph: dict) -> tuple[list, list]:
    """Módulos, funciones y docstrings de app/packs/scripts + sus relaciones.

    Se filtra a NUESTRO código: el grafo crudo trae `.claude/` y `vendor/`, que
    son herramientas de terceros y solo agregarían ruido al contexto."""
    keep, nodes = {}, []
    for nd in graph.get("nodes", []):
        if nd.get("repo") != "code":
            continue
        sf = nd.get("source_file") or ""
        if not sf.startswith(CODE_ROOTS):
            continue
        label = (nd.get("label") or "").strip()
        if not label:
            continue
        nid = nd.get("id") or ""
        keep[nid] = True
        nodes.append({"id": nid, "file": sf, "label": label[:200],
                      "kind": nd.get("file_type") or "code"})
    edges = [[l["source"], l["target"], l.get("relation") or ""]
             for l in graph.get("links", [])
             if l.get("source") in keep and l.get("target") in keep
             and l.get("relation") in ("calls", "imports", "imports_from", "inherits")]
    return nodes, edges


# ── Graphify ──

def _run(cmd: list, cwd: Path | None = None) -> None:
    r = subprocess.run(cmd, cwd=str(cwd) if cwd else None,
                       capture_output=True, text=True, timeout=900)
    tail = (r.stdout or r.stderr or "").strip().splitlines()[-1:] or [""]
    print(f"  {' '.join(Path(c).name if i == 0 else c for i, c in enumerate(cmd))[:70]} → {tail[0][:90]}")
    if r.returncode != 0:
        raise RuntimeError(f"graphify falló: {(r.stderr or r.stdout)[-300:]}")


def build_merged_graph(workdir: Path) -> dict:
    """Corre Graphify sobre el vault y sobre el repo, y fusiona los dos grafos.

    El vault se copia a un temporal: correr Graphify adentro dejaría una carpeta
    `graphify-out/` en el vault del dueño (y aparecería como notas basura)."""
    vault_copy = workdir / "vault"
    shutil.copytree(VAULT, vault_copy, ignore=shutil.ignore_patterns(".obsidian", ".git"))
    print("graphify:")
    _run([GRAPHIFY, "update", ".", "--no-cluster"], cwd=vault_copy)
    _run([GRAPHIFY, "update", ".", "--no-cluster"], cwd=REPO)
    merged = workdir / "merged.json"
    _run([GRAPHIFY, "merge-graphs",
          str(vault_copy / "graphify-out" / "graph.json"),
          str(REPO / "graphify-out" / "graph.json"), "--out", str(merged)])
    g = json.loads(merged.read_text(encoding="utf-8"))
    # merge-graphs etiqueta cada nodo con el nombre de la carpeta de origen;
    # lo normalizamos a "vault"/"code" para que el resto no dependa de eso.
    for nd in g.get("nodes", []):
        nd["repo"] = "vault" if nd.get("repo") == vault_copy.name else "code"
    return g


def build_brain(lecciones: dict | None = None) -> dict:
    with tempfile.TemporaryDirectory(prefix="brain-") as tmp:
        merged = build_merged_graph(Path(tmp))
        sections = _sections_layer(merged)
        code_nodes, code_edges = _code_layer(merged)
    # Las notas de lecciones ya entraron por el vault (para que el dueño las vea
    # en Obsidian); acá van además como pasajes sueltos, que es como se buscan.
    sections = [s for s in sections if not s["note"].startswith("Lecciones-")]
    sections += _lessons_layer(lecciones or {})
    nodes, edges, domains, _ = _notes_layer()
    brain = {"ok": True, "nodes": nodes, "edges": edges, "domains": domains,
             "sections": sections, "code": code_nodes, "code_edges": code_edges,
             "stats": {"notes": len(nodes), "links": len(edges),
                       "folders": len(domains), "sections": len(sections),
                       "code_nodes": len(code_nodes), "code_edges": len(code_edges),
                       "ref_sections": sum(1 for s in sections if s.get("ref"))}}
    # Todo esto crece con el repo y con el vault: recortamos los pasajes antes de
    # que el POST muera por tamaño, en vez de perder la sync entera.
    cut = SECTION_CHARS
    while cut > 120 and len(json.dumps(brain)) > MAX_BYTES:
        cut //= 2
        for s in sections:
            s["text"] = s["text"][:cut]
        print(f"payload > {MAX_BYTES//1024} KB → pasajes recortados a {cut} chars")
    return brain


def _load_env_file() -> None:
    p = Path(__file__).with_name(".brain_sync_env")
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())


def push(brain: dict) -> None:
    secret = os.environ.get("WEBHOOK_SECRET", "")
    if not secret:
        sys.exit("Falta WEBHOOK_SECRET (env o scripts/.brain_sync_env)")
    req = urllib.request.Request(
        PANEL.rstrip("/") + "/api/brain/graph",
        data=json.dumps(brain).encode(),
        headers={"Content-Type": "application/json", "X-Webhook-Secret": secret},
        method="POST")
    with urllib.request.urlopen(req, timeout=180) as r:
        print("panel:", r.status, r.read().decode()[:200])


if __name__ == "__main__":
    _load_env_file()
    lecciones = pull_lessons()
    n = sum(len(v) for v in lecciones.values())
    if n:
        print(f"lecciones de los agentes → vault: {n} en {len(lecciones)} notas")
    b = build_brain(lecciones)
    s = b["stats"]
    print(f"cerebro: {s['notes']} notas · {s['sections']} pasajes ({n} son lecciones) · "
          f"{s['code_nodes']} nodos de código · {s['links']}+{s['code_edges']} conexiones "
          f"· {len(json.dumps(b))//1024} KB")
    push(b)
