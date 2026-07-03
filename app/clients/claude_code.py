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
import re
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


# strict=False permite caracteres de control crudos (saltos de línea sin escapar,
# etc.) DENTRO de los strings JSON. El CLI con backend MiniMax a veces emite el
# reporte con un \n real en vez de \\n → el json estricto lo rechaza ("Invalid
# control character") y caíamos al fallback que posteaba el envelope crudo.
_LENIENT_DECODER = json.JSONDecoder(strict=False)
# Último recurso: rescatar el valor del campo "result" aunque el objeto entero esté
# roto O TRUNCADO. [^"\\] matchea cualquier char (incluido \n crudo) salvo comilla y
# backslash. La comilla de cierre es OPCIONAL a propósito: si el stdout viene cortado
# a mitad del result (envelope sin cerrar), igual rescatamos lo que llegó. Cuando el
# result sí cierra, el grupo para en la comilla → mismo resultado que antes.
_RESULT_FIELD_RE = re.compile(r'"result"\s*:\s*"((?:\\.|[^"\\])*)', re.DOTALL)


def _extract_result_json(out: str) -> Optional[dict]:
    """Extrae el objeto JSON del result envelope de `claude -p --output-format json`.

    Robusto ante (1) ruido alrededor del JSON (logs antes/después del objeto),
    (2) caracteres de control crudos dentro de los strings (strict=False), y
    (3) JSON irreparable (regex de último recurso sobre el campo "result").
    """
    if not out:
        return None
    # Camino feliz / tolerante: todo el stdout es el objeto JSON.
    try:
        data = _LENIENT_DECODER.decode(out)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    # Ruido alrededor: escanear objetos JSON con raw_decode (también lenient).
    best: Optional[dict] = None
    idx = 0
    n = len(out)
    while idx < n:
        start = out.find("{", idx)
        if start == -1:
            break
        try:
            obj, end = _LENIENT_DECODER.raw_decode(out, start)
        except json.JSONDecodeError:
            idx = start + 1
            continue
        if isinstance(obj, dict) and (obj.get("type") == "result" or "result" in obj):
            best = obj  # el último result gana (stream-json deja el final al cierre)
            idx = end
        else:
            idx = end if end > start else start + 1
    if best is not None:
        return best
    # Último recurso: el JSON es irreparable o vino TRUNCADO, pero el campo "result"
    # sigue ahí (entero o cortado). Rescatamos el texto crudo del entregable.
    m = _RESULT_FIELD_RE.search(out)
    if m:
        frag = m.group(1)
        # Si el corte cayó en medio de un escape, el último backslash queda colgando
        # y rompe el re-decode ("unterminated escape"). Lo soltamos si es impar.
        trailing_bs = len(frag) - len(frag.rstrip("\\"))
        if trailing_bs % 2 == 1:
            frag = frag[:-1]
        try:
            text = _LENIENT_DECODER.decode(f'"{frag}"')
            if isinstance(text, str) and text.strip():
                # ¿El envelope cerró bien? Si no termina en "}" lo más probable es
                # que stdout viniera truncado en transporte.
                truncated = not out.rstrip().endswith("}")
                return {"result": text, "_recovered": "truncated" if truncated else "regex"}
        except json.JSONDecodeError:
            pass
    return None


