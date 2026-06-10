#!/usr/bin/env python3
"""
fetch_leadhunter.py — dispara /run/leadhunter y baja el MD+JSON a data/.

Uso:
  python scripts/fetch_leadhunter.py

Variables de entorno (opcional):
  RENDER_BASE   default: https://automiq-agents.onrender.com
  WEBHOOK_SECRET  default: el de abajo (automiq-*** )
  ASYNC_RUN     default: true   (true=encolar, false=sync y más rápido)
  DATA_DIR      default: <repo>/data

Requiere: requests (pip install requests)
"""
import os
import sys
import json
import time
from pathlib import Path

try:
    import requests
except ImportError:
    print("ERROR: pip install requests", file=sys.stderr)
    sys.exit(2)

BASE = os.environ.get("RENDER_BASE", "https://automiq-agents.onrender.com")
SECRET = os.environ.get("WEBHOOK_SECRET", "automiq-rQbr28IOQOTojWozIlr_jl5xFCRm6zDE11iI")
ASYNC = os.environ.get("ASYNC_RUN", "true").lower() == "true"

REPO = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get("DATA_DIR", REPO / "data"))
DATA.mkdir(exist_ok=True)

HEADERS = {"X-Webhook-Secret": SECRET, "Content-Type": "application/json"}


def healthz() -> dict:
    r = requests.get(f"{BASE}/healthz", timeout=30)
    r.raise_for_status()
    return r.json()


def run_leadhunter() -> str:
    body = {"args": {"force_global": True, "validate_sites": True},
            "async_run": ASYNC}
    r = requests.post(f"{BASE}/run/leadhunter", headers=HEADERS,
                      json=body, timeout=600)
    r.raise_for_status()
    j = r.json()
    print(f"[run] status={j.get('status')} run_id={j.get('run_id')}")
    return j.get("run_id") or "sync"


def last_leadhunter() -> dict:
    r = requests.get(f"{BASE}/last/leadhunter", headers=HEADERS, timeout=60)
    if r.status_code == 404:
        return {"status": "not_found"}
    r.raise_for_status()
    return r.json()


def main() -> int:
    print(f"[config] BASE={BASE} ASYNC={ASYNC} DATA={DATA}")
    h = healthz()
    print(f"[healthz] {h.get('status')} | minimax={h['services'].get('minimax_configured')} "
          f"| discord={h['services'].get('discord_configured')} "
          f"| global_pause={h['services'].get('global_pause')}")
    if h["services"].get("global_pause"):
        print("[warn] global_pause está activo — el run no va a ejecutar", file=sys.stderr)

    run_id = run_leadhunter()

    # Si fue async, esperar hasta 180s con backoff
    if ASYNC:
        for attempt in range(18):
            time.sleep(10)
            j = last_leadhunter()
            if j.get("status") == "ok":
                print(f"[last] listo en {(attempt+1)*10}s")
                break
        else:
            print("[error] timeout esperando el reporte", file=sys.stderr)
            return 1
    else:
        j = last_leadhunter()
        if j.get("status") != "ok":
            print(f"[error] {j}", file=sys.stderr)
            return 1

    date = j.get("date")
    files = j.get("files", {})
    sizes = j.get("sizes", {})
    written = []
    if files.get("report_md"):
        p = DATA / f"leadhunter-report-{date}.md"
        p.write_text(files["report_md"], encoding="utf-8")
        written.append(("md", p, sizes.get("report_md", 0)))
    if files.get("leads_md"):
        p = DATA / f"leadhunter-leads-{date}.md"
        p.write_text(files["leads_md"], encoding="utf-8")
        written.append(("leads_md", p, sizes.get("leads_md", 0)))
    if files.get("leads_json"):
        p = DATA / f"leadhunter-leads-{date}.json"
        p.write_text(files["leads_json"], encoding="utf-8")
        written.append(("json", p, sizes.get("leads_json", 0)))

    print(f"[done] {len(written)} archivos en {DATA} para {date}:")
    for kind, p, size in written:
        print(f"   {kind:8s} {p}  ({size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
