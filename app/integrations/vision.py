"""
vision — deja que el sistema MIRE imágenes (los agentes son ciegos).

Antes esto era Gemini multimodal vía Vertex. Se sacó de Google por decisión del
dueño (2026-09-16): Vertex era lo ÚNICO de Google que factura por uso en los
agentes — Gmail, Drive, Search Console, YouTube y la API de Ads son gratis — y
se decidió dejar Google Cloud sólo para CLAMEVET.

Ahora corre todo por la cuenta de NVIDIA que ya usábamos para texto:
  · mirar imágenes → `z-ai/glm-5.3-flash`
  · texto puro     → Kimi K3

Kimi NO tiene variante multimodal en los catálogos que tenemos: verificado el
2026-09-16 listando los dos endpoints (tokenrouter expone 1 modelo, NVIDIA 82) y
no hay ningún `kimi-vl`. Por eso mirar y escribir usan modelos distintos.

⚠️ MIRAR ES LENTO: ~155 s por llamada, medido. Es el precio de acertar — los
modelos rápidos que probamos describían mal o no respondían. Por eso el video
se muestrea en pocos frames y todo esto corre fuera del camino de un request.

⚠️ LO QUE SE PIERDE, y no es menor: Gemini analizaba el VIDEO NATIVO —movimiento,
AUDIO y texto en pantalla a lo largo del tiempo—. El modelo que mira ahora sólo ve imágenes
fijas, así que el video se muestrea en frames con ffmpeg (que ya está en la
imagen) y se pierde el audio. Para juzgar un short hablado eso es un bajón real;
está anotado acá para que nadie lo descubra por accidente.

Best-effort en todo: si no hay credencial o la llamada falla, devuelve "".
"""
from __future__ import annotations

import base64
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import List

from ..config import get_settings
from ..log import get_logger

log = get_logger("vision")

# Cuántos frames se le muestran al modelo de un video. Seis cubre el arco
# (apertura, desarrollo, cierre) y mantiene el request manejable: mirar cuesta
# ~155 s, y cada imagen de más lo encarece.
FRAMES_POR_VIDEO = 6

# Compatibilidad: los llamadores viejos podían pasar `model=`. Ya no se usa —
# el modelo sale de la config— pero se acepta para no romper ninguna firma.
_MODEL = "nvidia"


def enabled() -> bool:
    return bool(get_settings().nvidia_api_key)


def _completar(mensajes: list, proveedor: str, max_tokens: int) -> str:
    """Una completion contra NVIDIA. "" si falla: mirar es opcional, romper no."""
    try:
        from ..clients.nvidia import NvidiaClient
        with NvidiaClient(get_settings()) as c:
            r = c.complete("", mensajes, provider=proveedor,
                           max_tokens=max_tokens, temperature=0.4)
        return (r.text or "").strip()
    except Exception as e:                                  # noqa: BLE001
        log.warning("vision_falló", proveedor=proveedor, error=str(e)[:150])
        return ""


def _parte_imagen(ruta: Path) -> dict | None:
    """Una imagen como data-URI, en el formato multimodal de OpenAI."""
    try:
        datos = base64.b64encode(ruta.read_bytes()).decode()
    except Exception:
        return None
    mime = "image/png" if str(ruta).lower().endswith(".png") else "image/jpeg"
    return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{datos}"}}


def describe(image_paths: List[str], prompt: str, model: str = _MODEL,
             max_tokens: int = 1800) -> str:
    """Mira imágenes (hasta 8) y responde texto. "" si falla."""
    if not enabled() or not image_paths:
        return ""
    partes = []
    for p in image_paths[:8]:
        parte = _parte_imagen(Path(p))
        if parte:
            partes.append(parte)
    if not partes:
        return ""
    partes.append({"type": "text", "text": prompt})
    return _completar([{"role": "user", "content": partes}], "vision", max_tokens)


def _frames(video_path: str, n: int = FRAMES_POR_VIDEO) -> List[Path]:
    """Saca `n` frames repartidos a lo largo del video. [] si no se puede.

    `fps` fijo no sirve: un video de 5 s y uno de 60 s darían cantidades muy
    distintas. Se calcula la duración y se muestrea parejo.
    """
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg:
        log.warning("vision_sin_ffmpeg")
        return []
    dur = 0.0
    if ffprobe:
        try:
            out = subprocess.run(
                [ffprobe, "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", video_path],
                capture_output=True, text=True, timeout=60)
            dur = float((out.stdout or "0").strip() or 0)
        except Exception:
            dur = 0.0
    destino = Path(tempfile.mkdtemp(prefix="frames_"))
    # Sin duración medible se cae a 1 frame por segundo, con tope: peor muestreo,
    # pero mejor que no mirar nada.
    filtro = (f"fps={max(n / dur, 0.1):.4f}" if dur > 0 else "fps=1")
    try:
        subprocess.run(
            [ffmpeg, "-v", "error", "-i", video_path, "-vf", filtro,
             "-frames:v", str(n), "-q:v", "3", str(destino / "f%02d.jpg")],
            capture_output=True, timeout=180)
    except Exception as e:                                  # noqa: BLE001
        log.warning("vision_frames_falló", error=str(e)[:150])
        return []
    salida = sorted(destino.glob("*.jpg"))
    log.info("vision_frames", video=Path(video_path).name, frames=len(salida),
             duracion=round(dur, 1))
    return salida


def describe_video(video_path: str, prompt: str, model: str = _MODEL,
                   max_tokens: int = 1800) -> str:
    """Analiza un video muestreando frames. "" si falla.

    OJO: son fotos, no el video. No hay audio ni movimiento. Se le dice al modelo
    explícitamente para que no describa cosas que no puede saber --si cree que
    está viendo el video entero, opina sobre el ritmo y la música y se lo inventa.
    """
    if not enabled() or not video_path:
        return ""
    frames = _frames(video_path)
    if not frames:
        return ""
    aviso = (f"Son {len(frames)} fotogramas tomados a intervalos regulares de un "
             "video, en orden. NO tenés el audio ni el movimiento: no opines sobre "
             "música, voz, ritmo ni transiciones. Limitate a lo que se ve.\n\n")
    try:
        return describe([str(f) for f in frames], aviso + prompt, max_tokens=max_tokens)
    finally:
        for f in frames:
            try:
                f.unlink()
            except Exception:
                pass


def synthesize(text: str, prompt: str, model: str = _MODEL,
               max_tokens: int = 2000) -> str:
    """Llamada solo-texto (sintetizar notas en el playbook final). "" si falla."""
    if not enabled() or not text.strip():
        return ""
    return _completar([{"role": "user", "content": prompt + "\n\n" + text}],
                      "kimi", max_tokens)