def _largest_text_artifact(workdir: str, exclude: set) -> Optional[str]:
    """Devuelve el contenido del .md/.txt más grande que el modelo dejó en el workdir.

    Algunos agentes (p.ej. leadhunter) a veces ESCRIBEN el entregable a un archivo y
    sólo imprimen un resumen corto como respuesta final → perderíamos el reporte
    completo (el workdir es efímero). Rescatamos el artefacto más grande para no
    quedarnos con el resumen.
    """
    best_size = 0
    best_text: Optional[str] = None
    for root, _dirs, files in os.walk(workdir):
        for fn in files:
            if not fn.lower().endswith((".md", ".markdown", ".txt")):
                continue
            p = os.path.join(root, fn)
            if p in exclude:
                continue
            try:
                sz = os.path.getsize(p)
                if sz <= best_size:
                    continue
                with open(p, "rb") as f:
                    best_text = f.read().decode("utf-8", errors="replace")
                best_size = sz
            except OSError:
                continue
    return best_text


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
    cwd: Optional[str] = None,
    extra_env: Optional[dict] = None,
    mcp_servers: Optional[dict] = None,
) -> str:
    """Corre `claude -p <prompt>` headless con backend MiniMax y devuelve el texto final.

    Lanza ClaudeCodeError si el binario no existe o el run falla; el caller
    decide el fallback (p.ej. completion directa a MiniMax).

    `cwd`: si se pasa, Claude Code corre EN ese directorio (en vez de un temp aislado)
    → permite que un agente edite un repo/proyecto ya clonado en disco (web_optimizer).
    `extra_env`: variables extra para el subproceso (p.ej. tokens de deploy).
    `mcp_servers`: dict estilo {"nombre": {"type": "http", "url": ..., "headers": ...}}
    → se pasa vía --mcp-config; el caller debe permitir sus tools (`mcp__<nombre>`).
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
    if extra_env:
        env.update({k: str(v) for k, v in extra_env.items() if v is not None})

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

    # Directorio de I/O (siempre temporal) para los .bin de stdout/stderr.
    io_dir = tempfile.mkdtemp(prefix="cc_io_")
    if mcp_servers:
        mcp_path = os.path.join(io_dir, "_mcp.json")
        with open(mcp_path, "w", encoding="utf-8") as f:
            json.dump({"mcpServers": mcp_servers}, f)
        cmd += ["--mcp-config", mcp_path]
    # Directorio de ejecución: si el caller pasó `cwd`, corremos AHÍ (repo/proyecto
    # real a editar); si no, un temp aislado por run (comportamiento default).
    own_workdir = cwd is None
    workdir = cwd or tempfile.mkdtemp(prefix="cc_run_")
    # Redirigimos stdout/stderr a ARCHIVOS, no a pipes. CAUSA RAÍZ de la truncación:
    # `claude` (CLI de Node) escribe el JSON final de una sola vez y hace process.exit;
    # sobre un PIPE la escritura es asíncrona y el proceso sale antes de que libuv
    # drene el buffer → stdout truncado a mitad del `result` (envelope sin cerrar, con
    # un multibyte partido → '�'). Sobre un fd de archivo REGULAR las escrituras de
    # Node son SÍNCRONAS → el envelope se escribe entero. Leemos el archivo después.
    stdout_path = os.path.join(io_dir, "_cc_stdout.bin")
    stderr_path = os.path.join(io_dir, "_cc_stderr.bin")
    try:
        with open(stdout_path, "wb") as fout, open(stderr_path, "wb") as ferr:
            proc = subprocess.run(
                cmd, cwd=workdir, env=env,
                stdout=fout, stderr=ferr, timeout=timeout,
            )
        with open(stdout_path, "rb") as f:
            stdout_b = f.read()
        with open(stderr_path, "rb") as f:
            stderr_b = f.read()
        # Rescate de artefacto sólo cuando usamos un workdir propio/efímero. Si el
        # caller pasó su `cwd` (repo real), NO escaneamos: el entregable es el texto
        # impreso, no un .md suelto, y el repo puede tener miles de archivos.
        artifact = None
        if own_workdir:
            artifact = _largest_text_artifact(workdir, exclude={stdout_path, stderr_path})
    except subprocess.TimeoutExpired as e:
        log.error("claude_code_timeout", timeout=timeout)
        raise ClaudeCodeError(f"claude -p timeout tras {timeout}s") from e
    finally:
        shutil.rmtree(io_dir, ignore_errors=True)
        if own_workdir:
            shutil.rmtree(workdir, ignore_errors=True)

    # Decodificamos con errors="replace" igual, por si el backend emite algún byte
    # UTF-8 inválido suelto (no debe abortar la lectura).
    stdout_s = stdout_b.decode("utf-8", errors="replace")
    stderr_s = stderr_b.decode("utf-8", errors="replace")

    if proc.returncode != 0:
        log.error("claude_code_failed", returncode=proc.returncode,
                  stderr=stderr_s[:500])
        raise ClaudeCodeError(
            f"claude -p exit {proc.returncode}: {stderr_s[:300]}"
        )

    out = stdout_s.strip()
    # --output-format json: objeto con campo `result` (texto final) + metadata.
    # Robusto ante ruido antes/después del objeto (evita postear el envelope crudo).
    data = _extract_result_json(out)
    text = ""
    recovered = None
    if data is not None:
        text = (data.get("result") or data.get("text") or "").strip()
        recovered = data.get("_recovered")  # None | "regex" | "truncated"
        if data.get("is_error"):
            log.warning("claude_code_result_is_error", subtype=data.get("subtype"))

    # Si el modelo dejó un entregable MÁS COMPLETO en un archivo del workdir que lo que
    # imprimió (resumen corto), preferimos el archivo. Umbral holgado para no pisar un
    # output ya completo con algún scratch chico.
    art = (artifact or "").strip()
    if art and len(art) > max(int(len(text) * 1.2), 1000):
        log.info("claude_code_artifact_recovered",
                 model=mm_model, printed_chars=len(text), artifact_chars=len(art))
        text = art
        recovered = "artifact"

    if text:
        log.info("claude_code_ok",
                 model=mm_model,
                 turns=data.get("num_turns") if data else None,
                 cost_usd=data.get("total_cost_usd") if data else None,
                 recovered=recovered,  # None | "regex" | "truncated" | "artifact"
                 out_chars=len(text))
        return text.strip()
    # Fallback: no se pudo extraer texto del JSON → devolver stdout crudo.
    log.warning("claude_code_ok_raw", model=mm_model, out_chars=len(out))
    return out
