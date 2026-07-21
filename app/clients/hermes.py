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
_HERMES_SEARCH_KEYS = ("TAVILY_API_KEY", "EXA_API_KEY", "PARALLEL_API_KEY",
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
        if web.get("backend") == "searxng" and web.get("search_backend") == "searxng":
            return {"ok": True, "cambio": False, "backend": "searxng"}
        web["backend"] = "searxng"
        web["search_backend"] = "searxng"
        # extract_backend NO se toca: searxng no sabe extraer (supports_extract()
        # es False) y pisarlo dejaría a los agentes sin poder leer páginas.
        cfg["web"] = web
        path.write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False),
                        encoding="utf-8")
        log.info("hermes_backend_fijado", backend="searxng", path=str(path))
        return {"ok": True, "cambio": True, "backend": "searxng"}
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
