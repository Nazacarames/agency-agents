"""
db — acceso a Postgres (Supabase) para la capa de memoria de la agencia.

Toda la data vive bajo el schema `agency` (aislado de las tablas de Paperclip
que comparten la misma instancia). Conexión lazy, guardada por un lock y con
reconexión automática: el panel y los agentes son de bajo tráfico, así que una
única conexión serializada alcanza y sobra.

Si `DATABASE_URL` no está configurada, `enabled()` devuelve False y los stores
caen a su modo JSON-en-volume (fallback resiliente).
"""
from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Any, Dict, Iterable, List, Optional

from ..config import get_settings

try:  # psycopg es opcional: si no está instalado, simplemente no hay DB
    import psycopg
    from psycopg.rows import dict_row
    _HAVE_PSYCOPG = True
except Exception:  # pragma: no cover
    psycopg = None  # type: ignore
    dict_row = None  # type: ignore
    _HAVE_PSYCOPG = False

_LOCK = threading.Lock()
_CONN = None  # type: ignore


def enabled() -> bool:
    return bool(_HAVE_PSYCOPG and get_settings().database_url)


def schema() -> str:
    return get_settings().db_schema or "agency"


def _connect():
    settings = get_settings()
    conn = psycopg.connect(  # type: ignore
        settings.database_url,
        connect_timeout=15,
        autocommit=True,
        row_factory=dict_row,
    )
    # search_path al schema de la agencia (las queries usan nombres sin prefijo)
    with conn.cursor() as cur:
        cur.execute(f'SET search_path TO {schema()}, public')
    return conn


def _get_conn():
    global _CONN
    if _CONN is None or _CONN.closed:
        _CONN = _connect()
    return _CONN


@contextmanager
def cursor():
    """Cursor serializado con reconexión en caso de conexión muerta."""
    global _CONN
    with _LOCK:
        try:
            conn = _get_conn()
            cur = conn.cursor()
        except Exception:
            _CONN = _connect()
            cur = _CONN.cursor()
        try:
            yield cur
        except Exception:
            # una conexión rota deja todo inservible → forzar reconexión la próxima
            try:
                if _CONN and not _CONN.closed:
                    _CONN.rollback()
            except Exception:
                pass
            raise
        finally:
            cur.close()


def fetchall(sql: str, params: Optional[Iterable[Any]] = None) -> List[Dict[str, Any]]:
    with cursor() as cur:
        cur.execute(sql, params or ())
        return list(cur.fetchall())


def fetchone(sql: str, params: Optional[Iterable[Any]] = None) -> Optional[Dict[str, Any]]:
    with cursor() as cur:
        cur.execute(sql, params or ())
        return cur.fetchone()


def execute(sql: str, params: Optional[Iterable[Any]] = None) -> None:
    with cursor() as cur:
        cur.execute(sql, params or ())


def healthcheck() -> Dict[str, Any]:
    if not enabled():
        return {"db": False, "reason": "DATABASE_URL no configurada o psycopg ausente"}
    try:
        row = fetchone("SELECT 1 AS ok")
        return {"db": True, "ok": bool(row and row.get("ok") == 1), "schema": schema()}
    except Exception as e:  # pragma: no cover
        return {"db": False, "error": f"{type(e).__name__}: {e}"}
