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
from typing import Optional

from ..config import Settings
from ..log import get_logger
from .claude_code import _largest_text_artifact, run_cli_killtree
from .opencode import _extract_text, _has_json_payload

log = get_logger("hermes")


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


def run_hermes(
    prompt: str,
    *,
    settings: Settings,
    llm_provider: str = "",
    system_append: Optional[str] = None,
    timeout: int = 600,
    max_turns: int = 15,
) -> str:
    """Corre `hermes chat -q` headless y devuelve el texto final."""
    if not hermes_available():
        raise HermesError("CLI `hermes` no encontrado en PATH")
    provider, model = _provider_model(llm_provider, settings)
    if provider == "minimax" and not settings.minimax_api_key:
        raise HermesError("sin MINIMAX_API_KEY")

    full_prompt = prompt
    if system_append:
        full_prompt = (f"## INSTRUCCIONES DE SISTEMA (tu rol y reglas — cumplilas SIEMPRE)\n"
                       f"{system_append}\n\n## TAREA\n{prompt}")

    env = dict(os.environ)

    workdir = tempfile.mkdtemp(prefix="hermes_run_")
    stdout_path = os.path.join(workdir, "_hermes_stdout.bin")
    stderr_path = os.path.join(workdir, "_hermes_stderr.bin")
    exe = shutil.which("hermes") or "hermes"
    cmd = [exe, "chat", "-q", full_prompt, "-Q", "--yolo",
           "--max-turns", str(max_turns), "-m", model, "--provider", provider,
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
        artifact = _largest_text_artifact(workdir, exclude={stdout_path, stderr_path})
    except subprocess.TimeoutExpired as e:
        log.error("hermes_timeout", timeout=timeout)
        raise HermesError(f"hermes chat timeout tras {timeout}s") from e
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    if returncode != 0:
        log.error("hermes_failed", returncode=returncode, stderr=stderr_s[:400])
        raise HermesError(f"hermes exit {returncode}: {stderr_s[:300]}")

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
