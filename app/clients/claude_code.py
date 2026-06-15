"""
ClaudeCodeRunner — ejecuta el CLI de Claude Code (headless, `claude -p`) usando
MiniMax-M3 como backend vía su endpoint compatible con Anthropic.

Esto le da a cada agente el harness real de Claude Code (tools Bash/WebFetch/
Read/Write/Glob/Grep + skills) manejado por el modelo barato de MiniMax, sin
ninguna API key nueva: reusa MINIMAX_API_KEY/BASE_URL/MODEL de la config.

Nota importante: la tool WebSearch de Claude Code es server-side de Anthropic y
NO funciona con backend MiniMax (devuelve 400). Por eso NO la habilitamos; el
descubrimiento se hace con WebFetch/Bash sobre directorios y sitios conocidos.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from typing import List, Optional

from ..config import Settings
from ..log import get_logger

log = get_logger("claude_code")

# Tools seguras por defecto para agentes (sin WebSearch: no anda con MiniMax).
# Skill = cargar skills; Task = subagentes (los usa la auditoría de páginas).
DEFAULT_ALLOWED_TOOLS = ["WebFetch", "Bash", "Read", "Write", "Edit", "Glob", "Grep", "Skill", "Task"]

# Modelo chico para tareas internas del harness (títulos, etc.).
SMALL_FAST_MODEL = "MiniMax-M2.5"


class ClaudeCodeError(Exception):
    """El CLI de claude no está disponible o falló."""


def _extract_result_json(out: str) -> Optional[dict]:
    """Extrae el objeto JSON del result envelope de `claude -p --output-format json`.

    Robusto ante ruido alrededor del JSON (logs/warnings que el CLI imprime antes o
    DESPUÉS del objeto). `json.loads(out)` falla con 'Extra data' si hay algo después
    del `}`; acá escaneamos cada `{` con raw_decode (que corta en el primer objeto
    válido) y nos quedamos con el dict que tenga `result`/`type=="result"`.
    """
    if not out:
        return None
    # Camino feliz: todo el stdout es el objeto JSON.
    try:
        data = json.loads(out)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    # Ruido alrededor: escanear objetos JSON con raw_decode.
    decoder = json.JSONDecoder()
    best: Optional[dict] = None
    idx = 0
    n = len(out)
    while idx < n:
        start = out.find("{", idx)
        if start == -1:
            break
        try:
            obj, end = decoder.raw_decode(out, start)
        except json.JSONDecodeError:
            idx = start + 1
            continue
        if isinstance(obj, dict):
            if obj.get("type") == "result" or "result" in obj:
                best = obj  # el último result gana (stream-json deja el final al cierre)
        idx = end
    return best


def claude_available() -> bool:
    return shutil.which("claude") is not None


def run_claude_code(
    prompt: str,
    *,
    settings: Settings,
    system_append: Optional[str] = None,
    allowed_tools: Optional[List[str]] = None,
    model: Optional[str] = None,
    timeout: int = 600,
) -> str:
    """Corre `claude -p <prompt>` headless con backend MiniMax y devuelve el texto final.

    Lanza ClaudeCodeError si el binario no existe o el run falla; el caller
    decide el fallback (p.ej. completion directa a MiniMax).
    """
    if not claude_available():
        raise ClaudeCodeError("CLI `claude` no encontrado en PATH")

    mm_model = model or settings.minimax_model_primary

    # Env del subproceso: apuntar Claude Code a MiniMax (endpoint Anthropic-compatible).
    env = dict(os.environ)
    env["ANTHROPIC_BASE_URL"] = settings.minimax_base_url.rstrip("/")
    env["ANTHROPIC_API_KEY"] = settings.minimax_api_key
    env["ANTHROPIC_MODEL"] = mm_model
    env["ANTHROPIC_SMALL_FAST_MODEL"] = SMALL_FAST_MODEL
    env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] = "1"
    env["DISABLE_TELEMETRY"] = "1"
    env["DISABLE_AUTOUPDATER"] = "1"
    # Render corre el container como root; Claude Code bloquea
    # --dangerously-skip-permissions con root salvo que se marque entorno sandbox.
    # El container es efímero/aislado → seguro habilitarlo.
    env["IS_SANDBOX"] = "1"
    env.setdefault("HOME", "/root")  # para que ~/.claude/skills se resuelva en el container

    cmd = [
        "claude", "-p", prompt,
        "--output-format", "json",
        "--model", mm_model,
        "--dangerously-skip-permissions",  # headless: sin prompts de permisos
    ]
    if allowed_tools is None:
        allowed_tools = DEFAULT_ALLOWED_TOOLS
    if allowed_tools:
        cmd += ["--allowedTools", *allowed_tools]
    if system_append:
        cmd += ["--append-system-prompt", system_append]

    # cwd temporal y aislado por run (Claude Code escribe estado de sesión ahí).
    workdir = tempfile.mkdtemp(prefix="cc_run_")
    try:
        proc = subprocess.run(
            cmd, cwd=workdir, env=env,
            capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired as e:
        log.error("claude_code_timeout", timeout=timeout)
        raise ClaudeCodeError(f"claude -p timeout tras {timeout}s") from e
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    if proc.returncode != 0:
        log.error("claude_code_failed", returncode=proc.returncode,
                  stderr=(proc.stderr or "")[:500])
        raise ClaudeCodeError(
            f"claude -p exit {proc.returncode}: {(proc.stderr or '')[:300]}"
        )

    out = (proc.stdout or "").strip()
    # --output-format json: objeto con campo `result` (texto final) + metadata.
    # Robusto ante ruido antes/después del objeto (evita postear el envelope crudo).
    data = _extract_result_json(out)
    if data is not None:
        text = data.get("result") or data.get("text") or ""
        if data.get("is_error"):
            log.warning("claude_code_result_is_error", subtype=data.get("subtype"))
        if text:
            log.info("claude_code_ok",
                     model=mm_model,
                     turns=data.get("num_turns"),
                     cost_usd=data.get("total_cost_usd"),
                     out_chars=len(text))
            return text.strip()
    # Fallback: no se pudo extraer texto del JSON → devolver stdout crudo.
    log.warning("claude_code_ok_raw", model=mm_model, out_chars=len(out))
    return out
