"""
higgsfield — generación de imagen y video SIN Google.

Por qué existe: el 2026-09-16 el dueño decidió sacar Vertex de los agentes
(Imagen, Veo y Gemini eran lo ÚNICO de Google que factura por uso acá; Gmail,
Drive, Search Console, YouTube y la API de Ads son gratis) y dejar Google Cloud
reservado para CLAMEVET. La generación pasa al pool de créditos de Higgsfield
que ya estaba comprado.

⚠️ ESTO CONSUME CRÉDITOS. El plan ilimitado de Higgsfield es sólo web/manual —
sus propios términos excluyen API, CLI y automatización— así que cada llamada de
acá sale del pool prepago (~835 comprados, parte usada en el banco de 46 videos
de agosto). No hay endpoint de saldo: se mira en cloud.higgsfield.ai.

Receta verificada el 2026-08-26 generando videos reales, y los gotchas que costó
encontrar:
  · Auth: header `Authorization: Key <id>:<secret>` (no Bearer).
  · Cloudflare corta el User-Agent por defecto con error 1010 → hay que mandar
    uno de browser o todo da 403.
  · Video: Veo 3.1 en `POST api.higgsfield.ai/veo3.1/text-to-video`. `generate_audio`
    viene en FALSE por default: por eso los primeros videos salieron MUDOS.
  · Flujo async: submit → {request_id} → pollear el status hasta `completed`.
  · Seedance NO está en la API (es sólo del ilimitado web).

Sin credenciales, `enabled()` devuelve False y el que llama sigue por su fallback
de siempre. Nunca levanta.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

import httpx

from ..config import get_settings
from ..log import get_logger

log = get_logger("higgsfield")

API = "https://api.higgsfield.ai"
PLATAFORMA = "https://platform.higgsfield.ai"

# Cloudflare devuelve 403 (error 1010) con el User-Agent de las librerías HTTP.
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36")

# Un video de 1080p/8s tardó ~150 s medidos. El tope deja margen para la cola.
ESPERA_MAX = 600
ENTRE_POLLS = 10


def enabled() -> bool:
    s = get_settings()
    return bool(getattr(s, "higgsfield_key_id", "") and
                getattr(s, "higgsfield_key_secret", ""))


def _headers() -> Dict[str, str]:
    s = get_settings()
    return {"Authorization": f"Key {s.higgsfield_key_id}:{s.higgsfield_key_secret}",
            "User-Agent": UA, "Content-Type": "application/json"}


def _sin_credito(payload: Any, status: int) -> bool:
    """402, o el texto lo dice. Distinguirlo importa: sin crédito no se reintenta,
    se avisa, porque reintentar no lo va a arreglar y confunde el diagnóstico."""
    if status == 402:
        return True
    texto = str(payload).lower()
    return any(k in texto for k in ("insufficient", "no credit", "not enough",
                                    "credits", "quota exceeded"))


def _submit(ruta: str, cuerpo: Dict[str, Any]) -> Optional[str]:
    try:
        with httpx.Client(timeout=120) as c:
            r = c.post(f"{API}/{ruta.lstrip('/')}", json=cuerpo, headers=_headers())
        datos = r.json() if r.content else {}
        if r.status_code >= 400:
            if _sin_credito(datos, r.status_code):
                log.error("higgsfield_sin_credito", ruta=ruta, status=r.status_code)
            else:
                log.warning("higgsfield_submit_falló", ruta=ruta, status=r.status_code,
                            detalle=str(datos)[:200])
            return None
        rid = datos.get("request_id") or datos.get("id")
        if not rid:
            log.warning("higgsfield_sin_request_id", ruta=ruta, datos=str(datos)[:200])
        return rid
    except Exception as e:                                  # noqa: BLE001
        log.warning("higgsfield_submit_error", ruta=ruta, error=str(e)[:150])
        return None


def _esperar(request_id: str, espera_max: int = ESPERA_MAX) -> Dict[str, Any]:
    """Pollea hasta que termine. {} si falla o se agota el tiempo."""
    limite = time.time() + espera_max
    while time.time() < limite:
        try:
            with httpx.Client(timeout=60) as c:
                r = c.get(f"{PLATAFORMA}/requests/{request_id}/status",
                          headers=_headers())
            if r.status_code >= 400:
                time.sleep(ENTRE_POLLS)
                continue
            d = r.json() if r.content else {}
            estado = (d.get("status") or "").lower()
            if estado == "completed":
                return d
            # `nsfw` es un falso positivo conocido (pasó en el banco de agosto) y
            # `failed` suele ser transitorio. Los dos terminan la espera: quien
            # llama decide si reformula o reintenta.
            if estado in ("failed", "nsfw", "canceled", "cancelled"):
                log.warning("higgsfield_terminó_mal", request_id=request_id, estado=estado)
                return {}
        except Exception as e:                              # noqa: BLE001
            log.warning("higgsfield_poll_error", error=str(e)[:120])
        time.sleep(ENTRE_POLLS)
    log.warning("higgsfield_timeout", request_id=request_id, segundos=espera_max)
    return {}


def _url_del_resultado(d: Dict[str, Any], clave: str) -> str:
    """El MP4/PNG sale en final.<clave>.url (CloudFront, se baja sin auth)."""
    final = d.get("final") or d.get("result") or {}
    item = final.get(clave) or {}
    if isinstance(item, list) and item:
        item = item[0]
    return (item or {}).get("url", "") if isinstance(item, dict) else ""


def _bajar(url: str) -> bytes:
    with httpx.Client(timeout=300, follow_redirects=True) as c:
        r = c.get(url, headers={"User-Agent": UA})
        r.raise_for_status()
        return r.content


def generar_video(prompt: str, *, vertical: bool = True, segundos: int = 8,
                  con_audio: bool = True) -> bytes:
    """Un video con Veo 3.1. b"" si no se pudo.

    El default sale de lo que se midió mejor en el banco: 9:16 a 1080p, 8 s y con
    audio. `generate_audio` va explícito porque su default es False y por eso los
    primeros videos salieron mudos.
    """
    if not enabled() or not (prompt or "").strip():
        return b""
    rid = _submit("veo3.1/text-to-video", {
        "prompt": prompt[:2000],
        "aspect_ratio": "9:16" if vertical else "16:9",
        "resolution": "1080p",
        "duration": segundos if segundos in (4, 6, 8) else 8,
        "generate_audio": bool(con_audio),
    })
    if not rid:
        return b""
    d = _esperar(rid)
    url = _url_del_resultado(d, "video")
    if not url:
        return b""
    try:
        datos = _bajar(url)
        log.info("higgsfield_video", request_id=rid, bytes=len(datos))
        return datos
    except Exception as e:                                  # noqa: BLE001
        log.warning("higgsfield_bajada_falló", error=str(e)[:150])
        return b""


def generar_imagen(prompt: str, aspect_ratio: str = "1:1", n: int = 1) -> List[bytes]:
    """Imágenes con Soul. [] si no se pudo. `n` se pide una por una: la API no
    garantiza batch y así un fallo no se lleva puestas las demás."""
    if not enabled() or not (prompt or "").strip():
        return []
    salida: List[bytes] = []
    for _ in range(max(1, n)):
        rid = _submit("higgsfield-ai/soul/v2/standard", {
            "prompt": prompt[:2000],
            "aspect_ratio": aspect_ratio,
        })
        if not rid:
            break
        d = _esperar(rid, espera_max=300)
        url = _url_del_resultado(d, "image") or _url_del_resultado(d, "raw")
        if not url:
            continue
        try:
            salida.append(_bajar(url))
        except Exception as e:                              # noqa: BLE001
            log.warning("higgsfield_imagen_bajada_falló", error=str(e)[:150])
    log.info("higgsfield_imagenes", pedidas=n, obtenidas=len(salida))
    return salida


def generate_and_wait(prompt: str, aspect_ratio: str = "9:16",
                      timeout_s: int = ESPERA_MAX, **_ignorado) -> Dict[str, Any]:
    """Adaptador con la forma que ya esperaba el llamador: {"b64": ...}.

    Los parámetros que eran de Veo y acá no existen (`reference_image_urls`,
    `negative_prompt`, `model`…) se aceptan y se ignoran para no romper firmas.
    ⚠️ `reference_image_urls` era lo que le daba la CARA de Nazareno al clip:
    Veo aceptaba imágenes de referencia y este endpoint de Veo 3.1 por Higgsfield
    es text-to-video, así que esa consistencia de cara se pierde. Para
    mantenerla hay que pasar por Soul ID, que es otro flujo.
    """
    import base64 as _b64
    datos = generar_video(prompt, vertical=(aspect_ratio == "9:16"),
                          segundos=8, con_audio=True)
    if not datos:
        return {}
    return {"b64": _b64.b64encode(datos).decode(), "motor": "Higgsfield/Veo 3.1"}
