"""
content_scout — "aprendizaje constante" AUTÓNOMO en prod (IG-only). Descubre reels
recientes de competidores/marcas de referencia vía Business Discovery, **Gemini mira
cada video nativo (con audio)** y sintetiza el playbook de edición/hooks → data/visual-scout.md.

Corre en el SERVER (Railway): la Business Discovery API y Gemini NO se bloquean por IP
de datacenter (a diferencia de yt-dlp). El scout completo con TikTok/YouTube va por el
script local `scripts/scout_watch.py` (IP residencial). Ambos escriben el mismo playbook.

Best-effort: si falta config o falla, no toca el archivo (queda el SEED / lo anterior).
"""
from __future__ import annotations

import subprocess
import urllib.request
import uuid
from pathlib import Path
from typing import Dict, List, Tuple

from ..log import get_logger

log = get_logger("content_scout")

_DATA = Path(__file__).resolve().parent.parent.parent / "data"

_NOTE_PROMPT = (
    "Analizá este reel de un competidor o marca de referencia (mirá el video Y escuchá el "
    "audio). En español rioplatense, MUY concreto y breve (~120 palabras): HOOK exacto "
    "(primeros 3s), FORMATO/EDICIÓN (cortes, PiP, texto en pantalla, ritmo, música), DÓNDE "
    "va la demo del producto, y QUÉ ROBAR para TikToks de bots de WhatsApp para PyMEs "
    "argentinas. Nada genérico: citá lo que ves y oís."
)
_SYNTH_PROMPT = (
    "Sos director de contenido de una agencia argentina (TikToks/Reels sobre IA y bots de "
    "WhatsApp para PyMEs). Abajo hay notas de análisis de reels REALES. Sintetizalas en UN "
    "playbook accionable en español rioplatense, con estas secciones EXACTAS:\n"
    "## Regla madre (variar formato, orgánico)\n## Dónde va la demo del bot\n"
    "## Hooks (con ejemplos concretos)\n## Edición que se siente orgánica\n"
    "## Imágenes/banners para ads\nCitá ejemplos concretos. Máx ~380 palabras. NOTAS:"
)


def enabled() -> bool:
    try:
        from . import ig_discovery, vision
        return ig_discovery.enabled() and vision.enabled()
    except Exception:
        return False


def _shrink(src: Path, dst: Path) -> bool:
    """Achica el video para caber inline en Gemini (<~18MB): 480p, 45s, con audio."""
    try:
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-t", "45", "-i", str(src),
                        "-vf", "scale=-2:480", "-c:v", "libx264", "-crf", "30",
                        "-preset", "veryfast", "-c:a", "aac", "-b:a", "64k", str(dst)],
                       capture_output=True, timeout=180)
    except Exception as e:
        log.warning("scout_shrink_failed", error=str(e)[:150])
        return False
    return dst.exists() and dst.stat().st_size < 18 * 1024 * 1024


def refresh() -> Dict:
    """Descubre IG → Gemini mira → sintetiza → escribe data/visual-scout.md. Autónomo."""
    from . import ig_discovery, vision
    if not enabled():
        return {"ok": False, "reason": "ig_discovery/vision no configurados"}
    work = _DATA / "images" / f"_scout_{uuid.uuid4().hex[:8]}"
    work.mkdir(parents=True, exist_ok=True)
    notes: List[Tuple[str, str]] = []
    try:
        for key, handle in ig_discovery.IG_HANDLES.items():
            reels = ig_discovery.recent_reels(handle, n=15)
            if not reels:
                continue
            mp4 = work / f"{key}.mp4"
            try:
                urllib.request.urlretrieve(reels[0]["media_url"], str(mp4))
            except Exception:
                continue
            small = work / f"s_{key}.mp4"
            if not _shrink(mp4, small):
                continue
            note = vision.describe_video(str(small), _NOTE_PROMPT)
            if note:
                notes.append((f"IG @{handle}", note))
        if not notes:
            return {"ok": False, "sources": 0}
        blob = "\n\n".join(f"### {lbl}\n{n}" for lbl, n in notes)
        playbook = vision.synthesize(blob, _SYNTH_PROMPT) or blob
        body = ("=== VISUAL SCOUT — playbook de EDICIÓN / hooks / formato (MIRADO por Gemini, IG autónomo) ===\n"
                "_Auto-destilado de reels reales de IG por el server (semanal). Foco VIDEO._\n\n"
                + playbook.strip() + "\n=== fin visual scout ===\n")
        (_DATA / "visual-scout.md").write_text(body, encoding="utf-8")
        log.info("content_scout_ok", sources=len(notes), chars=len(playbook))
        return {"ok": True, "sources": len(notes), "chars": len(playbook)}
    finally:
        try:
            for f in work.glob("*"):
                f.unlink()
            work.rmdir()
        except Exception:
            pass
