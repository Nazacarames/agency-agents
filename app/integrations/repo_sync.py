"""
Sync best-effort hacia el repo remoto (push de artefactos de data/).

Diseñado para ser invocado desde post_process de un agente después de
escribir los archivos en disco. Si la operación falla por cualquier
motivo (sin red, sin credenciales, push rechazado, etc.), la función
retorna sin lanzar excepción — el archivo queda en disco y el run sigue.

Estrategia:
1. `git add` de los archivos explícitamente pasados.
2. `git commit -m` con el mensaje provisto. Si no hay nada para commitear
   (working tree limpio), no falla.
3. `git push origin <rama>` con timeout corto. Si falla, se loguea y listo.

Requisitos en el contenedor:
- git instalado (Render ya lo trae)
- Remote `origin` con credenciales válidas. Render inyecta un token
  automáticamente para deploys; si el push falla, se loguea el motivo.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Iterable

from ..log import get_logger

log = get_logger("repo_sync")


def _run(cmd: list[str], cwd: str, timeout: int = 30) -> tuple[int, str, str]:
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        return 124, "", f"timeout after {timeout}s"
    except Exception as e:
        return 1, "", str(e)


def push_data_files(files: Iterable[Path], commit_message: str) -> bool:
    """Hace `git add` + `commit` + `push` de los archivos dados.

    Devuelve True si el push tuvo éxito, False en cualquier otro caso
    (incluyendo "nothing to commit" — que se considera éxito no-op).
    """
    files = [Path(f) for f in files]
    files = [f for f in files if f.exists()]
    if not files:
        log.info("repo_sync_no_files")
        return True

    # Resolver el repo root (subimos hasta encontrar .git)
    cwd = Path(files[0]).resolve().parent
    repo_root = None
    for parent in [cwd, *cwd.parents]:
        if (parent / ".git").exists():
            repo_root = parent
            break
    if repo_root is None:
        log.warning("repo_sync_no_git_root", start=str(cwd))
        return False

    branch = os.environ.get("GIT_BRANCH", "main")

    # git add explícito de los archivos (no hace git add . para no tocar basura).
    # Si los archivos están en .gitignore (como data/leadhunter-*.md), git add
    # va a rechazarlos: en ese caso los dejamos en disco y tratamos como
    # "nothing to commit" — el run no debe romperse por el sync del repo.
    rel_files = [str(f.relative_to(repo_root)).replace(os.sep, "/") for f in files]
    rc, out, err = _run(["git", "add", "--"] + rel_files, cwd=str(repo_root))
    if rc != 0:
        combined = (out + " " + err).lower()
        if "ignored by one of your .gitignore files" in combined:
            log.info("repo_sync_files_ignored", files=rel_files)
            return True
        log.warning("repo_sync_git_add_failed", rc=rc, stderr=err[:500])
        return False

    # git commit (puede no haber nada que commitear)
    rc, out, err = _run(
        ["git", "commit", "-m", commit_message],
        cwd=str(repo_root),
        timeout=30,
    )
    if rc != 0:
        msg = (out + " " + err).lower()
        if "nothing to commit" in msg or "no changes added" in msg:
            log.info("repo_sync_nothing_to_commit", files=rel_files)
            return True
        log.warning("repo_sync_git_commit_failed", rc=rc, stderr=err[:500])
        return False

    # git push
    rc, out, err = _run(
        ["git", "push", "origin", branch],
        cwd=str(repo_root),
        timeout=60,
    )
    if rc != 0:
        log.warning("repo_sync_git_push_failed", rc=rc, stderr=err[:500])
        return False

    log.info("repo_sync_pushed", branch=branch, files=rel_files)
    return True
