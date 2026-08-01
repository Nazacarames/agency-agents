"""
brain_sync — Fase 3 del OS: el vault de Obsidian conectado al Cerebro del panel.

Corre LOCAL (en la máquina donde vive el vault, NO en Railway). Parsea las notas
del vault (títulos, carpetas top-level, [[wikilinks]] y un EXTRACTO del cuerpo),
arma un grafo destilado liviano y lo POSTea a POST /api/brain/graph del panel. El
Brain Explorer del dashboard lo muestra (notas + dominios + stats) y
`vault_search` lo usa para que los agentes citen nuestra propia documentación.
Programado diario vía el Task Scheduler de Windows (ver brain_sync.bat).

Secretos: lee WEBHOOK_SECRET de la env o de scripts/.brain_sync_env (gitignored,
formato KEY=VALUE por línea). Nunca en el repo.
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.request
from pathlib import Path

VAULT = Path(os.environ.get("VAULT_PATH", r"C:\Users\Administrator\Documents\Obsidian Vault"))
PANEL = os.environ.get("BRAIN_PANEL_URL", "https://automiq-agents-production-e5a4.up.railway.app")
LINK_RE = re.compile(r"\[\[([^\]|#]+)")
FM_RE = re.compile(r"\A---\n.*?\n---\n", re.S)     # frontmatter YAML
MD_RE = re.compile(r"[#>*`_\[\]]|!\[.*?\]\(.*?\)")  # ruido de markdown
EXCERPT_CHARS = 700
MAX_BYTES = 1_800_000                               # el endpoint corta en 2 MB


def _excerpt(txt: str) -> str:
    """Primeras líneas útiles de la nota, sin frontmatter ni sintaxis markdown.
    Es lo que después buscan los agentes vía vault_search."""
    body = FM_RE.sub("", txt)
    body = MD_RE.sub("", body)
    return " ".join(body.split())[:EXCERPT_CHARS]


def _load_env_file() -> None:
    p = Path(__file__).with_name(".brain_sync_env")
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())


def build_graph() -> dict:
    nodes, edges, domains, texts = [], [], {}, {}
    ids = set()
    notes = [p for p in VAULT.rglob("*.md") if ".obsidian" not in p.parts]
    for p in notes:
        nid = p.stem
        folder = p.relative_to(VAULT).parts[0] if len(p.relative_to(VAULT).parts) > 1 else "(raíz)"
        try:
            texts[p] = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            texts[p] = ""
        ids.add(nid)
        nodes.append({"id": nid, "folder": folder, "excerpt": _excerpt(texts[p])})
        domains[folder] = domains.get(folder, 0) + 1
    for p in notes:
        for m in LINK_RE.finditer(texts[p]):
            target = m.group(1).strip()
            if target and target != p.stem and target in ids:
                edges.append([p.stem, target])
    graph = {"ok": True, "nodes": nodes, "edges": edges, "domains": domains,
             "stats": {"notes": len(nodes), "links": len(edges),
                       "folders": len(domains)}}
    # El vault crece: si los extractos empujan el payload contra el tope del
    # endpoint, los recortamos antes de que el POST muera con un 413.
    cut = EXCERPT_CHARS
    while cut > 120 and len(json.dumps(graph)) > MAX_BYTES:
        cut //= 2
        for nd in nodes:
            nd["excerpt"] = nd["excerpt"][:cut]
        print(f"payload > {MAX_BYTES} bytes → extractos recortados a {cut} chars")
    return graph


def push(graph: dict) -> None:
    secret = os.environ.get("WEBHOOK_SECRET", "")
    if not secret:
        sys.exit("Falta WEBHOOK_SECRET (env o scripts/.brain_sync_env)")
    req = urllib.request.Request(
        PANEL.rstrip("/") + "/api/brain/graph",
        data=json.dumps(graph).encode(),
        headers={"Content-Type": "application/json", "X-Webhook-Secret": secret},
        method="POST")
    with urllib.request.urlopen(req, timeout=60) as r:
        print("panel:", r.status, r.read().decode()[:200])


if __name__ == "__main__":
    _load_env_file()
    g = build_graph()
    print(f"vault: {g['stats']['notes']} notas · {g['stats']['links']} links · "
          f"{g['stats']['folders']} carpetas")
    push(g)
