"""
BaseAgent — clase base para todos los agentes de Automiq.

Cada subclase define:
- name: identificador único
- description: para qué sirve
- system_prompt: instrucciones para MiniMax-M3
- schedule: cron expression (None si solo manual)
- run(ctx) -> str: ejecuta y devuelve el output a entregar

El context trae: client (MiniMax), discord (webhook), logger, settings, run_id, args.
"""
from __future__ import annotations

import json
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

import pytz
from apscheduler.triggers.cron import CronTrigger

from ..clients.minimax import MiniMaxClient, MiniMaxResponse, MiniMaxError
from ..clients.claude_code import run_claude_code, ClaudeCodeError
from ..clients.discord import DiscordWebhook
from ..log import get_logger, write_run_log
from ..config import Settings
from ._common import sanitize_model_text

log = get_logger("agent")


@dataclass
class AgentContext:
    settings: Settings
    minimax: MiniMaxClient
    discord: Optional[DiscordWebhook]
    run_id: str
    triggered_by: str                # "cron" | "webhook" | "manual"
    args: Dict[str, Any]            # argumentos del trigger


class BaseAgent(ABC):
    name: str = "base"
    description: str = ""
    schedule: Optional[str] = None  # cron expr
    timezone: str = "America/Buenos_Aires"
    enabled: bool = True
    deliver_to_discord: bool = True
    max_tokens: int = 6000
    temperature: float = 0.7
    # ── Claude Code runner (harness real con MiniMax de backend) ──
    # Si use_claude_code=True, el agente corre vía `claude -p` headless (tools
    # reales + skills) en vez de una completion directa. Fallback automático a
    # MiniMax si el CLI no está disponible o falla.
    use_claude_code: bool = False
    claude_code_tools: Optional[List[str]] = None  # None → DEFAULT_ALLOWED_TOOLS
    claude_code_timeout: int = 600
    claude_code_skill: Optional[str] = None  # nombre de skill a cargar (tool Skill)

    # ── Tool use (online mode, path MiniMax directo) ──
    # Subclases que quieran correr "online" definen `tools` (schemas Anthropic
    # {name, description, input_schema}) y `tool_executors` (name -> callable).
    # Si `tools` está vacío, el agente corre en modo texto puro (como antes).
    max_tool_iterations: int = 8

    @property
    def tools(self) -> List[Dict[str, Any]]:
        return []

    @property
    def tool_executors(self) -> Dict[str, Callable[..., Any]]:
        return {}

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if cls.name == "base" or cls.name == BaseAgent.name:
            return
        # Auto-registro en la registry global
        from .registry import register_agent
        register_agent(cls())

    @property
    @abstractmethod
    def system_prompt(self) -> str:
        ...

    @abstractmethod
    def build_user_message(self, ctx: AgentContext) -> str:
        """Construye el mensaje user que dispara al agente."""
        ...

    def post_process(self, response_text: str, ctx: AgentContext) -> str:
        """Persistencia genérica best-effort: deja el output en
        data/<name>-report-YYYY-MM-DD.md para que /last lo sirva. Las subclases
        con lógica especial (p.ej. leadhunter) lo sobreescriben."""
        try:
            from pathlib import Path
            from datetime import datetime
            import pytz as _pytz
            today = datetime.now(_pytz.timezone(self.timezone)).strftime("%Y-%m-%d")
            data_dir = Path(__file__).resolve().parent.parent.parent / "data"
            data_dir.mkdir(exist_ok=True)
            fname = f"{self.name.replace('_', '-')}-report-{today}.md"
            (data_dir / fname).write_text((response_text or "").strip() + "\n", encoding="utf-8")
        except Exception as e:
            log.warning("post_process_persist_failed", agent=self.name, error=str(e))
        return response_text

    # ── Memoria de la agencia (contexto + aprendizaje) ──

    def _augment_with_memory(self, user_msg: str, ctx: AgentContext) -> str:
        """Inyecta contexto de empresa + lecciones + memoria del cliente al prompt."""
        from ..integrations import memory_store as ms
        blocks: List[str] = []
        company = ms.company_digest()
        if company:
            blocks.append("## CONTEXTO DE AUTOMIQ (memoria general)\n" + company)
        lessons = ms.lessons_for(self.name)
        if lessons:
            blocks.append("## " + lessons)
        # cliente objetivo (args.client_id) → su memoria acumulada
        cid = ctx.args.get("client_id") if isinstance(ctx.args, dict) else None
        if cid:
            try:
                from ..integrations import client_memory_store as cms, clients_store as cs
                client = cs.get_client(cid)
                # Cliente descartado → memoria congelada: no la inyectamos.
                if client and client.get("stage") not in cs.FROZEN_STAGES:
                    from ..integrations import localization as loc
                    blocks.append(f"## CLIENTE OBJETIVO: {client.get('name')} "
                                  f"({client.get('vertical') or 's/vertical'}) — "
                                  f"{loc.label(client.get('country'))} — etapa {client.get('stage')}")
                    # Localización: moneda/tratamiento/regulación del país del cliente.
                    blocks.append(loc.locale_block(client.get("country")))
                    digest = cms.context_digest(cid)
                    if digest:
                        blocks.append("## MEMORIA DEL CLIENTE (lo que ya sabemos de él)\n" + digest)
            except Exception:
                pass
        if not blocks:
            return user_msg
        header = "\n\n".join(blocks)
        return (f"{header}\n\nUsá ese contexto para que tu trabajo sea coherente con la "
                f"empresa, los objetivos y lo aprendido.\n\n---\n\n{user_msg}")

    def _persist_client_report(self, output: str, ctx: AgentContext) -> None:
        """Guarda el output como report en la memoria del cliente objetivo (si lo hay)."""
        cid = ctx.args.get("client_id") if isinstance(ctx.args, dict) else None
        if not cid or not (output or "").strip():
            return
        from ..integrations import clients_store as cs
        # Cliente descartado → memoria congelada: no seguimos escribiéndole.
        if cs.is_frozen(cid):
            return
        from datetime import datetime as _dt
        from ..integrations import client_memory_store as cms
        title = f"{self.name} · {_dt.now(pytz.timezone(self.timezone)).strftime('%Y-%m-%d')}"
        cms.add_memory(cid, kind="report", agent=self.name, title=title,
                       content=(output or "").strip()[:20000],
                       meta={"run_id": ctx.run_id, "triggered_by": ctx.triggered_by})

    def run(self, ctx: AgentContext) -> str:
        t0 = time.perf_counter()
        log.info(
            "agent_run_start",
            agent=self.name,
            run_id=ctx.run_id,
            triggered_by=ctx.triggered_by,
        )
        try:
            user_msg = self.build_user_message(ctx)
            # Tarea ad-hoc del operador (dashboard): se inyecta como instrucción
            # prioritaria, además del trabajo normal del agente. Uniforme p/todos.
            try:
                if isinstance(ctx.args, dict) and ctx.args.get("task_prompt"):
                    user_msg = (
                        f"{user_msg}\n\n## TAREA ADICIONAL (pedido manual del operador — prioritaria)\n"
                        f"{ctx.args['task_prompt']}\n"
                        "Resolvé esta tarea adicional y entregá su resultado junto con tu output."
                    )
            except Exception:
                pass
            # Memoria de la agencia: contexto de empresa + lecciones aprendidas +
            # (si la tarea apunta a un cliente) su memoria. Best-effort: nunca
            # rompe una corrida. Este es el sustrato del "aprendizaje continuo":
            # cada run arranca con el contexto y lo aprendido hasta ahora.
            try:
                user_msg = self._augment_with_memory(user_msg, ctx)
            except Exception as e:
                log.warning("memory_augment_failed", agent=self.name, error=str(e))
            # Llama a MiniMax-M3 (con fallback a M2.5 / M2.5-highspeed según config)
            # Allow a force_global override to remove "global_pause" guard from the system prompt
            local_system = self.system_prompt
            try:
                if isinstance(ctx.args, dict) and ctx.args.get("force_global"):
                    # Remove instructions that explicitly tell the model to honor global_pause
                    local_system = local_system.replace(
                        "Si global_pause está activo, no ejecutar (sólo devolver mensaje de pausa)",
                        "[IGNORAR GLOBAL_PAUSE: ejecución autorizada vía force_global=True]",
                    )
            except Exception:
                pass

            response: Optional[MiniMaxResponse] = None

            # 1) Camino preferente: Claude Code headless con backend MiniMax.
            if self.use_claude_code:
                try:
                    cc_prompt = user_msg
                    if self.claude_code_skill:
                        cc_prompt = (
                            f"IMPORTANTE: cargá y seguí la skill `{self.claude_code_skill}` "
                            f"(usá la tool Skill) para resolver esta tarea.\n\n{user_msg}\n\n"
                            "Al terminar, IMPRIMÍ el entregable COMPLETO como tu respuesta final "
                            "(no lo dejes solo en archivos de disco)."
                        )
                    cc_text = run_claude_code(
                        prompt=cc_prompt,
                        settings=ctx.settings,
                        system_append=local_system,
                        allowed_tools=self.claude_code_tools,
                        timeout=self.claude_code_timeout,
                    )
                    response = MiniMaxResponse(
                        text=cc_text,
                        model=f"claude-code:{ctx.settings.minimax_model_primary}",
                        input_tokens=0, output_tokens=0,
                        stop_reason="end_turn", raw={}, elapsed_ms=0,
                    )
                    log.info("agent_via_claude_code", agent=self.name, run_id=ctx.run_id)
                except ClaudeCodeError as e:
                    log.warning("claude_code_unavailable_fallback",
                                agent=self.name, run_id=ctx.run_id, error=str(e))
                    response = None  # cae al path MiniMax directo

            # 2) Path MiniMax directo (con o sin tool-use), o fallback del anterior.
            if response is None:
                if self.tools:
                    try:
                        response = self._run_agentic_loop(ctx, local_system, user_msg)
                    except MiniMaxError as e:
                        # Red de seguridad: si el proveedor rechaza el campo `tools`
                        # (o el loop falla), no dejamos al equipo sin entregable:
                        # caemos a una completion de texto plano (modo offline).
                        log.warning("agentic_loop_failed_fallback_text",
                                    agent=self.name, run_id=ctx.run_id, error=str(e))
                        response = ctx.minimax.complete(
                            system=local_system,
                            messages=[{"role": "user", "content": user_msg}],
                            max_tokens=self.max_tokens,
                            temperature=self.temperature,
                        )
                else:
                    response = ctx.minimax.complete(
                        system=local_system,
                        messages=[{"role": "user", "content": user_msg}],
                        max_tokens=self.max_tokens,
                        temperature=self.temperature,
                    )
            # Sanitización: MiniMax a veces inyecta caracteres CJK (chino/japonés)
            # en medio del español. Los limpiamos acá (un solo punto → cubre el
            # reporte de todos los agentes y los emails de outbound) antes de
            # persistir/entregar/enviar.
            clean_text, cjk_removed = sanitize_model_text(response.text)
            if cjk_removed:
                log.warning("sanitized_cjk_chars", agent=self.name,
                            run_id=ctx.run_id, removed=cjk_removed)
            output = self.post_process(clean_text, ctx)
            # Si la corrida apuntaba a un cliente, guardar el report en su memoria
            # (así "una vez que guardás un cliente, el report y la info recaudada
            # queda en su memoria" y cualquier agente futuro la lee).
            try:
                self._persist_client_report(output, ctx)
            except Exception as e:
                log.warning("client_report_persist_failed", agent=self.name, error=str(e))
            elapsed_ms = int((time.perf_counter() - t0) * 1000)

            # Auditoría
            write_run_log(
                "agent_runs",
                {
                    "agent": self.name,
                    "run_id": ctx.run_id,
                    "triggered_by": ctx.triggered_by,
                    "model": response.model,
                    "input_tokens": response.input_tokens,
                    "output_tokens": response.output_tokens,
                    "elapsed_ms": elapsed_ms,
                    "stop_reason": response.stop_reason,
                    "ok": True,
                },
            )

            # Delivery a Discord
            if self.deliver_to_discord and ctx.discord:
                try:
                    ctx.discord.send_agent_output(
                        agent_name=self.name,
                        text=output,
                        run_id=ctx.run_id,
                        elapsed_ms=elapsed_ms,
                        url=ctx.settings.discord_webhook_for(self.name),
                    )
                except Exception as e:
                    log.error("discord_delivery_error", agent=self.name, error=str(e))

            log.info(
                "agent_run_ok",
                agent=self.name,
                run_id=ctx.run_id,
                elapsed_ms=elapsed_ms,
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
            )
            return output

        except Exception as e:
            elapsed_ms = int((time.perf_counter() - t0) * 1000)
            log.exception("agent_run_failed", agent=self.name, run_id=ctx.run_id)
            write_run_log(
                "agent_runs",
                {
                    "agent": self.name,
                    "run_id": ctx.run_id,
                    "triggered_by": ctx.triggered_by,
                    "elapsed_ms": elapsed_ms,
                    "ok": False,
                    "error": str(e),
                },
            )
            if ctx.discord:
                try:
                    ctx.discord.send_agent_output(
                        agent_name=f"❌ {self.name}",
                        text=f"Error: {e}",
                        run_id=ctx.run_id,
                        elapsed_ms=elapsed_ms,
                        url=ctx.settings.discord_webhook_errors or ctx.settings.discord_webhook_for(self.name),
                        color=0xE74C3C,  # rojo
                    )
                except Exception:
                    pass
            raise

    # ── Agentic loop (tool use) ──

    def _execute_tool(self, name: str, tool_input: Dict[str, Any]) -> Any:
        """Ejecuta una tool local y devuelve un resultado serializable."""
        fn = self.tool_executors.get(name)
        if fn is None:
            return {"error": f"tool desconocida: {name}"}
        try:
            return fn(**tool_input) if isinstance(tool_input, dict) else fn(tool_input)
        except TypeError as e:
            # input con keys que la fn no acepta: reintentar con el primer arg posicional
            try:
                vals = list(tool_input.values()) if isinstance(tool_input, dict) else [tool_input]
                return fn(*vals)
            except Exception as e2:
                return {"error": f"tool {name} falló: {e2}"}
        except Exception as e:
            return {"error": f"tool {name} falló: {e}"}

    def _run_agentic_loop(self, ctx: AgentContext, system: str, user_msg: str) -> MiniMaxResponse:
        """Loop de tool use: el modelo pide tools, las ejecutamos y le devolvemos
        el resultado, iterando hasta que termine (end_turn) o se agoten las vueltas.
        """
        messages: List[Dict[str, Any]] = [{"role": "user", "content": user_msg}]
        last: Optional[MiniMaxResponse] = None

        for i in range(self.max_tool_iterations):
            last = ctx.minimax.complete(
                system=system,
                messages=messages,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                tools=self.tools,
            )
            log.info("agent_tool_turn", agent=self.name, run_id=ctx.run_id,
                     turn=i + 1, stop_reason=last.stop_reason,
                     tool_calls=len(last.tool_uses))

            if not last.tool_uses:
                return last  # respuesta final (texto)

            # Anexar la respuesta del asistente (con sus bloques tool_use) tal cual
            messages.append({"role": "assistant", "content": last.content_blocks})

            # Ejecutar cada tool y devolver los resultados
            tool_results = []
            for tu in last.tool_uses:
                result = self._execute_tool(tu["name"], tu.get("input", {}))
                log.info("agent_tool_exec", agent=self.name, run_id=ctx.run_id,
                         tool=tu["name"], input=tu.get("input", {}))
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tu["id"],
                    "content": json.dumps(result, ensure_ascii=False, default=str)[:8000],
                })
            messages.append({"role": "user", "content": tool_results})

        # Vueltas agotadas: pedir un cierre final SIN tools para forzar texto
        log.warning("agent_tool_loop_exhausted", agent=self.name, run_id=ctx.run_id,
                    iterations=self.max_tool_iterations)
        messages.append({
            "role": "user",
            "content": ("Cerrá ahora con el entregable final completo usando lo que ya "
                        "recolectaste. No pidas más tools."),
        })
        final = ctx.minimax.complete(
            system=system,
            messages=messages,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
        )
        return final

    def get_trigger(self) -> Optional[CronTrigger]:
        if not self.schedule:
            return None
        return CronTrigger.from_crontab(self.schedule, timezone=pytz.timezone(self.timezone))
