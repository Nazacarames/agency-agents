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

# El container de Railway tiene poca RAM: x264 a 1080x1920 con defaults muere
# OOM-killed (síntoma: stderr cortado con frame=0 repetido, sin error). Encoder
# frugal (threads/lookahead/refs mínimos) y, si 1080p igual falla, fallback a 720p.
_X264_LOWMEM = ["-threads", "2", "-x264-params", "rc-lookahead=12:ref=1:threads=2"]
_SIZES = [(1080, 1920), (720, 1280)]


def _vf(w: int, h: int) -> str:
    return (f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
            f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color={PAD},setsar=1,fps={FPS},format=yuv420p")


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
            # returncode -9 = SIGKILL (OOM del container) → probar tamaño menor
            log.warning("ffmpeg_fail", returncode=r.returncode,
                        err=r.stderr.decode("utf-8", "ignore")[-400:])
            return False
        return True
    except Exception as e:
        log.warning("ffmpeg_exc", error=str(e)[:200])
        return False


def _normalize(seg: Dict, idx: int, work: Path, w: int, h: int) -> Optional[Path]:
    """Normaliza un segmento (video o imagen) a un mp4 estándar de w x h.
    El tamaño lo decide `assemble` para TODO el lote (mezclar resoluciones
    rompería el concat con -c copy)."""
    path = seg["path"]
    kind = seg.get("kind") or ("video" if str(path).lower().endswith((".mp4", ".webm", ".mov")) else "image")
    out = work / f"seg_{idx}_{h}.mp4"
    if kind == "video":
        cmd = [_ffmpeg(), "-y", "-i", str(path),
               "-vf", _vf(w, h),
               "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", *_X264_LOWMEM,
               "-c:a", "aac", "-ar", "44100", "-ac", "2",
               "-af", "aresample=44100", str(out)]
        if _run(cmd):
            return out
        # si el video no tuviera audio, agregamos uno silencioso
        cmd = [_ffmpeg(), "-y", "-i", str(path),
               "-f", "lavfi", "-t", "8", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
               "-vf", _vf(w, h), "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
               *_X264_LOWMEM, "-c:a", "aac", "-shortest", str(out)]
        return out if _run(cmd) else None
    # imagen: segmento de `dur` seg + silencio. Con zoom (Ken Burns) para stills
    # sueltos; SIN zoom (seg["zoom"]=False) para frames de una animación (p.ej. el
    # chat que va llegando mensaje a mensaje) — el zoom reiniciado por frame marea.
    dur = float(seg.get("dur") or 4.5)
    if seg.get("zoom", True):
        frames = int(dur * FPS)
        vf = (f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
              f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color={PAD},setsar=1,"
              f"zoompan=z='min(zoom+0.0006,1.10)':d={frames}:s={w}x{h}:fps={FPS},format=yuv420p")
    else:
        vf = _vf(w, h)
    cmd = [_ffmpeg(), "-y", "-loop", "1", "-t", f"{dur}", "-i", str(path),
           "-f", "lavfi", "-t", f"{dur}", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
           "-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
           *_X264_LOWMEM, "-c:a", "aac", "-ar", "44100", "-ac", "2", "-shortest", str(out)]
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
        # Tamaño por LOTE: si algún segmento no encodea a 1080p (RAM), se rehace
        # TODO a 720p (mezclar resoluciones rompe el concat con -c copy).
        norm: List[Path] = []
        for w, h in _SIZES:
            norm = []
            for i, s in enumerate(segs):
                p = _normalize(s, i, work, w, h)
                if not p:
                    log.warning("assemble_size_failed", size=f"{w}x{h}", seg=i)
                    norm = []
                    break
                norm.append(p)
            if norm:
                break
        if not norm:
            log.warning("assemble_no_segments", tried=[f"{w}x{h}" for w, h in _SIZES])
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


def assemble_short_animated(clip_path: str, frame_paths: List[str],
                            out_name: Optional[str] = None) -> Optional[str]:
    """Clip de Nazareno + demo de chat ANIMADA: cada frame es el chat con un
    mensaje más (o el "escribiendo…"), cortados en secuencia → se ve el mensaje
    enviándose y llegando. Sin zoom (los frames deben quedar clavados)."""
    segs: List[Dict] = [{"path": clip_path, "kind": "video"}]
    n = len(frame_paths or [])
    for i, p in enumerate(frame_paths or []):
        is_typing = "typing" in Path(p).stem
        last = (i == n - 1)
        dur = 0.8 if is_typing else (2.6 if last else 1.3)
        segs.append({"path": p, "kind": "image", "dur": dur, "zoom": False})
    return assemble(segs, out_name=out_name)


def _split_filter(w: int, h: int) -> str:
    """filter_complex del layout SPLIT: Nazareno arriba (con su voz) + demo del bot
    abajo, ambos a la vez. La base temporal es el clip de Nazareno (dura su audio);
    la demo se congela en el último frame (tpad clone) hasta que él termina."""
    top_h = (int(h * 0.545) // 2) * 2      # ~55% para Nazareno
    bot_h = h - top_h
    navy = f"0x{PAD[2:]}" if PAD.startswith("0x") else PAD
    return (
        # Nazareno: crop centrado a proporción w:top_h, escalado arriba; navy debajo.
        f"[0:v]crop=1080:1040:0:(ih-1040)/2,scale={w}:{top_h},setsar=1,"
        f"pad={w}:{h}:0:0:color={navy}[base];"
        # Bot: crop de la zona header+mensajes del chat, escalado a la banda inferior,
        # y congelado (clone) para cubrir toda la duración de Nazareno.
        f"[1:v]crop=1080:1120:0:0,scale={w}:{bot_h}:force_original_aspect_ratio=decrease,"
        f"pad={w}:{bot_h}:(ow-iw)/2:(oh-ih)/2:color={navy},setsar=1,"
        f"tpad=stop_mode=clone:stop_duration=30[bot];"
        f"[base][bot]overlay=0:{top_h}:shortest=1,format=yuv420p[v]"
    )


def assemble_split(clip_path: str, frame_paths: List[str],
                   out_name: Optional[str] = None) -> Optional[str]:
    """Short PRO estilo tech-TikTok: Nazareno hablando ARRIBA + la demo del bot
    funcionando ABAJO, AL MISMO TIEMPO (no en secuencia). Devuelve /media/<file>.mp4
    o None (el caller cae al modo secuencial)."""
    frames = [p for p in (frame_paths or []) if p and Path(p).exists()]
    if not clip_path or not Path(clip_path).exists() or not frames:
        return None
    work = _images_dir() / f"_split_{uuid.uuid4().hex[:8]}"
    work.mkdir(parents=True, exist_ok=True)
    try:
        # 1) demo del chat como mini-video (los frames con su timing de animación).
        demo = assemble_short_animated(clip_path="", frame_paths=[]) if False else None
        segs = []
        n = len(frames)
        for i, p in enumerate(frames):
            is_typing = "typing" in Path(p).stem
            dur = 0.8 if is_typing else (2.4 if i == n - 1 else 1.3)
            segs.append({"path": p, "kind": "image", "dur": dur, "zoom": False})
        demo_url = assemble(segs, out_name=f"_demo_{uuid.uuid4().hex[:8]}.mp4")
        demo = _images_dir() / Path(demo_url).name if demo_url else None
        if not demo or not demo.exists():
            return None
        # 2) composición split, probando 1080p → 720p (RAM del container).
        fname = out_name or f"short_{uuid.uuid4().hex}.mp4"
        final = _images_dir() / fname
        ok = False
        for w, h in _SIZES:
            cmd = [_ffmpeg(), "-y", "-i", str(clip_path), "-i", str(demo),
                   "-filter_complex", _split_filter(w, h),
                   "-map", "[v]", "-map", "0:a?",
                   "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", *_X264_LOWMEM,
                   "-c:a", "aac", "-ar", "44100", "-ac", "2",
                   "-movflags", "+faststart", "-shortest", str(final)]
            if _run(cmd):
                ok = True
                break
            log.warning("split_size_failed", size=f"{w}x{h}")
        try:
            demo.unlink()
        except Exception:
            pass
        if not ok:
            return None
        log.info("video_split_assembled", file=fname)
        return f"/media/{fname}"
    finally:
        try:
            for f in work.glob("*"):
                f.unlink()
            work.rmdir()
        except Exception:
            pass
