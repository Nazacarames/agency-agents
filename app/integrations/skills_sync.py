"""
skills_sync — publica las skills curadas del repo (`.claude/skills`) en el HOME
de Hermes, que es el harness PRINCIPAL de todos los agentes desde 2026-07-14.

Por qué existe (diagnosticado 2026-07-20): Hermes descubre skills en
`$HERMES_HOME/skills` y corre con `--ignore-user-config`, así que NUNCA ve
`/root/.claude/skills` — que es donde el Dockerfile deja las nuestras para
Claude Code y OpenCode. Resultado: desde que Hermes pasó a ser el harness
principal, las 37 skills curadas eran letra muerta para TODOS los agentes.
Se veía en los reportes de producción, p.ej. tiktok_creator:
    "[SKILL FAIL: reels-scripting y hook-generator — no registradas en el entorno]"

El REPO MANDA: en cada arranque se re-copian encima. Si Hermes editó una skill
nuestra durante su ciclo de aprendizaje, la versión del repo la pisa (regla
vigente: las skills viven en el repo, no locales). Las skills que Hermes
aprendió por su cuenta (nombres que NO existen en el repo) no se tocan jamás.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Dict, List, Optional

from ..log import get_logger

log = get_logger("skills_sync")

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _source_dir() -> Optional[Path]:
    """Dónde están las skills curadas.

    En dev/local es el repo. En el container el Dockerfile las deja SOLO en
    `/root/.claude/skills` (`COPY .claude/ /root/.claude/`), no en /app — por eso
    el fallback al HOME no es opcional.
    """
    for cand in (_REPO_ROOT / ".claude" / "skills",
                 Path(os.environ.get("HOME", "/root")) / ".claude" / "skills"):
        if cand.is_dir():
            return cand
    return None


def _dest_dir() -> Path:
    """El skills/ de Hermes. Se importa de hermes.py para no duplicar el path:
    si allá cambia el HOME, esto lo sigue solo."""
    from ..clients.hermes import _HERMES_HOME
    return _HERMES_HOME / "skills"


def sync() -> Dict[str, object]:
    """Copia las skills del repo al home de Hermes. Best-effort: nunca lanza."""
    src = _source_dir()
    if src is None:
        log.warning("skills_sync_sin_origen")
        return {"ok": False, "error": "no encontré .claude/skills"}

    dest = _dest_dir()
    copiadas: List[str] = []
    fallidas: List[str] = []
    try:
        dest.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        log.warning("skills_sync_dest_no_creable", error=str(e)[:120])
        return {"ok": False, "error": str(e)[:120]}

    for skill in sorted(p for p in src.iterdir() if p.is_dir()):
        if not (skill / "SKILL.md").is_file():
            continue  # sin SKILL.md no es una skill: Hermes la ignoraría igual
        try:
            shutil.copytree(skill, dest / skill.name, dirs_exist_ok=True)
            copiadas.append(skill.name)
        except Exception as e:
            fallidas.append(skill.name)
            log.warning("skills_sync_skill_fallo", skill=skill.name, error=str(e)[:120])

    # Las que Hermes aprendió solo: quedan intactas, solo se cuentan para el log.
    try:
        propias = [p.name for p in dest.iterdir()
                   if p.is_dir() and p.name not in copiadas]
    except Exception:
        propias = []

    log.info("skills_sync_ok", copiadas=len(copiadas), fallidas=len(fallidas),
             aprendidas=len(propias), origen=str(src), destino=str(dest))
    return {"ok": True, "copiadas": len(copiadas), "fallidas": fallidas,
            "aprendidas": len(propias), "origen": str(src), "destino": str(dest),
            "skills": copiadas}
