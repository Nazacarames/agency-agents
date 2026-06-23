"""
tasks_store — historial de TAREAS ad-hoc lanzadas a los agentes desde el dashboard.

Cada vez que el operador le manda una tarea libre a un agente (además de su trabajo
por schedule), se registra acá. Persistencia: JSON en el volume (data/tasks-store.json).
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

MAX_TASKS = 200  # se conservan las últimas N


def _data_dir() -> Path:
    return Path(__file__).resolve().parent.parent.parent / "data"


def _store_path() -> Path:
    return _data_dir() / "tasks-store.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_store() -> Dict[str, Any]:
    p = _store_path()
    if not p.exists():
        return {"tasks": []}
    try:
        with p.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if "tasks" not in data:
            data["tasks"] = []
        return data
    except Exception:
        return {"tasks": []}


def save_store(store: Dict[str, Any]) -> None:
    p = _store_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(store, f, ensure_ascii=False, indent=2)
    os.replace(tmp, p)


def add_task(agent: str, prompt: str, run_id: str) -> Dict[str, Any]:
    store = load_store()
    task = {
        "id": uuid.uuid4().hex[:12],
        "agent": agent,
        "prompt": prompt,
        "run_id": run_id,
        "status": "queued",
        "result_excerpt": "",
        "created_at": _now(),
        "updated_at": _now(),
    }
    store["tasks"].insert(0, task)
    store["tasks"] = store["tasks"][:MAX_TASKS]
    save_store(store)
    return task


def update_task(run_id: str, status: str, result_excerpt: str = "") -> Optional[Dict[str, Any]]:
    store = load_store()
    for t in store["tasks"]:
        if t.get("run_id") == run_id:
            t["status"] = status
            if result_excerpt:
                t["result_excerpt"] = result_excerpt[:600]
            t["updated_at"] = _now()
            save_store(store)
            return t
    return None


def list_tasks(limit: int = 50) -> List[Dict[str, Any]]:
    return load_store().get("tasks", [])[:limit]
