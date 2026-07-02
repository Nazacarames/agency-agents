"""
veo_video — generación de video con Google Veo 3 vía Vertex AI.

La org del usuario bloquea las API keys (política de seguridad) → autenticamos
con un **service account** (ADC). Los créditos de Google Cloud (US$300) se
descuentan directo del proyecto. Reemplaza a MoneyPrinterTurbo / MiniMax video.

Modo image-to-video: anima una imagen (p.ej. la foto de Nazareno) según un prompt
de movimiento → clip vertical 9:16 de ~8s. Flujo async (long-running operation):
  1. create_task(prompt, image_url|image_b64) -> operation_name
  2. query_task(operation_name) -> {done, b64?, error?}   (Vertex: fetchPredictOperation)
  3. el video vuelve como bytes base64 inline (sin storageUri) → fetch_bytes los decodifica

Config: GOOGLE_SERVICE_ACCOUNT_JSON (JSON de la SA, rol "Vertex AI User"),
VERTEX_PROJECT (opcional, default = project_id del JSON), VERTEX_LOCATION.

Docs: https://cloud.google.com/vertex-ai/generative-ai/docs/video/generate-videos
"""
from __future__ import annotations

import base64
import json
import threading
import time
from typing import Any, Dict, Optional

import httpx

from ..config import get_settings
from ..log import get_logger

log = get_logger("veo_video")

_SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]
_creds_lock = threading.Lock()
_creds = None  # cache del objeto Credentials (refresca solo)


def enabled() -> bool:
    return bool(get_settings().google_service_account_json)


def _sa_info() -> Dict[str, Any]:
    raw = get_settings().google_service_account_json
    if not raw:
        raise RuntimeError("Veo no configurado (sin GOOGLE_SERVICE_ACCOUNT_JSON)")
    return json.loads(raw)


def _project() -> str:
    s = get_settings()
    return s.vertex_project or _sa_info().get("project_id", "")


def _location() -> str:
    return get_settings().vertex_location or "us-central1"


def _model() -> str:
    return get_settings().veo_model or "veo-3.0-fast-generate-001"


def _build_creds():
    """Construye Credentials desde el JSON: service account O usuario ADC (gcloud).

    Soporta los dos porque la org bloquea API keys y puede bloquear también las
    claves de SA → en ese caso se usa `gcloud auth application-default login`
    (type=authorized_user). Ese JSON no es una clave de SA, así que la política no
    lo frena.
    """
    info = _sa_info()
    t = info.get("type")
    if t == "authorized_user":
        from google.oauth2.credentials import Credentials as UserCreds
        return UserCreds.from_authorized_user_info(info, scopes=_SCOPES)
    from google.oauth2 import service_account
    return service_account.Credentials.from_service_account_info(info, scopes=_SCOPES)


def _token() -> str:
    """Mintea/refresca un access token OAuth desde la credencial configurada."""
    global _creds
    import google.auth.transport.requests as gar
    with _creds_lock:
        if _creds is None:
            _creds = _build_creds()
        if not _creds.valid:
            _creds.refresh(gar.Request())
        return _creds.token


def _base() -> str:
    loc = _location()
    return (f"https://{loc}-aiplatform.googleapis.com/v1/projects/{_project()}"
            f"/locations/{loc}/publishers/google/models/{_model()}")


def _headers() -> Dict[str, str]:
    return {"Authorization": f"Bearer {_token()}", "Content-Type": "application/json"}


def fetch_image_b64(url: str) -> Dict[str, str]:
    """Descarga una imagen y la devuelve {bytesBase64Encoded, mimeType} para Veo."""
    with httpx.Client(timeout=60, follow_redirects=True) as c:
        r = c.get(url)
        r.raise_for_status()
        mime = r.headers.get("content-type", "image/jpeg").split(";")[0].strip()
        if not mime.startswith("image/"):
            mime = "image/jpeg"
        return {"bytesBase64Encoded": base64.b64encode(r.content).decode("ascii"),
                "mimeType": mime}


