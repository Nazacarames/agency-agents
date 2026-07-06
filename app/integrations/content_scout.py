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

import json
import re
import subprocess
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple

from ..log import get_logger

log = get_logger("content_scout")

_DATA = Path(__file__).resolve().parent.parent.parent / "data"
_RADAR_FILE = _DATA / "competitor-radar.json"

# Nicho por cuenta (para etiquetar los ganchos que van al baúl).
_NICHOS = {
    "stevenbartlett": "negocios", "hormozi": "negocios", "codiesanchez": "negocios",
    "garyvee": "negocios", "neuromodernos": "ia", "romualdfons": "marketing",
    "eugeoller": "negocios", "hubspot": "saas/b2b", "manychat": "bots/pymes",
}

_NOTE_PROMPT = (
    "Analizá este reel de un competidor o marca de referencia (mirá el video Y escuchá el "
    "audio). Empezá EXACTAMENTE con estas 2 líneas:\n"
    "HOOK: <lo que se dice/muestra en los primeros 3s; si está en inglés, traducilo a "
    "español rioplatense manteniendo la estructura del gancho>\n"
    "TEXTO EN PANTALLA: <el texto sobreimpreso más importante, o 'ninguno'>\n"
    "Después, en español rioplatense, MUY concreto y breve (~120 palabras): "
    "FORMATO/EDICIÓN (cortes, PiP, texto en pantalla, ritmo, música), DÓNDE "
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


def _parse_note(note: str) -> Tuple[str, str]:
    """Extrae (hook, texto_en_pantalla) de las 2 primeras líneas de la nota de Gemini."""
    hook = screen = ""
    m = re.search(r"^HOOK\s*:\s*(.+)$", note, re.MULTILINE | re.IGNORECASE)
    if m:
        hook = m.group(1).strip().strip('"')
    m = re.search(r"^TEXTO EN PANTALLA\s*:\s*(.+)$", note, re.MULTILINE | re.IGNORECASE)
    if m:
        screen = m.group(1).strip()
        if screen.lower().startswith("ninguno"):
            screen = ""
    return hook, screen


def load_radar() -> Dict:
    """Radar estructurado del espía de competencia (para el panel). {} si no corrió."""
    try:
        return json.loads(_RADAR_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def refresh() -> Dict:
    """Descubre IG → Gemini mira → sintetiza → escribe data/visual-scout.md (playbook)
    + data/competitor-radar.json (espía estructurado: top reels con gancho + likes)
    + guarda los ganchos transcriptos al Baúl. Autónomo (domingo a la mañana)."""
    from . import ig_discovery, vision
    if not enabled():
        return {"ok": False, "reason": "ig_discovery/vision no configurados"}
    work = _DATA / "images" / f"_scout_{uuid.uuid4().hex[:8]}"
    work.mkdir(parents=True, exist_ok=True)
    notes: List[Tuple[str, str]] = []
    radar_accounts: List[Dict] = []
    try:
        for key, handle in ig_discovery.IG_HANDLES.items():
            prof = ig_discovery.profile_media(handle, n=15)
            reels = [m for m in prof.get("media", [])
                     if m.get("media_type") == "VIDEO" and m.get("media_url")]
            if not reels:
                continue
            # top por likes (proxy de vistas: Business Discovery no expone plays)
            reels.sort(key=lambda r: r.get("like_count", 0) or 0, reverse=True)
            acct = {"key": key, "handle": prof.get("username", handle),
                    "followers": prof.get("followers_count", 0),
                    "reels": [{"permalink": r.get("permalink", ""),
                               "caption": (r.get("caption") or "")[:200],
                               "likes": r.get("like_count", 0) or 0,
                               "comments": r.get("comments_count", 0) or 0,
                               "timestamp": r.get("timestamp", "")}
                              for r in reels[:5]]}
            # Gemini MIRA el reel más gustado → nota (playbook) + gancho (radar/baúl)
            mp4 = work / f"{key}.mp4"
            try:
                urllib.request.urlretrieve(reels[0]["media_url"], str(mp4))
            except Exception:
                radar_accounts.append(acct)
                continue
            small = work / f"s_{key}.mp4"
            if _shrink(mp4, small):
                note = vision.describe_video(str(small), _NOTE_PROMPT)
                if note:
                    notes.append((f"IG @{handle}", note))
                    hook, screen = _parse_note(note)
                    if acct["reels"]:
                        acct["reels"][0]["hook"] = hook
                        acct["reels"][0]["screen_text"] = screen
                    if hook:
                        try:
                            from . import hook_vault
                            hook_vault.add(hook, tipo="", nicho=_NICHOS.get(key, "general"),
                                           fuente=f"IG @{acct['handle']}",
                                           permalink=acct["reels"][0].get("permalink", ""),
                                           likes=acct["reels"][0].get("likes", 0))
                        except Exception:
                            pass
            radar_accounts.append(acct)
        if radar_accounts:
            try:
                _RADAR_FILE.write_text(json.dumps(
                    {"updated_at": datetime.now(timezone.utc).isoformat(),
                     "accounts": radar_accounts}, ensure_ascii=False, indent=1),
                    encoding="utf-8")
            except Exception as e:
                log.warning("radar_write_failed", error=str(e)[:150])
        if not notes:
            return {"ok": False, "sources": 0, "radar_accounts": len(radar_accounts)}
        blob = "\n\n".join(f"### {lbl}\n{n}" for lbl, n in notes)
        playbook = vision.synthesize(blob, _SYNTH_PROMPT) or blob
        body = ("=== VISUAL SCOUT — playbook de EDICIÓN / hooks / formato (MIRADO por Gemini, IG autónomo) ===\n"
                "_Auto-destilado de reels reales de IG por el server (semanal). Foco VIDEO._\n\n"
                + playbook.strip() + "\n=== fin visual scout ===\n")
        (_DATA / "visual-scout.md").write_text(body, encoding="utf-8")
        log.info("content_scout_ok", sources=len(notes), chars=len(playbook),
                 radar_accounts=len(radar_accounts))
        return {"ok": True, "sources": len(notes), "chars": len(playbook),
                "radar_accounts": len(radar_accounts)}
    finally:
        try:
            for f in work.glob("*"):
                f.unlink()
            work.rmdir()
        except Exception:
            pass
