"""
creative_learnings — el LAZO DE RETROALIMENTACIÓN creativo del sistema.

Todo lo que se APRENDE mirando el output propio y los estudios se persiste acá
como lecciones cortas y accionables, y se REINYECTA donde se crea:
- Escriben: el QA de Gemini sobre nuestras imágenes (image_gen), el QA de Gemini
  sobre nuestros shorts (tiktok_creator) y el estudio de reels del competidor
  (reel_study, su "Lección de edición").
- Leen: image_prompt.refine() (cada imagen nueva sale con las lecciones aplicadas)
  y competitor_playbook.playbook_block() (los agentes de contenido las ven).

Store JSON en el volume (data/creative-learnings.json), dedup por texto
normalizado, capado a las últimas _MAX. Best-effort: sin lecciones → "".
"""
from __future__ import annotations

import json
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from ..log import get_logger
from .jsonstore import write_json_atomic

log = get_logger("creative_learnings")

_FILE = Path(__file__).resolve().parent.parent.parent / "data" / "creative-learnings.json"
_MAX = 60          # lecciones que se retienen (las más nuevas)
_MIN_LEN = 12      # menos que esto no es una lección, es ruido


def _load() -> List[dict]:
    try:
        items = json.loads(_FILE.read_text(encoding="utf-8"))
        return items if isinstance(items, list) else []
    except Exception:
        return []


def _norm(t: str) -> str:
    t = unicodedata.normalize("NFKD", (t or "").lower())
    return "".join(c for c in t if c.isalnum() or c.isspace()).strip()


def add(leccion: str, fuente: str, aplica: str = "imagen") -> bool:
    """Guarda una lección (aplica: 'imagen' | 'video'). False si es ruido o duplicada."""
    leccion = (leccion or "").strip().strip("-•* ").strip()
    if len(leccion) < _MIN_LEN:
        return False
    items = _load()
    key = _norm(leccion)
    if any(_norm(i.get("leccion", "")) == key for i in items):
        return False
    items.append({
        "fecha": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "fuente": fuente,
        "aplica": aplica if aplica in ("imagen", "video") else "imagen",
        "leccion": leccion[:300],
    })
    try:
        write_json_atomic(_FILE, items[-_MAX:])
        log.info("learning_added", fuente=fuente, aplica=aplica, chars=len(leccion))
        return True
    except Exception as e:
        log.warning("learning_save_failed", error=str(e)[:150])
        return False


def block(aplica: Optional[str] = None, n: int = 10) -> str:
    """Bloque para inyectar en prompts. '' si no hay lecciones."""
    items = [i for i in _load() if not aplica or i.get("aplica") == aplica]
    if not items:
        return ""
    lines = [f"- ({i['fecha']}, {i['fuente']}) {i['leccion']}" for i in items[-n:]]
    titulo = {"imagen": "LECCIONES APRENDIDAS DE NUESTRAS IMÁGENES (QA real — aplicalas)",
              "video": "LECCIONES APRENDIDAS DE NUESTROS VIDEOS (QA real — aplicalas)"}.get(
        aplica or "", "LECCIONES APRENDIDAS DEL QA DE NUESTRO CONTENIDO (aplicalas)")
    return f"\n\n=== {titulo} ===\n" + "\n".join(lines) + "\n=== fin lecciones ===\n"
