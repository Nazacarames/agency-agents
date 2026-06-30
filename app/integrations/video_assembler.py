"""
video_assembler — arma un short vertical (1080x1920) uniendo segmentos con ffmpeg.

Pega el clip de Nazareno (Veo, con su voz) + la "prueba" (mockup de chatbot / captura)
en UN solo mp4 listo para postear. Enfoque en 2 pasos (robusto):
  1. Normaliza cada segmento a un mp4 idéntico (1080x1920, 30fps, h264/yuv420p, aac
     estéreo 44.1k; los segmentos de imagen llevan silencio + un leve zoom).
  2. Concatena por demuxer con `-c copy` (rápido, sin recodificar).

Devuelve la URL local `/media/<file>.mp4` (servida por la app) o None si falla.

NOTA: el audio "trending" se suele agregar al subir a TikTok; este armado deja el
corte visual + la voz de Nazareno. Música de fondo opcional (param `music`).
"""
from __future__ import annotations

import subprocess
import uuid
from pathlib import Path
from typing import Dict, List, Optional

from ..log import get_logger

log = get_logger("video_assembler")

W, H, FPS = 1080, 1920, 30
PAD = "0x0D1426"  # navy de marca para las bandas si algo no llena el 9:16

_VF_BASE = (f"scale={W}:{H}:force_original_aspect_ratio=decrease,"
            f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color={PAD},setsar=1,fps={FPS},format=yuv420p")


def _ffmpeg() -> str:
    return "ffmpeg"


def _images_dir() -> Path:
    d = Path(__file__).resolve().parent.parent.parent / "data" / "images"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _run(cmd: List[str]) -> bool:
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=300)
        if r.returncode != 0:
            log.warning("ffmpeg_fail", err=r.stderr.decode("utf-8", "ignore")[-400:])
            return False
        return True
    except Exception as e:
        log.warning("ffmpeg_exc", error=str(e)[:200])
        return False


def _normalize(seg: Dict, idx: int, work: Path) -> Optional[Path]:
    """Normaliza un segmento (video o imagen) a un mp4 estándar."""
    out = work / f"seg_{idx}.mp4"
    path = seg["path"]
    kind = seg.get("kind") or ("video" if str(path).lower().endswith((".mp4", ".webm", ".mov")) else "image")
    if kind == "video":
        cmd = [_ffmpeg(), "-y", "-i", str(path),
               "-vf", _VF_BASE,
               "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
               "-c:a", "aac", "-ar", "44100", "-ac", "2",
               "-af", "aresample=44100", str(out)]
        # si el video no tuviera audio, agregamos uno silencioso
        if not _run(cmd):
            cmd = [_ffmpeg(), "-y", "-i", str(path),
                   "-f", "lavfi", "-t", "8", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
                   "-vf", _VF_BASE, "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                   "-c:a", "aac", "-shortest", str(out)]
            if not _run(cmd):
                return None
        return out
    # imagen: segmento de `dur` seg con leve zoom + silencio
    dur = float(seg.get("dur") or 4.5)
    frames = int(dur * FPS)
    vf = (f"scale={W}:{H}:force_original_aspect_ratio=decrease,"
          f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color={PAD},setsar=1,"
          f"zoompan=z='min(zoom+0.0006,1.10)':d={frames}:s={W}x{H}:fps={FPS},format=yuv420p")
    cmd = [_ffmpeg(), "-y", "-loop", "1", "-t", f"{dur}", "-i", str(path),
           "-f", "lavfi", "-t", f"{dur}", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
           "-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
           "-c:a", "aac", "-ar", "44100", "-ac", "2", "-shortest", str(out)]
    return out if _run(cmd) else None


def assemble(segments: List[Dict], music: Optional[str] = None,
             out_name: Optional[str] = None) -> Optional[str]:
    """Une los segmentos en un mp4 vertical. segments=[{path, kind?, dur?}, ...].

    Devuelve /media/<file>.mp4 o None. `music` = path opcional a un track de fondo.
    """
    segs = [s for s in (segments or []) if s.get("path") and Path(s["path"]).exists()]
    if not segs:
        return None
    work = _images_dir() / f"_work_{uuid.uuid4().hex[:8]}"
    work.mkdir(parents=True, exist_ok=True)
    try:
        norm: List[Path] = []
        for i, s in enumerate(segs):
            p = _normalize(s, i, work)
            if p:
                norm.append(p)
        if not norm:
            return None
        # concat por demuxer
        listfile = work / "list.txt"
        listfile.write_text("".join(f"file '{p.as_posix()}'\n" for p in norm), encoding="utf-8")
        fname = out_name or f"short_{uuid.uuid4().hex}.mp4"
        final = _images_dir() / fname
        concat = [_ffmpeg(), "-y", "-f", "concat", "-safe", "0", "-i", str(listfile)]
        if music and Path(music).exists():
            # mezcla música de fondo (baja) bajo el audio existente
            concat += ["-i", str(music), "-filter_complex",
                       "[0:a]volume=1.0[a0];[1:a]volume=0.18,aloop=loop=-1:size=2e9[a1];"
                       "[a0][a1]amix=inputs=2:duration=first:dropout_transition=2[aout]",
                       "-map", "0:v", "-map", "[aout]",
                       "-c:v", "copy", "-c:a", "aac", "-movflags", "+faststart", str(final)]
        else:
            concat += ["-c", "copy", "-movflags", "+faststart", str(final)]
        if not _run(concat):
            return None
        log.info("video_assembled", file=fname, segs=len(norm))
        return f"/media/{fname}"
    finally:
        # limpiar temporales
        try:
            for f in work.glob("*"):
                f.unlink()
            work.rmdir()
        except Exception:
            pass


def assemble_short(clip_path: str, proof_paths: List[str],
                   proof_dur: float = 5.0, out_name: Optional[str] = None) -> Optional[str]:
    """Atajo: clip de Nazareno (hook) + 1+ pruebas (mockup/captura) como stills."""
    segs: List[Dict] = [{"path": clip_path, "kind": "video"}]
    for p in (proof_paths or []):
        segs.append({"path": p, "kind": "image", "dur": proof_dur})
    return assemble(segs, out_name=out_name)
