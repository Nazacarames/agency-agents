"""
write_json_atomic — escritura atómica de JSON stores (tmp + os.replace).

Si el proceso muere a mitad de un write_text directo, el store queda truncado
y el próximo load cae al default vacío EN SILENCIO (se pierden hooks, radar,
token de LinkedIn, log de enviados de outbound → re-mailear contactados).
El patrón tmp+replace ya estaba copy-pasteado en 13 stores; este es el helper
único para los nuevos y para los que se lo habían perdido.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def write_json_atomic(path: Path, data: Any, **json_kwargs) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    json_kwargs.setdefault("ensure_ascii", False)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, **json_kwargs), encoding="utf-8")
    os.replace(tmp, path)
