"""
higgsfield — generación de imagen y video SIN Google.

Por qué existe: el 2026-09-16 el dueño decidió sacar Vertex de los agentes
(Imagen, Veo y Gemini eran lo ÚNICO de Google que factura por uso acá; Gmail,
Drive, Search Console, YouTube y la API de Ads son gratis) y dejar Google Cloud
reservado para CLAMEVET. La generación pasa al pool de créditos de Higgsfield
que ya estaba comprado.

⚠️ ESTO CONSUME CRÉDITOS. El plan ilimitado de Higgsfield es sólo web/manual —
sus propios términos excluyen API, CLI y automatización— así que cada llamada de
acá sale del pool prepago. No hay endpoint de saldo: se mira en cloud.higgsfield.ai.

TODO lo de acá está verificado contra la especificación OpenAPI oficial
(`Higgsfield API 2.0.0`, 50 endpoints), no contra la memoria de cómo era antes.
Eso corrigió cuatro cosas que habrían hecho fallar cada llamada:
  · El host es `platform.higgsfield.ai`, NO `api.higgsfield.ai`.
  · El video es `POST /veo3.1`, no `/veo3.1/text-to-video`.
  · `resolution` es "720"/"1080" SIN la "p", y `duration` es un STRING ("8").
  · Las imágenes son `/higgsfield-ai/soul/standard` y aceptan `num_images`,
    así que no hace falta pedirlas de a una.

Gotchas que sí seguían valiendo:
  · Auth: header `Authorization: Key <id>:<secret>` (no Bearer). Confirmado en
    el `securitySchemes` de la spec.
  · Cloudflare corta el User-Agent de las librerías HTTP con error 1010 → hay
    que mandar uno de browser o todo da 403.
  · `generate_audio` viene en False por default: por eso los primeros videos del
    banco de agosto salieron MUDOS.
  · Flujo async: submit → {request_id} → pollear status hasta `completed`.

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

BASE = "https://platform.higgsfield.ai"

# Cloudflare devuelve 403 (error 1010) con el User-Agent de las librerías HTTP.
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36")

# Un video de 1080/8s tardó ~150 s medidos. El tope deja margen para la cola.
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
            r = c.post(f"{BASE}/{ruta.lstrip('/')}", json=cuerpo, headers=_headers())
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
                r = c.get(f"{BASE}/requests/{request_id}/status", headers=_headers())
            if r.status_code < 400:
                d = r.json() if r.content else {}
                estado = (d.get("status") or "").lower()
                if estado == "completed":
                    return d
                # `nsfw` es un falso positivo conocido (pasó en el banco de agosto)
                # y `failed` suele ser transitorio. Los dos cortan la espera: quien
                # llama decide si reformula o reintenta.
                if estado in ("failed", "nsfw", "canceled", "cancelled"):
                    log.warning("higgsfield_terminó_mal", request_id=request_id,
                                estado=estado)
                    return {}
        except Exception as e:                              # noqa: BLE001
            log.warning("higgsfield_poll_error", error=str(e)[:120])
        time.sleep(ENTRE_POLLS)
    log.warning("higgsfield_timeout", request_id=request_id, segundos=espera_max)
    return {}


def _urls_del_resultado(d: Dict[str, Any]) -> List[str]:
    """Los archivos salen en CloudFront y se bajan sin auth. La forma exacta del
    resultado cambia según el modelo, así que se recorre buscando urls."""
    urls: List[str] = []

    def hurgar(o: Any) -> None:
        if isinstance(o, dict):
            u = o.get("url")
            if isinstance(u, str) and u.startswith("http"):
                urls.append(u)
            for v in o.values():
                hurgar(v)
        elif isinstance(o, list):
            for v in o:
                hurgar(v)

    hurgar(d.get("final") or d.get("results") or d.get("result") or d)
    return urls


def _bajar(url: str) -> bytes:
    with httpx.Client(timeout=300, follow_redirects=True) as c:
        r = c.get(url, headers={"User-Agent": UA})
        r.raise_for_status()
        return r.content


def generar_video(prompt: str, *, vertical: bool = True, segundos: int = 8,
                  con_audio: bool = True, rapido: bool = False,
                  referencias: Optional[List[str]] = None) -> bytes:
    """Un video con Veo 3.1. b"" si no se pudo.

    Con `referencias` (URLs de imagen) usa `reference-to-video`, que es lo que
    mantiene la CARA del personaje entre clips. Sin ellas va el text-to-video
    común.

    `duration` y `resolution` van como STRING porque así los pide la spec; con
    enteros o con "1080p" la API rechaza el request.
    """
    if not enabled() or not (prompt or "").strip():
        return b""
    cuerpo: Dict[str, Any] = {
        "prompt": prompt[:2000],
        "duration": str(segundos if segundos in (4, 6, 8) else 8),
        "resolution": "1080",
        "aspect_ratio": "9:16" if vertical else "16:9",
        "generate_audio": bool(con_audio),
    }
    if referencias:
        ruta = "veo3.1/reference-to-video"
        cuerpo["image_urls"] = list(referencias)[:4]
    else:
        ruta = "veo3.1/fast" if rapido else "veo3.1"

    rid = _submit(ruta, cuerpo)
    if not rid:
        return b""
    urls = _urls_del_resultado(_esperar(rid))
    if not urls:
        return b""
    try:
        datos = _bajar(urls[0])
        log.info("higgsfield_video", request_id=rid, ruta=ruta, bytes=len(datos),
                 con_referencias=bool(referencias))
        return datos
    except Exception as e:                                  # noqa: BLE001
        log.warning("higgsfield_bajada_falló", error=str(e)[:150])
        return b""


def generar_imagen(prompt: str, aspect_ratio: str = "1:1", n: int = 1) -> List[bytes]:
    """Imágenes con Soul. [] si no se pudo.

    `num_images` viene en la API, así que van en UN pedido y no de a una.
    """
    if not enabled() or not (prompt or "").strip():
        return []
    # La spec sólo acepta esta lista; cualquier otro valor lo rechaza.
    validos = ("1:1", "4:3", "3:4", "3:2", "2:3", "5:4", "4:5", "16:9", "9:16", "21:9")
    rid = _submit("higgsfield-ai/soul/standard", {
        "prompt": prompt[:2000],
        "num_images": max(1, min(int(n), 8)),
        "aspect_ratio": aspect_ratio if aspect_ratio in validos else "1:1",
        "resolution": "2K",
    })
    if not rid:
        return []
    salida: List[bytes] = []
    for url in _urls_del_resultado(_esperar(rid, espera_max=300))[:max(1, n)]:
        try:
            salida.append(_bajar(url))
        except Exception as e:                              # noqa: BLE001
            log.warning("higgsfield_imagen_bajada_falló", error=str(e)[:150])
    log.info("higgsfield_imagenes", pedidas=n, obtenidas=len(salida))
    return salida


def generate_and_wait(prompt: str, aspect_ratio: str = "9:16",
                      timeout_s: int = ESPERA_MAX,
                      reference_image_urls: Optional[List[str]] = None,
                      **_ignorado) -> Dict[str, Any]:
    """Adaptador con la forma que ya esperaba el llamador: {"b64": ...}.

    `reference_image_urls` SÍ se usa: la spec expone `reference-to-video`, que es
    lo que mantiene la cara de Nazareno entre clips. Los demás parámetros que
    eran de Veo por Vertex (`negative_prompt`, `model`…) se aceptan y se ignoran
    para no romper firmas.
    """
    import base64 as _b64
    datos = generar_video(prompt, vertical=(aspect_ratio == "9:16"), segundos=8,
                          con_audio=True, referencias=reference_image_urls)
    if not datos:
        return {}
    return {"b64": _b64.b64encode(datos).decode(), "motor": "Higgsfield/Veo 3.1"}