def create_task(prompt: str, image_url: Optional[str] = None,
                image_b64: Optional[Dict[str, str]] = None,
                aspect_ratio: str = "9:16",
                negative_prompt: str = "",
                reference_image_urls: Optional[list] = None,
                resolution: Optional[str] = "1080p") -> str:
    """Lanza la generación. Devuelve el operation_name (para pollear).

    - reference_image_urls: lista de URLs (hasta 3). Modo Veo 3.1 "reference image"
      (referenceType=asset): mantiene el MISMO personaje (cara de Nazareno) en escenas
      descritas por el prompt → consistencia + lugar/fondo controlables. Si se pasa,
      tiene prioridad sobre image_url (que es first-frame/image-to-video).
    - resolution: "1080p" (default) | "720p" | None. Si el modelo rechaza el
      parámetro para este aspect ratio, se reintenta sin él (default del modelo).
    """
    instance: Dict[str, Any] = {"prompt": (prompt or "").strip()[:2000]}
    if reference_image_urls:
        refs = []
        for u in reference_image_urls[:3]:
            try:
                refs.append({"image": fetch_image_b64(u), "referenceType": "asset"})
            except Exception:
                continue
        if refs:
            instance["referenceImages"] = refs
    else:
        img = image_b64 or (fetch_image_b64(image_url) if image_url else None)
        if img:
            instance["image"] = img
    params: Dict[str, Any] = {"aspectRatio": aspect_ratio, "sampleCount": 1}
    if resolution:
        params["resolution"] = resolution
    if negative_prompt:
        params["negativePrompt"] = negative_prompt

    def _post(body: Dict[str, Any]) -> Dict[str, Any]:
        with httpx.Client(timeout=90) as c:
            r = c.post(f"{_base()}:predictLongRunning", json=body, headers=_headers())
        return {"status": r.status_code, "data": r.json() if r.content else {},
                "text": r.text[:300]}

    res = _post({"instances": [instance], "parameters": params})
    if (res["status"] >= 400 or "error" in res["data"]) and resolution:
        # p.ej. modelo/aspect que no soporta el parámetro resolution → sin él
        log.warning("veo_resolution_retry", resolution=resolution,
                    error=str(res["data"].get("error") or res["text"])[:200])
        params.pop("resolution", None)
        res = _post({"instances": [instance], "parameters": params})
    data = res["data"]
    if res["status"] >= 400 or "error" in data:
        err = data.get("error") or {"status": res["status"], "text": res["text"]}
        raise RuntimeError(f"veo create error: {err}")
    name = data.get("name")
    if not name:
        raise RuntimeError(f"veo sin operation name: {str(data)[:300]}")
    log.info("veo_task_created", op=name, model=_model(), resolution=params.get("resolution"),
             refs=len(instance.get("referenceImages", [])), firstframe="image" in instance)
    return name


def _extract_b64(resp: Dict[str, Any]) -> Optional[str]:
    """Saca los bytes base64 del video del response (tolerante a variantes)."""
    videos = (resp.get("videos") or resp.get("generatedSamples")
              or resp.get("predictions") or [])
    for v in videos:
        b64 = v.get("bytesBase64Encoded") or v.get("video", {}).get("bytesBase64Encoded")
        if b64:
            return b64
    return None


def query_task(operation_name: str) -> Dict[str, Any]:
    """Estado de la operación (Vertex: fetchPredictOperation). {done, b64?, gcsUri?, error?}."""
    body = {"operationName": operation_name}
    with httpx.Client(timeout=60) as c:
        r = c.post(f"{_base()}:fetchPredictOperation", json=body, headers=_headers())
    data = r.json() if r.content else {}
    if r.status_code >= 400:
        return {"done": False, "error": data.get("error") or {"status": r.status_code}}
    out: Dict[str, Any] = {"done": bool(data.get("done"))}
    if data.get("error"):
        out["error"] = data["error"]
    if out["done"]:
        resp = data.get("response") or {}
        b64 = _extract_b64(resp)
        gcs = next((v.get("gcsUri") for v in (resp.get("videos") or []) if v.get("gcsUri")), None)
        if b64:
            out["b64"] = b64
        elif gcs:
            out["gcsUri"] = gcs
        elif not out.get("error"):
            out["error"] = {"msg": "done sin video", "raw": str(data)[:400]}
    return out


def save_video(b64: str, path: str) -> str:
    """Decodifica el base64 a un mp4 en disco. Devuelve el path."""
    with open(path, "wb") as f:
        f.write(base64.b64decode(b64))
    return path


def generate_and_wait(prompt: str, image_url: Optional[str] = None,
                      image_b64: Optional[Dict[str, str]] = None,
                      aspect_ratio: str = "9:16", negative_prompt: str = "",
                      timeout_s: int = 600, poll: int = 12,
                      reference_image_urls: Optional[list] = None,
                      resolution: Optional[str] = "1080p") -> Dict[str, Any]:
    """Crea la tarea y espera (bloqueante) hasta el video. Devuelve {operation, b64|gcsUri}."""
    op = create_task(prompt, image_url, image_b64, aspect_ratio, negative_prompt,
                     reference_image_urls=reference_image_urls, resolution=resolution)
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        q = query_task(op)
        if q.get("done"):
            if q.get("b64") or q.get("gcsUri"):
                log.info("veo_done", op=op, gcs=bool(q.get("gcsUri")))
                return {"operation": op, "b64": q.get("b64"), "gcsUri": q.get("gcsUri")}
            raise RuntimeError(f"veo task fail: {q.get('error')}")
        time.sleep(poll)
    raise TimeoutError(f"veo task timeout ({op})")
