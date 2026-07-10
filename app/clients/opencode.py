"""
OpenCodeRunner — ejecuta el CLI de OpenCode (headless, `opencode run`) con los
modelos de NVIDIA (GLM 5.2 / DeepSeek V4 Pro) como backend.

Por qué: los agentes con `llm_provider` corrían por completion directa SIN tools
ni skills (las instrucciones de "cargá la skill X" y "hacé WebFetch" eran letra
muerta). OpenCode les da un harness real — bash/read/write/webfetch + la tool
`skill` — y lee NUESTRAS skills de `.claude/skills/` sin cambios (formato
Claude-compatible). El provider se define en `opencode.json` (repo root →
copiado a /root/.config/opencode/ en el Dockerfile), key vía {env:NVIDIA_API_KEY}.

Mismo contrato que claude_code.run_claude_code: devuelve el texto final o lanza
OpenCodeError (el caller decide el fallback: NVIDIA directo → CC → MiniMax).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from typing import Optional

from ..config import Settings
from ..log import get_logger
from .claude_code import _largest_text_artifact, run_cli_killtree

log = get_logger("opencode")


class OpenCodeError(Exception):
    """El CLI de opencode no está disponible o falló."""


def opencode_available() -> bool:
    return shutil.which("opencode") is not None


def model_ref(provider: str, s: Settings) -> str:
    """provider lógico ('glm'|'deepseek') → ref de opencode 'nvidia/<model-id>'."""
    mid = {"glm": getattr(s, "glm_model", "z-ai/glm-5.2"),
           "deepseek": getattr(s, "deepseek_model", "deepseek-ai/deepseek-v4-pro")
           }.get(provider, getattr(s, "glm_model", "z-ai/glm-5.2"))
    return f"nvidia/{mid}"


_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]")


def _extract_text(out: str) -> str:
    """Extrae el texto final del stdout de `opencode run`.

    Con --print-logs los logs van a stderr; stdout debería ser el texto plano de
    la respuesta. Toleramos igual: JSON envelope, ndjson de eventos, o texto con
    códigos ANSI.
    """
    out = (out or "").strip()
    if not out:
        return ""
    # ¿JSON? (objeto único o ndjson de eventos con partes de texto)
    if out.lstrip().startswith(("{", "[")):
        try:
            data = json.loads(out)
            if isinstance(data, dict):
                for k in ("result", "text", "output", "message"):
                    if isinstance(data.get(k), str) and data[k].strip():
                        return data[k].strip()
            if isinstance(data, list):
                parts = [p.get("text", "") for p in data
                         if isinstance(p, dict) and p.get("text")]
                if parts:
                    return "\n".join(parts).strip()
        except json.JSONDecodeError:
            texts = []
            for line in out.splitlines():
                line = line.strip()
                if not line.startswith("{"):
                    continue
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(ev, dict):
                    t = (ev.get("text") or (ev.get("part") or {}).get("text") or "")
                    # SOLO eventos de texto del mensaje (type text/message o sin
                    # type). Antes un `or True` anulaba el filtro y se concatenaba
                    # el text de eventos de tools/steps → entregable contaminado.
                    if t and ev.get("type") in ("text", "message", None):
                        texts.append(t)
            if texts:
                return "".join(texts).strip()
    return _ANSI_RE.sub("", out).strip()


def _has_json_payload(text: str) -> bool:
    """¿El texto impreso ya contiene un array/objeto JSON sustancial? Si sí, es
    probablemente el entregable de un agente con contrato estructurado (outbound/
    inbox) y NO hay que pisarlo con un .md que la skill dejó en el workdir."""
    t = (text or "").strip()
    if not t:
        return False
    if t.startswith(("[", "{")):
        return True
    m = re.search(r"\[\s*\{", t)
    return bool(m)


def run_opencode(
    prompt: str,
    *,
    settings: Settings,
    provider: str = "glm",
    system_append: Optional[str] = None,
    timeout: int = 600,
) -> str:
    """Corre `opencode run` headless con el modelo NVIDIA dado y devuelve el texto.

    `opencode run` no tiene flag de system prompt → se antepone al mensaje (los
    modelos chat lo respetan bien como bloque inicial marcado).

    Sampling: el CLI tampoco acepta temperature/max_tokens por corrida — la
    temperatura se fija POR MODELO en opencode.json (glm 0.65 copy, deepseek
    0.45 razonamiento, aproximando los valores de los agentes que los usan).
    """
    if not opencode_available():
        raise OpenCodeError("CLI `opencode` no encontrado en PATH")
    if not getattr(settings, "nvidia_api_key", ""):
        raise OpenCodeError("sin NVIDIA_API_KEY")

    full_prompt = prompt
    if system_append:
        full_prompt = (f"## INSTRUCCIONES DE SISTEMA (tu rol y reglas — cumplilas SIEMPRE)\n"
                       f"{system_append}\n\n## TAREA\n{prompt}")

    env = dict(os.environ)
    env.setdefault("HOME", "/root")   # ~/.claude/skills y ~/.config/opencode en el container
    env["OPENCODE_DISABLE_AUTOUPDATE"] = "1"

    workdir = tempfile.mkdtemp(prefix="oc_run_")
    stdout_path = os.path.join(workdir, "_oc_stdout.bin")
    stderr_path = os.path.join(workdir, "_oc_stderr.bin")
    # shutil.which: en Windows el binario es opencode.CMD y subprocess no lo
    # resuelve solo; en Linux devuelve el path normal. Mismo código en ambos.
    exe = shutil.which("opencode") or "opencode"
    cmd = [exe, "run", full_prompt,
           "-m", model_ref(provider, settings)]
    try:
        with open(stdout_path, "wb") as fout, open(stderr_path, "wb") as ferr:
            returncode = run_cli_killtree(cmd, cwd=workdir, env=env,
                                          stdout_file=fout, stderr_file=ferr,
                                          timeout=timeout)
        with open(stdout_path, "rb") as f:
            stdout_s = f.read().decode("utf-8", errors="replace")
        with open(stderr_path, "rb") as f:
            stderr_s = f.read().decode("utf-8", errors="replace")
        artifact = _largest_text_artifact(workdir, exclude={stdout_path, stderr_path})
    except subprocess.TimeoutExpired as e:
        log.error("opencode_timeout", timeout=timeout)
        raise OpenCodeError(f"opencode run timeout tras {timeout}s") from e
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    if returncode != 0:
        log.error("opencode_failed", returncode=returncode, stderr=stderr_s[:400])
        raise OpenCodeError(f"opencode exit {returncode}: {stderr_s[:300]}")

    text = _extract_text(stdout_s)
    # igual que claude_code: si dejó un entregable más completo en un archivo,
    # usarlo — SALVO que lo impreso ya sea un payload JSON (contrato estructurado
    # de outbound/inbox: un .md de la skill NO debe pisar el array parseable).
    art = (artifact or "").strip()
    if art and len(art) > max(int(len(text) * 1.2), 1000) and not _has_json_payload(text):
        log.info("opencode_artifact_recovered", printed=len(text), artifact=len(art))
        text = art
    if not text:
        raise OpenCodeError(f"opencode sin output (stderr: {stderr_s[:200]})")
    log.info("opencode_ok", provider=provider, out_chars=len(text))
    return text
