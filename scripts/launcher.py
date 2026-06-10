"""
launcher.py — punto de entrada único del contenedor en Render.

Arranca:
1. El ACP server de Hermes en background (proceso Hermes)
2. El gateway FastAPI en foreground (uvicorn) que traduce HTTP → Hermes

Render expone sólo el puerto de FastAPI ($PORT, default 8000).
"""
from __future__ import annotations

import os
import sys
import subprocess
import time
import signal
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PACKS = REPO / "packs"


def _setup_hermes_home() -> Path:
    """Crea ~/.hermes y symlinkea skills/ y tools/ del pack automiq."""
    hermes_home = Path(os.environ.get("HERMES_HOME", "/home/automiq/.hermes"))
    hermes_home.mkdir(parents=True, exist_ok=True)
    (hermes_home / "skills").mkdir(exist_ok=True)
    (hermes_home / "agents").mkdir(exist_ok=True)
    (hermes_home / "memory").mkdir(exist_ok=True)
    # Symlinks: ~/.hermes/skills/automiq -> packs/automiq/skills
    for src, subdir, name in [
        (PACKS / "automiq" / "skills", "skills", "automiq"),
        (PACKS / "automiq" / "agents", "agents", "automiq"),
    ]:
        target = hermes_home / subdir / name
        if target.exists() or target.is_symlink():
            try:
                target.unlink()
            except IsADirectoryError:
                import shutil
                shutil.rmtree(target)
        if src.exists():
            target.symlink_to(src.resolve())
    return hermes_home


def _start_hermes_acp() -> subprocess.Popen:
    """Levanta el ACP server de Hermes como subprocess (stdio)."""
    log_path = REPO / "logs" / "hermes-acp.log"
    log_path.parent.mkdir(exist_ok=True)
    log_fh = open(log_path, "ab", buffering=0)
    proc = subprocess.Popen(
        [sys.executable, "-m", "acp_adapter.entry"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=log_fh,
        env={**os.environ, "HERMES_HOME": str(_setup_hermes_home())},
    )
    return proc


def _start_fastapi():
    """Arranca uvicorn en foreground (Render espera este proceso)."""
    port = os.environ.get("PORT", "8000")
    cmd = [
        sys.executable, "-m", "uvicorn",
        "app.main:app",
        "--host", "0.0.0.0",
        "--port", port,
        "--workers", "1",
    ]
    os.execvp(cmd[0], cmd)


def main() -> int:
    print(f"[launcher] repo={REPO} hermes_home={_setup_hermes_home()}")
    hermes_proc = _start_hermes_acp()
    print(f"[launcher] Hermes ACP server started, pid={hermes_proc.pid}")

    def _shutdown(*_):
        print("[launcher] shutting down Hermes...")
        try:
            hermes_proc.terminate()
            hermes_proc.wait(timeout=5)
        except Exception:
            hermes_proc.kill()
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    # Pequeño warmup para que Hermes termine de registrar skills
    time.sleep(2)

    print("[launcher] starting FastAPI gateway...")
    _start_fastapi()
    return 0


if __name__ == "__main__":
    sys.exit(main())
