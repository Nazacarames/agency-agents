"""
launcher_hermes.py — arranca Hermes ACP en background, sin bloquear el shell.

El proceso principal del contenedor (uvicorn) corre en foreground y expone
$PORT. Este launcher corre como subprocess detachado y muere rápido
para no interferir.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PACKS = REPO / "packs"


def setup_hermes_home() -> Path:
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
            except (IsADirectoryError, OSError):
                import shutil
                shutil.rmtree(target, ignore_errors=True)
        if src.exists():
            target.symlink_to(src.resolve())
    return hermes_home


def main() -> int:
    log_dir = REPO / "logs"
    log_dir.mkdir(exist_ok=True)
    log_path = log_dir / "hermes-acp.log"
    hh = setup_hermes_home()
    print(f"[launcher_hermes] hermes_home={hh}, log={log_path}", flush=True)
    # Arrancamos acp_adapter en background (subprocess detachado, no bloquea)
    with open(log_path, "ab", buffering=0) as log_fh:
        try:
            proc = subprocess.Popen(
                [sys.executable, "-m", "acp_adapter.entry"],
                stdin=subprocess.DEVNULL,
                stdout=log_fh,
                stderr=log_fh,
                start_new_session=True,
                env={**os.environ, "HERMES_HOME": str(hh)},
            )
            print(f"[launcher_hermes] hermes pid={proc.pid}", flush=True)
        except Exception as e:
            print(f"[launcher_hermes] failed to start Hermes: {e}", flush=True)
    # No esperamos — uvicorn ya está corriendo en foreground desde el CMD
    return 0


if __name__ == "__main__":
    sys.exit(main())
