"""
HermesRunner — ejecuta el CLI de Hermes (hermes-agent, Nous Research) headless
(`hermes chat -q ... -Q --yolo`) como harness PRINCIPAL de todos los agentes.

Backend LLM: MiniMax-M3 (provider `minimax`, MINIMAX_API_KEY) por default; los
agentes con `llm_provider` ("glm"/"deepseek") corren con provider `nvidia` y su
modelo de siempre. Hermes lee las keys de las MISMAS env vars que ya usamos.

`hermes chat` no tiene flag de system prompt → se antepone al mensaje (igual
que run_opencode). Workdir temporal: evita que Hermes cargue el AGENTS.md del
repo y aísla los artefactos que deje.

Mismo contrato que run_opencode/run_claude_code: devuelve el texto final o
lanza HermesError (el caller decide el fallback: OpenCode → CC → NVIDIA → MiniMax).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from ..config import Settings
from ..log import get_logger
from .claude_code import _largest_text_artifact, run_cli_killtree
from .opencode import _extract_text, _has_json_payload

log = get_logger("hermes")

# HERMES_HOME en el VOLUMEN persistente (/app/data en Railway): las skills que
# los agentes crean/mejoran y la memoria de Hermes sobreviven corridas y deploys.
# Sin esto, el home del Dockerfile es efímero y el aprendizaje se pierde.
_HERMES_HOME = Path(__file__).resolve().parent.parent.parent / "data" / ".hermes"

# El review automático de skills/memoria de Hermes corre en un thread daemon
# DESPUÉS de responder → en modo one-shot el proceso sale antes y no aprende.
# Por eso el aprendizaje se pide EXPLÍCITO dentro del turno (skill_manage).
_LEARNING_BLOCK = (
    "## APRENDIZAJE CONTINUO (Hermes)\n"
    "Tus skills persisten entre corridas y las comparten todos los agentes de "
    "Automiq. Si esta tarea te dejó un aprendizaje PROCEDURAL durable (cómo hacer "
    "mejor un tipo de tarea concreto, un patrón que funciona, un gotcha a evitar), "
    "creá o actualizá una skill con tu tool de gestión de skills ANTES de terminar "
    "(nombre kebab-case en español, ej. 'cold-emails-automiq'). Si ya existe una "
    "skill relevante, mejorala en lugar de duplicar. No guardes obviedades ni cosas "
    "de un solo día. Este proceso es SILENCIOSO: tu respuesta final es SOLO el "
    "entregable de la tarea — nunca menciones skills ni aprendizajes en ella.\n\n"
)


class HermesError(Exception):
    """El CLI de hermes no está disponible o falló."""


def hermes_available() -> bool:
    return shutil.which("hermes") is not None


def _provider_model(llm_provider: str, s: Settings) -> tuple[str, str]:
    """provider lógico del agente → (provider hermes, modelo)."""
    if llm_provider == "glm" and getattr(s, "nvidia_api_key", ""):
        return "nvidia", getattr(s, "glm_model", "z-ai/glm-5.2")
    if llm_provider == "deepseek" and getattr(s, "nvidia_api_key", ""):
        return "nvidia", getattr(s, "deepseek_model", "deepseek-ai/deepseek-v4-pro")
    return "minimax", s.minimax_model_primary


# Vars con las que Hermes elige su backend de búsqueda. Las sacamos del entorno
# del hijo para que no gane ninguna: queremos que caiga SIEMPRE en nuestro shim.
# Nuestra cascada igual usa estas keys — las lee del entorno del PADRE.
#
# TAVILY_API_KEY quedó FUERA de esta lista a propósito: es la única que tenemos
# que sabe EXTRAER (searxng es search-only) y `_is_backend_available("tavily")`
# la busca en el entorno del hijo — sacándola, `web.extract_backend: tavily` no
# se aplicaba y el extract volvía a caer en searxng. Para la BÚSQUEDA no gana
# igual: `web.search_backend: searxng` del config.yaml se resuelve antes que
# cualquier variable de entorno (ver fijar_backend_busqueda).
_HERMES_SEARCH_KEYS = ("EXA_API_KEY", "PARALLEL_API_KEY",
                       "FIRECRAWL_API_KEY", "FIRECRAWL_API_URL",
                       "BRAVE_SEARCH_API_KEY")


def token_shim(webhook_secret: str) -> str:
    """Token EXCLUSIVO del shim de búsqueda, derivado del webhook secret.

    El shim autentica por PATH (el provider SearXNG de Hermes no manda headers),
    y Railway loguea la URL completa de cada request. Poniendo ahí el
    WEBHOOK_SECRET lo estábamos escribiendo en texto plano en los logs de acceso
    en CADA búsqueda — el mismo secreto que protege todos los endpoints.

    Derivarlo por HMAC corta la filtración: lo que queda en los logs sólo sirve
    para pedir búsquedas, y de él no se puede volver al secreto original.
    """
    import hashlib
    import hmac as _hmac
    return _hmac.new(webhook_secret.encode(), b"searx-shim-v1",
                     hashlib.sha256).hexdigest()[:32]


def _wire_search_backend(env: dict, settings: Settings, agente: str = "") -> None:
    """Apunta el `web_search` de Hermes a nuestra cascada vía el shim SearXNG.

    Hermes elige UN backend y NO reintenta con otro si falla. Con Tavily seteada
    lo elegía siempre; agotado su free tier (432) todos los agentes se quedaron
    ciegos y entregaron reportes armados de memoria. Nuestra cascada sí reintenta
    (Serper → Google CSE → Brave → Tavily → DDG), así que la ponemos de backend.

    Si no hay webhook_secret no podemos autenticar el shim → dejamos el entorno
    intacto y Hermes sigue con lo que tenga (peor, pero no peor que hoy).
    """
    if not getattr(settings, "webhook_secret", ""):
        return
    port = os.environ.get("PORT", "8000")
    env["SEARXNG_URL"] = (f"http://127.0.0.1:{port}/api/searx/"
                          f"{token_shim(settings.webhook_secret)}/"
                          f"{agente or 'desconocido'}")
    for k in _HERMES_SEARCH_KEYS:
        env.pop(k, None)


def sessions_cmd(*args: str, timeout: int = 300) -> dict:
    """Corre `hermes sessions <args>` contra NUESTRO HERMES_HOME (el del volumen).

    Existe porque `state.db` crece sin techo: el 2026-08-07 pesaba 263 MB de los
    330 usados del volumen, mientras que la media —lo único que mira el
    housekeeping— eran 8 MB. Hermes trae la poda (`sessions optimize`, que hace
    VACUUM sin tocar datos, y `sessions prune --older-than`), pero el volumen no
    tiene shell, así que hay que poder dispararla desde acá.
    """
    if not hermes_available():
        return {"ok": False, "error": "CLI `hermes` no encontrado en PATH"}
    env = dict(os.environ)
    _HERMES_HOME.mkdir(parents=True, exist_ok=True)
    env["HERMES_HOME"] = str(_HERMES_HOME)
    try:
        r = subprocess.run([shutil.which("hermes"), "sessions", *args],
                           capture_output=True, text=True, timeout=timeout, env=env)
        return {"ok": r.returncode == 0, "returncode": r.returncode,
                "stdout": (r.stdout or "")[-4000:], "stderr": (r.stderr or "")[-2000:]}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"timeout {timeout}s"}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {str(e)[:200]}"}


def sessions_sizes() -> dict:
    """Qué tabla ocupa el espacio DENTRO de state.db. SOLO LECTURA.

    Importa para decidir la retención: si el peso está en el índice FTS se
    recupera SIN borrar nada (mergeando segmentos), pero si está en el texto de
    los mensajes la única palanca es podar sesiones. A ojo no se distingue.
    """
    db = _HERMES_HOME / "state.db"
    if not db.is_file():
        return {"ok": False, "error": f"no existe {db}"}
    import sqlite3
    mb = lambda b: round((b or 0) / 1_048_576, 1)  # noqa: E731
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=60)
        try:
            try:
                # dbstat da el tamaño REAL en páginas por tabla/índice.
                filas = con.execute(
                    "SELECT name, SUM(pgsize) FROM dbstat GROUP BY name "
                    "ORDER BY 2 DESC LIMIT 12").fetchall()
                por_tabla = [{"nombre": n, "mb": mb(b)} for n, b in filas]
            except sqlite3.OperationalError:
                # sin dbstat compilado: aproximar por largo del texto guardado
                por_tabla = [{"nombre": "(dbstat no disponible)", "mb": None}]
            libres = con.execute("PRAGMA freelist_count").fetchone()[0]
            psize = con.execute("PRAGMA page_size").fetchone()[0]
        finally:
            con.close()
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {str(e)[:200]}"}
    return {"ok": True, "archivo_mb": mb(db.stat().st_size),
            # espacio ya borrado que VACUUM devolvería al disco
            "reclamable_por_vacuum_mb": mb(libres * psize),
            "por_tabla": por_tabla}


def sessions_probe() -> dict:
    """Por qué state.db dice "disk full" con el volumen a medio llenar. SOLO LECTURA.

    SQLITE_FULL sale tanto por disco lleno como por tocar `max_page_count`, y el
    mensaje es el mismo. Con 65 MB libres el borrado en lotes seguía muriendo, así
    que hay que separar las dos causas en vez de seguir probando.
    """
    db = _HERMES_HOME / "state.db"
    if not db.is_file():
        return {"ok": False, "error": f"no existe {db}"}
    import sqlite3
    out: dict = {}
    try:
        con = sqlite3.connect(str(db), timeout=60)
        try:
            for p in ("journal_mode", "page_size", "page_count", "max_page_count",
                      "freelist_count", "temp_store", "locking_mode"):
                try:
                    out[p] = con.execute(f"PRAGMA {p}").fetchone()[0]
                except Exception as e:
                    out[p] = f"err: {str(e)[:60]}"
            out["tamanio_maximo_mb"] = round(
                (out.get("max_page_count", 0) or 0) * (out.get("page_size", 0) or 0)
                / 1_048_576, 1) if isinstance(out.get("max_page_count"), int) else None
            # ¿se puede escribir? una tabla mínima que se borra enseguida
            try:
                con.execute("CREATE TABLE IF NOT EXISTS _probe_espacio (x INTEGER)")
                con.execute("INSERT INTO _probe_espacio VALUES (1)")
                con.commit()
                con.execute("DROP TABLE _probe_espacio")
                con.commit()
                out["escritura_minima"] = "ok"
            except Exception as e:
                out["escritura_minima"] = f"{type(e).__name__}: {str(e)[:120]}"
        finally:
            con.close()
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {str(e)[:200]}"}
    return {"ok": True, **out}


def hermes_gc() -> dict:
    """Borra basura de HERMES_HOME: .tmp huérfanos y logs. No toca state.db.

    Los `.models_dev_cache_*.tmp` son escrituras de caché que quedaron a medias
    (había 3, 5,7 MB). Los logs crecen sin rotar. Nada de esto se recupera ni
    hace falta: el caché se rebaja solo y los logs son de corridas viejas.
    """
    borrados, liberado = [], 0
    try:
        for p in _HERMES_HOME.glob("*.tmp"):
            try:
                n = p.stat().st_size
                p.unlink()
                borrados.append(p.name)
                liberado += n
            except Exception:
                continue
        for log_p in (_HERMES_HOME / "logs").glob("*.log"):
            try:
                n = log_p.stat().st_size
                # truncar, no borrar: Hermes puede tenerlo abierto
                with log_p.open("w"):
                    pass
                borrados.append(log_p.name + " (truncado)")
                liberado += n
            except Exception:
                continue
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {str(e)[:200]}"}
    return {"ok": True, "borrados": borrados,
            "liberado_mb": round(liberado / 1_048_576, 1)}


_TRIGRAM_TRIGGERS = ("messages_fts_trigram_insert", "messages_fts_trigram_delete",
                     "messages_fts_trigram_update")


def sessions_drop_trigram() -> dict:
    """Borra el índice FTS `trigram` de state.db. NO toca un solo mensaje.

    Medido el 2026-08-07: de 296 MB, los mensajes son 53 y las sesiones 10 — el
    79% son índices de búsqueda, y el texto está guardado TRES veces (en
    `messages` y una copia completa dentro de cada FTS). El trigram solo son
    162 MB: sirve para buscar por substring en el navegador de sesiones de
    Hermes, una UI que nosotros no usamos (leemos los reportes de nuestro store).

    Se puede borrar sin miedo porque `hermes_state.py` lo crea con
    `CREATE VIRTUAL TABLE IF NOT EXISTS` en cada arranque: si alguna vez hace
    falta, vuelve solo. Queda el FTS normal, así que la búsqueda por palabra
    sigue andando.

    Ojo: esto NO achica el archivo — deja las páginas en la free-list, que es
    espacio que las escrituras nuevas reusan. El efecto buscado es doble: frena
    el crecimiento (cada mensaje nuevo deja de pagar el índice más caro) y deja
    runway interno. Para devolverle los MB al volumen hace falta VACUUM.
    """
    db = _HERMES_HOME / "state.db"
    if not db.is_file():
        return {"ok": False, "error": f"no existe {db}"}
    import sqlite3
    mb = lambda b: round((b or 0) / 1_048_576, 1)  # noqa: E731
    antes = db.stat().st_size
    try:
        # timeout largo: puede haber un agente corriendo y escribiendo.
        con = sqlite3.connect(str(db), timeout=180)
        try:
            # state.db está en WAL: commitear NO devuelve las páginas al archivo
            # principal, se apilan en el `-wal` hasta que corre un checkpoint. Sin
            # forzarlo, borrar 162 MB en lotes hacía crecer el -wal hasta llenar el
            # volumen y morir con SQLITE_FULL — con espacio libre de sobra.
            con.execute("PRAGMA temp_store = MEMORY")   # y sin temporales en disco
            con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            hay = con.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' "
                "AND name='messages_fts_trigram'").fetchone()
            if not hay:
                return {"ok": True, "cambio": False,
                        "detalle": "el índice trigram ya no estaba"}
            msgs_antes = con.execute("SELECT count(*) FROM messages").fetchone()[0]
            # Primero los triggers: si se cayera el proceso justo después de
            # borrar la tabla, un trigger vivo escribiría contra algo que no
            # existe y reventaría CADA insert de mensaje.
            for t in _TRIGRAM_TRIGGERS:
                con.execute(f"DROP TRIGGER IF EXISTS {t}")
            con.commit()
            # Vaciar las shadow tables EN LOTES antes de soltar la virtual.
            # `DROP TABLE` sobre una FTS5 dispara xDestroy, que borra todas las
            # filas en UNA transacción y journalea el borrado entero: con el
            # volumen al 88% eso muere con "database or disk is full" — para
            # liberar espacio hacía falta espacio. En lotes con commit, el
            # journal nunca crece y las páginas van pasando a la free-list.
            for shadow in ("messages_fts_trigram_data", "messages_fts_trigram_content",
                           "messages_fts_trigram_docsize", "messages_fts_trigram_idx"):
                if not con.execute("SELECT 1 FROM sqlite_master WHERE type='table' "
                                   "AND name=?", (shadow,)).fetchone():
                    continue
                try:
                    while con.execute(f"SELECT 1 FROM {shadow} LIMIT 1").fetchone():
                        con.execute(f"DELETE FROM {shadow} WHERE rowid IN "
                                    f"(SELECT rowid FROM {shadow} LIMIT 200)")
                        con.commit()
                        # devuelve el -wal a cero en cada vuelta: es lo que evita
                        # que el borrado se coma el disco mientras libera espacio
                        con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                except sqlite3.OperationalError as e:
                    # `_idx` es WITHOUT ROWID → no se puede paginar por rowid.
                    # Es la shadow chica (0,2 MB de 162), así que va entera: su
                    # journal no es el que hace fallar el drop.
                    if "no such column: rowid" not in str(e):
                        raise
                    con.execute(f"DELETE FROM {shadow}")
                    con.commit()
            # Ahora las shadow están vacías → el xDestroy es barato.
            con.execute("DROP TABLE IF EXISTS messages_fts_trigram")
            con.commit()
            msgs = con.execute("SELECT count(*) FROM messages").fetchone()[0]
            integridad = con.execute("PRAGMA quick_check").fetchone()[0]
            libres = con.execute("PRAGMA freelist_count").fetchone()[0]
            psize = con.execute("PRAGMA page_size").fetchone()[0]
        finally:
            con.close()
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {str(e)[:200]}"}
    return {"ok": True, "cambio": True, "integridad": integridad,
            "mensajes_antes": msgs_antes, "mensajes_ahora": msgs,
            "archivo_mb": mb(antes),
            "liberado_interno_mb": mb(libres * psize)}


_TRIGRAM_SHADOWS = ("messages_fts_trigram_data", "messages_fts_trigram_idx",
                    "messages_fts_trigram_content", "messages_fts_trigram_docsize",
                    "messages_fts_trigram_config")


def sessions_purge_trigram_orphan() -> dict:
    """Saca del schema la tabla virtual `messages_fts_trigram` ya inservible.

    Vaciar las shadow en lotes esquivó el SQLITE_FULL, pero dejó la FTS5 sin su
    fila de estructura: desde ahí el constructor de la vtable falla, y como
    SQLite lo invoca al abrir la base, `DROP TABLE` tampoco entra. Hermes quedó
    con "Could not open session database".

    Único camino: borrar la entrada de `sqlite_master` con `writable_schema` y
    después soltar las shadow, que sin la vtable encima son tablas comunes (y
    están vacías, así que salen baratas). Se sube `schema_version` para que las
    otras conexiones recarguen el schema en vez de seguir con el roto en caché.
    """
    db = _HERMES_HOME / "state.db"
    if not db.is_file():
        return {"ok": False, "error": f"no existe {db}"}
    import sqlite3
    pasos: list[str] = []
    try:
        con = sqlite3.connect(str(db), timeout=180)
        try:
            con.execute("PRAGMA temp_store = MEMORY")
            ver = con.execute("PRAGMA schema_version").fetchone()[0]
            con.execute("PRAGMA writable_schema = ON")
            n = con.execute("DELETE FROM sqlite_master WHERE type='table' "
                            "AND name='messages_fts_trigram'").rowcount
            con.execute(f"PRAGMA schema_version = {ver + 1}")
            con.execute("PRAGMA writable_schema = OFF")
            con.commit()
            pasos.append(f"entrada de sqlite_master borrada ({n})")
        finally:
            con.close()
        # Reconectar: recién con el schema recargado las shadow son tablas comunes.
        con = sqlite3.connect(str(db), timeout=180)
        try:
            con.execute("PRAGMA temp_store = MEMORY")
            for shadow in _TRIGRAM_SHADOWS:
                if con.execute("SELECT 1 FROM sqlite_master WHERE type='table' "
                               "AND name=?", (shadow,)).fetchone():
                    con.execute(f"DROP TABLE IF EXISTS {shadow}")
                    con.commit()
                    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                    pasos.append(f"{shadow} borrada")
            integridad = con.execute("PRAGMA quick_check").fetchone()[0]
            msgs = con.execute("SELECT count(*) FROM messages").fetchone()[0]
            sesiones = con.execute("SELECT count(*) FROM sessions").fetchone()[0]
            libres = con.execute("PRAGMA freelist_count").fetchone()[0]
            psize = con.execute("PRAGMA page_size").fetchone()[0]
        finally:
            con.close()
    except Exception as e:
        return {"ok": False, "pasos": pasos, "error": f"{type(e).__name__}: {str(e)[:200]}"}
    return {"ok": True, "pasos": pasos, "integridad": integridad,
            "mensajes": msgs, "sesiones": sesiones,
            "archivo_mb": round(db.stat().st_size / 1_048_576, 1),
            "free_list_mb": round(libres * psize / 1_048_576, 1)}


def sessions_vacuum() -> dict:
    """VACUUM sobre state.db con el sqlite3 de Python. No cambia datos.

    Borrar sesiones NO achica el archivo: SQLite deja las páginas en la free-list
    y el .db sigue ocupando lo mismo en el volumen. Hermes trae `sessions
    optimize` para esto, pero la versión del contenedor no lo tiene (sus acciones
    son list/export/delete/prune/stats/rename/browse), así que lo hacemos acá:
    VACUUM es SQL estándar y no depende de la versión del CLI.
    """
    db = _HERMES_HOME / "state.db"
    if not db.is_file():
        return {"ok": False, "error": f"no existe {db}"}
    import sqlite3
    antes = db.stat().st_size
    try:
        con = sqlite3.connect(str(db), timeout=60)
        try:
            con.execute("VACUUM")
            con.commit()
        finally:
            con.close()
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {str(e)[:200]}"}
    despues = db.stat().st_size
    mb = lambda b: round(b / 1_048_576, 1)  # noqa: E731
    return {"ok": True, "mb_antes": mb(antes), "mb_despues": mb(despues),
            "liberado_mb": mb(antes - despues)}


def fijar_backend_busqueda() -> dict:
    """Fija `web.backend: searxng` en el config.yaml de Hermes. Llamar al arranque.

    Sacar TAVILY_API_KEY del entorno del hijo NO alcanza: `get_env_value()` de
    Hermes chequea os.environ y, si no está, CAE al `.env` de HERMES_HOME — que
    para nosotros vive en el volumen persistente. Si la key quedó ahí de un setup
    viejo, el borrado es decorativo y Hermes sigue eligiendo Tavily (agotada).

    `web.backend` del config.yaml gana ANTES de toda esa resolución por variables
    (`_get_backend()` lo lee primero), así que es el único punto determinístico.
    """
    try:
        import yaml
        _HERMES_HOME.mkdir(parents=True, exist_ok=True)
        path = _HERMES_HOME / "config.yaml"
        cfg = {}
        if path.is_file():
            cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        web = cfg.get("web") or {}
        # extract_backend EXPLÍCITO. Antes se dejaba sin setear "para no romper el
        # extract", pero era justo al revés: `_get_capability_backend("extract")`
        # cae a `web.backend` cuando no hay override, o sea a searxng, que es
        # search-only → `web_extract` devolvía "search-only backend" SIEMPRE. Los
        # agentes lo venían reportando como "web_extract caído" desde el 21/07.
        extract = "tavily" if os.environ.get("TAVILY_API_KEY") else ""
        if (web.get("backend") == "searxng" and web.get("search_backend") == "searxng"
                and (web.get("extract_backend") or "") == extract):
            return {"ok": True, "cambio": False, "backend": "searxng",
                    "extract_backend": extract}
        web["backend"] = "searxng"
        web["search_backend"] = "searxng"
        if extract:
            web["extract_backend"] = extract
        cfg["web"] = web
        path.write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False),
                        encoding="utf-8")
        log.info("hermes_backend_fijado", backend="searxng",
                 extract_backend=extract or "(ninguno)", path=str(path))
        return {"ok": True, "cambio": True, "backend": "searxng",
                "extract_backend": extract}
    except Exception as e:
        log.warning("hermes_backend_fijar_failed", error=str(e)[:200])
        return {"ok": False, "error": str(e)[:200]}


def run_hermes(
    prompt: str,
    *,
    settings: Settings,
    llm_provider: str = "",
    system_append: Optional[str] = None,
    timeout: int = 600,
    max_turns: int = 15,
    cwd: Optional[str] = None,
    toolsets: Optional[str] = None,
    agente: str = "",
) -> str:
    """Corre `hermes chat -q` headless y devuelve el texto final.

    `cwd`: si se pasa, Hermes corre EN ese directorio (en vez de un temp aislado)
    → permite que un agente edite un proyecto ya clonado en disco (web_optimizer).
    OJO: en ese caso el directorio NO se borra y no se escanea buscando artefactos
    (el entregable es el texto impreso, y el proyecto puede tener miles de .md).

    `toolsets`: override del set de tools. Sirve para SACAR capacidades a un
    agente concreto (p.ej. web_optimizer no debe tener terminal: el deploy lo
    hace Python después de revisar, no el modelo por su cuenta).
    """
    if not hermes_available():
        raise HermesError("CLI `hermes` no encontrado en PATH")
    provider, model = _provider_model(llm_provider, settings)
    if provider == "minimax" and not settings.minimax_api_key:
        raise HermesError("sin MINIMAX_API_KEY")

    full_prompt = _LEARNING_BLOCK + prompt
    if system_append:
        full_prompt = (f"## INSTRUCCIONES DE SISTEMA (tu rol y reglas — cumplilas SIEMPRE)\n"
                       f"{system_append}\n\n{_LEARNING_BLOCK}## TAREA\n{prompt}")

    env = dict(os.environ)
    try:
        _HERMES_HOME.mkdir(parents=True, exist_ok=True)
        env["HERMES_HOME"] = str(_HERMES_HOME)
    except Exception as e:
        log.warning("hermes_home_fallback_ephemeral", error=str(e)[:120])

    _wire_search_backend(env, settings, agente)

    # Detección del cuelgue del tier gratis de NVIDIA. Hermes YA lo detecta y
    # reintenta (2 reintentos) conservando los turnos hechos, pero con su default
    # de 120s el reintento arrancaba recién pasada la mitad de nuestro corte de
    # proceso (180s) → lo matábamos en el medio y se perdía la corrida entera.
    # OJO: httpx lo usa como `read`, que es tiempo SIN RECIBIR BYTES, no total —
    # bajarlo NO estrangula una respuesta larga sana, solo detecta antes el
    # silencio. Y 60s de silencio es inequívoco: los turnos sanos tardan ~6s
    # (el run ENTERO, 15 turnos y 30k chars, son 90s medidos).
    # MiniMax no se toca: más lento por llamada y nunca mostró este cuelgue.
    if provider == "nvidia":
        env["HERMES_STREAM_READ_TIMEOUT"] = "60"

    # El stdout/stderr van SIEMPRE a un temp propio: si `cwd` es un proyecto real,
    # escribir los .bin adentro lo ensuciaría y el rmtree del final lo borraría.
    io_dir = tempfile.mkdtemp(prefix="hermes_io_")
    stdout_path = os.path.join(io_dir, "_hermes_stdout.bin")
    stderr_path = os.path.join(io_dir, "_hermes_stderr.bin")
    own_workdir = cwd is None
    workdir = cwd or tempfile.mkdtemp(prefix="hermes_run_")
    exe = shutil.which("hermes") or "hermes"
    # Toolsets acotados: los defaults incluyen browser (automatización de
    # navegador — rabbit hole que hizo timeout a growth_hacker), clarify
    # (preguntas aclaratorias: veneno en headless), delegation, computer_use,
    # tts, image_gen (las imágenes las maneja nuestra app). Set de laburo:
    cmd = [exe, "chat", "-q", full_prompt, "-Q", "--yolo",
           "--max-turns", str(max_turns), "-m", model, "--provider", provider,
           "-t", toolsets or "web,terminal,file,code_execution,skills,memory,todo",
           "--ignore-user-config"]
    try:
        with open(stdout_path, "wb") as fout, open(stderr_path, "wb") as ferr:
            returncode = run_cli_killtree(cmd, cwd=workdir, env=env,
                                          stdout_file=fout, stderr_file=ferr,
                                          timeout=timeout)
        with open(stdout_path, "rb") as f:
            stdout_s = f.read().decode("utf-8", errors="replace")
        with open(stderr_path, "rb") as f:
            stderr_s = f.read().decode("utf-8", errors="replace")
        # Rescate de artefacto SOLO con workdir propio/efímero: si el caller pasó
        # su `cwd` (proyecto real), el entregable es el texto impreso y escanear
        # miles de .md del proyecto traería cualquier cosa.
        artifact = (_largest_text_artifact(workdir, exclude={stdout_path, stderr_path})
                    if own_workdir else None)
    except subprocess.TimeoutExpired as e:
        log.error("hermes_timeout", timeout=timeout)
        raise HermesError(f"hermes chat timeout tras {timeout}s") from e
    finally:
        shutil.rmtree(io_dir, ignore_errors=True)
        if own_workdir:
            shutil.rmtree(workdir, ignore_errors=True)

    if returncode != 0:
        # Con -Q el error real suele quedar en stdout (stderr trae solo el
        # session_id) → loguear ambos para poder diagnosticar en prod.
        log.error("hermes_failed", returncode=returncode, stderr=stderr_s[:400],
                  stdout_tail=stdout_s[-600:])
        raise HermesError(f"hermes exit {returncode}: {(stdout_s[-200:] or stderr_s[:200])}")

    text = _extract_text(stdout_s)
    # igual que opencode: si dejó un entregable más completo en un archivo,
    # usarlo — salvo que lo impreso ya sea un payload JSON estructurado.
    art = (artifact or "").strip()
    if art and len(art) > max(int(len(text) * 1.2), 1000) and not _has_json_payload(text):
        log.info("hermes_artifact_recovered", printed=len(text), artifact=len(art))
        text = art
    if not text:
        raise HermesError(f"hermes sin output (stderr: {stderr_s[:200]})")
    log.info("hermes_ok", provider=provider, model=model, out_chars=len(text))
    return text
