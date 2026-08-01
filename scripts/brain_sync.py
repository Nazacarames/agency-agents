"""
brain_sync — Fase 3 del OS: el vault de Obsidian conectado al Cerebro del panel.

Corre LOCAL (en la máquina donde vive el vault, NO en Railway). Parsea las notas
del vault (títulos, carpetas top-level y [[wikilinks]]), arma un grafo destilado
liviano y lo POSTea a POST /api/brain/graph del panel. El Brain Explorer del
dashboard lo muestra (notas + dominios + stats). Programado diario vía el Task
Scheduler de Windows (ver brain_sync.bat).

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


def _load_env_file() -> None:
    p = Path(__file__).with_name(".brain_sync_env")
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())


def build_graph() -> dict:
    nodes, edges, domains = [], [], {}
    ids = set()
    notes = [p for p in VAULT.rglob("*.md") if ".obsidian" not in p.parts]
    for p in notes:
        nid = p.stem
        folder = p.relative_to(VAULT).parts[0] if len(p.relative_to(VAULT).parts) > 1 else "(raíz)"
        ids.add(nid)
        nodes.append({"id": nid, "folder": folder})
        domains[folder] = domains.get(folder, 0) + 1
    for p in notes:
        try:
            txt = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for m in LINK_RE.finditer(txt):
            target = m.group(1).strip()
            if target and target != p.stem and target in ids:
                edges.append([p.stem, target])
    return {"ok": True, "nodes": nodes, "edges": edges, "domains": domains,
            "stats": {"notes": len(nodes), "links": len(edges),
                      "folders": len(domains)}}


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
