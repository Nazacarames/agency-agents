"""
vision — deja que el sistema MIRE imágenes (los agentes son ciegos).

Antes esto era Gemini multimodal vía Vertex. Se sacó de Google por decisión del
dueño (2026-09-16): Vertex era lo ÚNICO de Google que factura por uso en los
agentes — Gmail, Drive, Search Console, YouTube y la API de Ads son gratis — y
se decidió dejar Google Cloud sólo para CLAMEVET.

Quién hace qué ahora:
  · mirar imágenes y video → Google AI Studio (gratis, API key sin tarjeta), con
    `z-ai/glm-5.3-flash` de red cuando AI Studio se satura.
  · texto puro             → Kimi K3 por NVIDIA.

AI Studio NO es Vertex: no lleva service account ni facturación. Vertex sigue
afuera. Entra sólo para mirar, porque devuelve el VIDEO NATIVO con audio que
habíamos perdido — ver `gemini_free.py`.

Kimi NO tiene variante multimodal en los catálogos que tenemos: verificado el
2026-09-16 listando los dos endpoints (tokenrouter expone 1 modelo, NVIDIA 82) y
no hay ningún `kimi-vl`. Por eso mirar y escribir usan modelos distintos.

Tiempos medidos (2026-09-17, misma imagen): AI Studio 3,3 s · glm-5.3-flash
~155 s. Por eso AI Studio va primero; glm queda para cuando no está.

El video va NATIVO por AI Studio (movimiento + audio + texto en pantalla). Sólo
si eso no está disponible se cae al muestreo por frames con ffmpeg, que pierde el
audio: en ese caso se le avisa al modelo que son fotos, para que no opine sobre
música ni ritmo.

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
    """Mira imágenes (hasta 8) y responde texto. "" si falla.

    AI Studio primero (3 s contra 155 s); si no está o se saturó, NVIDIA.
    """
    if not image_paths:
        return ""
    from . import gemini_free
    if gemini_free.enabled():
        r = gemini_free.describir_imagenes(image_paths, prompt, max_tokens)
        if r:
            return r
        log.warning("vision_cae_a_nvidia", motivo="AI Studio no contestó")
    if not enabled():
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

    Por AI Studio va el video ENTERO, con audio. Si eso no está, se cae a frames:
    ahí son fotos y se le avisa al modelo, para que no describa cosas que no puede
    saber --si cree que ve el video entero, opina sobre ritmo y música y lo inventa.
    """
    if not video_path:
        return ""
    # NATIVO primero: con audio y movimiento. Los frames son el plan B.
    from . import gemini_free
    if gemini_free.enabled():
        r = gemini_free.describir_video(video_path, prompt, max_tokens)
        if r:
            log.info("video_nativo_ok", video=Path(video_path).name)
            return r
        log.warning("video_cae_a_frames", motivo="AI Studio no contestó o pesa de más")
    if not enabled():
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
