"""
inbox_state — registro de hilos de Gmail YA procesados por el inbox_assistant.

Por qué existe: el agente antes dependía de `is:unread` para saber qué atender.
Si el operador abría un mail desde el teléfono, el hilo dejaba de estar unread y
la respuesta del prospecto quedaba SIN contestar y SIN marcar en el pipeline
(así se perdieron respuestas reales). Ahora el agente mira TODOS los hilos
recientes y este store lleva el dedup: por hilo, el último msg_id ya atendido.
Un hilo se reprocesa sólo si le llegó un mensaje NUEVO después del registrado.

Persistencia: JSON en el volume (data/inbox-processed.json).
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

MAX_THREADS = 500  # historial de hilos que se recuerda

_LOCK = threading.Lock()


def _store_path() -> Path:
    return Path(__file__).resolve().parent.parent.parent / "data" / "inbox-processed.json"


def _load() -> Dict[str, Any]:
    p = _store_path()
    if not p.exists():
        return {"threads": {}}
    try:
        with p.open("r", encoding="utf-8") as f:
            data = json.load(f)
        data.setdefault("threads", {})
        return data
    except Exception:
        return {"threads": {}}


def _save(store: Dict[str, Any]) -> None:
    p = _store_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(store, f, ensure_ascii=False, indent=2)
    os.replace(tmp, p)


def already_processed(thread_id: str, last_msg_id: str) -> bool:
    """True si el último mensaje del hilo ya fue atendido en una corrida previa."""
    if not thread_id:
        return False
    entry = _load()["threads"].get(thread_id) or {}
    return bool(last_msg_id) and entry.get("last_msg_id") == last_msg_id


def mark_processed(thread_id: str, last_msg_id: str, action: str = "") -> None:
    """Registra que el hilo quedó atendido hasta `last_msg_id`."""
    if not thread_id:
        return
    with _LOCK:
        store = _load()
        threads = store["threads"]
        threads[thread_id] = {
            "last_msg_id": last_msg_id,
            "action": action,
            "at": datetime.now(timezone.utc).isoformat(),
        }
        if len(threads) > MAX_THREADS:
            # tirar los más viejos por fecha de registro
            ordered = sorted(threads.items(), key=lambda kv: kv[1].get("at", ""))
            store["threads"] = dict(ordered[-MAX_THREADS:])
        _save(store)
