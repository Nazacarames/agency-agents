"""
minimax_video — generación de video con la API de MiniMax (Hailuo).

Misma API key que image_gen / el LLM (MINIMAX_API_KEY). Reemplaza a HeyGen y a
MoneyPrinterTurbo: el render corre en la nube de MiniMax (cero RAM/Railway).

Modo image-to-video: anima una imagen (p.ej. la foto de Nazareno) según un prompt
de movimiento. Flujo async:
  1. create_task(prompt, first_frame_image) -> task_id
  2. query_task(task_id) -> status (Queueing/Preparing/Processing/Success/Fail) + file_id
  3. retrieve_file(file_id) -> download_url (mp4)

Docs: https://platform.minimax.io/docs/guides/video-generation
"""
from __future__ import annotations

import time
from typing import Any, Dict, Optional

import httpx

from ..config import get_settings
from ..log import get_logger

log = get_logger("minimax_video")

DEFAULT_MODEL = "MiniMax-Hailuo-02"
_DONE = {"Success"}
_FAIL = {"Fail"}


def _root() -> str:
    base = (get_settings().minimax_base_url or "https://api.minimax.io/anthropic")
    return base.split("/anthropic")[0].rstrip("/")


def enabled() -> bool:
    return bool(get_settings().minimax_api_key)


def _headers() -> Dict[str, str]:
    return {"Authorization": f"Bearer {get_settings().minimax_api_key}",
            "Content-Type": "application/json"}


def create_task(prompt: str, first_frame_image: Optional[str] = None,
                model: str = DEFAULT_MODEL, duration: int = 6,
                resolution: str = "1080P") -> str:
    """Crea una tarea de generación de video. Devuelve task_id."""
    body: Dict[str, Any] = {
        "model": model,
        "prompt": (prompt or "").strip()[:2000],
        "duration": duration,
        "resolution": resolution,
    }
    if first_frame_image:
        body["first_frame_image"] = first_frame_image
    with httpx.Client(timeout=60) as c:
        r = c.post(f"{_root()}/v1/video_generation", json=body, headers=_headers())
    data = r.json() if r.content else {}
    br = data.get("base_resp") or {}
    if br.get("status_code") not in (0, None):
        raise RuntimeError(f"video_generation error {br.get('status_code')}: {br.get('status_msg')}")
    tid = data.get("task_id")
    if not tid:
        raise RuntimeError(f"sin task_id: {str(data)[:300]}")
    log.info("minimax_video_task_created", task_id=tid, model=model, img=bool(first_frame_image))
    return tid


def query_task(task_id: str) -> Dict[str, Any]:
    """Estado de la tarea: {status, file_id?}."""
    with httpx.Client(timeout=30) as c:
        r = c.get(f"{_root()}/v1/query/video_generation",
                  params={"task_id": task_id}, headers=_headers())
    return r.json() if r.content else {}


def retrieve_file(file_id: str) -> Optional[str]:
    """Devuelve el download_url del archivo generado."""
    with httpx.Client(timeout=30) as c:
        r = c.get(f"{_root()}/v1/files/retrieve",
                  params={"file_id": file_id}, headers=_headers())
    data = r.json() if r.content else {}
    return (data.get("file") or {}).get("download_url")


def status_with_url(task_id: str) -> Dict[str, Any]:
    """Estado normalizado para el panel/poll: incluye download_url si terminó."""
    q = query_task(task_id)
    status = q.get("status")
    out = {"task_id": task_id, "status": status, "file_id": q.get("file_id")}
    if status in _DONE and q.get("file_id"):
        out["download_url"] = retrieve_file(q["file_id"])
    elif status in _FAIL:
        out["error"] = q.get("base_resp") or q
    return out


def generate_and_wait(prompt: str, first_frame_image: Optional[str] = None,
                      model: str = DEFAULT_MODEL, duration: int = 6,
                      resolution: str = "1080P", timeout_s: int = 600,
                      poll: int = 10) -> Dict[str, Any]:
    """Crea la tarea y espera (bloqueante) hasta el video. Devuelve {task_id, download_url}."""
    tid = create_task(prompt, first_frame_image, model, duration, resolution)
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        q = query_task(tid)
        st = q.get("status")
        if st in _DONE and q.get("file_id"):
            url = retrieve_file(q["file_id"])
            log.info("minimax_video_done", task_id=tid, url=bool(url))
            return {"task_id": tid, "status": st, "download_url": url}
        if st in _FAIL:
            raise RuntimeError(f"video task fail: {q.get('base_resp') or q}")
        time.sleep(poll)
    raise TimeoutError(f"video task timeout ({tid})")
