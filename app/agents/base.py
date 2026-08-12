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
    # Skill(s) a cargar con la tool Skill. Acepta varias separadas por coma
    # (p.ej. "marketing-ads,ad-campaign-management").
    claude_code_skill: Optional[str] = None
    # Techo de turnos del harness Hermes. Antes NO se pasaba → todos los agentes
    # corrían con el default 15 del CLI y los largos morían con "Reached maximum
    # iterations (15). Requesting summary..." ENTREGANDO UN RESULTADO DEGRADADO
    # (leadhunter 2026-07-21: inventó el lote desde training data). El límite real
    # de una corrida es `claude_code_timeout`, no los turnos: un agente que busca
    # y verifica 10 empresas necesita decenas de tool calls.
    hermes_max_turns: int = 40
    # Los agentes de contenido reciben material de competencia (playbook, dirección
    # de arte, scout visual, estudio de reels). Antes iba ENTERO en el prompt —33 mil
    # caracteres iguales para los cuatro—; ahora se sirve por relevancia desde el
    # cerebro, así que cada uno recibe lo que aplica a la pieza del día.
    needs_creative_material: bool = False
    # Backend LLM alternativo (NVIDIA): "glm" | "deepseek" | "" (default MiniMax/CC).
    # Si está seteado y hay NVIDIA_API_KEY, el agente corre por completion directa con
    # ese modelo (salteando Claude Code); si NVIDIA falla, cae al flujo normal.
    llm_provider: str = ""

    def claude_code_mcp_servers(self, settings) -> Optional[Dict[str, Any]]:
        """Servidores MCP para el run de Claude Code (None = ninguno). Las subclases
        que usen un MCP lo devuelven acá; sus tools se permiten automáticamente
        como `mcp__<nombre>`."""
        return None

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

    def _skills_preamble(self) -> str:
        """Instrucción de skills + modo headless para los runs con harness
        (OpenCode). Igual espíritu que el cc_prompt del camino Claude Code."""
        parts = []
        if self.claude_code_skill:
            skills = [s.strip() for s in self.claude_code_skill.split(",") if s.strip()]
            skills_txt = " y ".join(f"`{s}`" for s in skills)
            parts.append(f"IMPORTANTE: cargá y seguí la(s) skill(s) {skills_txt} "
                         "(usá la tool de skills) para resolver esta tarea.")
        parts.append("Corrés HEADLESS (sin usuario): nunca preguntes ni esperes input — "
                     "decidí con el contexto y seguí. Al terminar, IMPRIMÍ el entregable "
                     "COMPLETO como tu respuesta final (no lo dejes solo en archivos).")
        return "\n".join(parts) + "\n\n"

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

    def _collab_block(self) -> str:
        """Colaboración entre agentes: notas que le dejaron + cómo dejar las suyas
        y cómo registrar aprendizajes. Es el mecanismo por el que los agentes se
        potencian entre sí y mejoran con el tiempo."""
        try:
            from ..integrations import agent_inbox, backlog
            from . import departments as dp
            from ._common import team_brief
            from .registry import list_agents as _all
            names = ", ".join(a.name for a in _all() if a.name != self.name)
            dept_id = dp.department_of(self.name)
            dept = dp.DEPARTMENTS.get(dept_id, {})
            mates = dp.teammates_of(self.name)
            parts = ["## 🤝 COLABORACIÓN ENTRE AGENTES"]
            # Equipo primero: con quién comparte departamento y qué produjeron recién.
            # Un agente que ve el trabajo de su sector no repite ni se contradice.
            if mates:
                parts.append(
                    f"### Tu equipo: {dept.get('label', dept_id)}\n"
                    f"Trabajás con **{', '.join(mates)}**. Son tu sector: apoyate en lo que "
                    "ya hicieron, no dupliques su trabajo y no te contradigas con ellos.")
                brief = team_brief(mates)
                if brief:
                    parts.append("**Lo último que produjo tu equipo:**\n" + brief)
            # Cómo le viene yendo con las órdenes de Dirección. Es el bucle de mejora
            # por resultado: antes el veredicto vivía en la prosa del brief de esa
            # noche y el agente nunca se enteraba de que no había cumplido.
            try:
                from ..integrations import missions_store as _mis
                track = _mis.bloque_cumplimiento(self.name)
                if track:
                    parts.append(track)
            except Exception as e:
                log.warning("track_block_failed", agent=self.name, error=str(e)[:120])
            notes = agent_inbox.pop_for(self.name)
            if notes:
                parts.append("### Notas que te dejaron tus compañeros (usalas HOY si aplican)")
                for n in notes:
                    when = (n.get("created_at") or "")[:10]
                    parts.append(f"- [de **{n['from']}**, {when}] {n['note']}")
            parts.append(
                "### Cómo colaborar (hacelo cuando aporte de verdad)\n"
                f"- Si descubriste algo que le sirve a OTRO agente ({names}), dejáselo "
                "con UNA línea propia y ESTRUCTURADA (así el que la recibe sabe qué hacer, "
                "no tiene que adivinar):\n"
                "  `NOTA_PARA(<agente>): [objetivo] <qué querés que haga> · "
                "[dato] <el dato concreto y accionable> · [porqué] <por qué le sirve>`\n"
                "  Ej: `NOTA_PARA(outbound): [objetivo] personalizá el 1er toque a veterinarias · "
                "[dato] responden más si mencionás el turno de guardia nocturna · "
                "[porqué] es su dolor #1 según la auditoría`. "
                "(máx 3 por corrida; la recibe en su próxima corrida).\n"
                "- Si esta corrida te dejó un aprendizaje DURABLE (qué funcionó, qué falló, "
                "qué patrón se repite), registralo con: `LECCION: <aprendizaje en 1 frase>` "
                "(máx 2; se te inyecta en el futuro y gana peso si se repite). "
                "No registres obviedades ni cosas de un solo día."
            )
            # El backlog: un hallazgo se anota UNA vez y acumula edad hasta que
            # alguien lo ejecuta. Antes de esto, cada agente re-escribía el mismo
            # hallazgo en su reporte todos los días y nadie sabía hace cuánto
            # estaba abierto (el trío de la web llevaba ~3 semanas así).
            pend = backlog.bloque(
                limite=8,
                titulo="### Pendientes YA anotados (NO los vuelvas a describir como hallazgo nuevo)")
            if pend:
                parts.append(pend + "\n(Si en ESTA corrida cerraste alguno, cerralo vos "
                                    "con `RESUELTO(<id>): <evidencia>`.)")
            parts.append(
                "### Hallazgos que hay que EJECUTAR (no los repitas en prosa: anotalos)\n"
                "Si encontrás algo que hay que hacer y no podés hacerlo vos, anotalo con "
                "UNA línea. Se registra con fecha y no se pierde; repetirlo en el reporte "
                "no lo ejecuta.\n"
                "  `PENDIENTE(<area>): <qué hay que hacer, concreto y verificable>`\n"
                "- `web` → cambio en la landing automiq.agency (lo ejecuta web_optimizer).\n"
                "- `dev` → cambio en el CÓDIGO del sistema de agentes. Ningún agente puede "
                "tocarlo, ni vos ni yo: va al dueño. Si tu instrucción necesita un flag o "
                "un modo que no existe todavía, es `dev`, no una tarea para otro agente.\n"
                "- `humano` → **último recurso**. Antes de anotar uno, pasá este test:\n"
                "  **¿Existe una opción conservadora que puedo tomar yo y que se revierte "
                "fácil? Entonces TOMALA y seguí.** Decila en tu reporte con la razón y cómo "
                "se cambia, pero NO la anotes como pendiente.\n"
                "  Ejemplo real de lo que NO va: 'definir si publico con el nombre real del "
                "cliente o uno genérico'. Usá el genérico —es lo reversible y no compromete a "
                "nadie— y avisá en el reporte que si tenemos permiso escrito se puede cambiar.\n"
                "  `humano` es SÓLO: gastar plata · una credencial o un acceso que no tenés · "
                "comprometer a la empresa con un tercero (mandar algo a un cliente, firmar, "
                "prometer) · algo irreversible o con riesgo legal/reputacional · información "
                "que únicamente el dueño tiene (números reales del negocio, estado de una "
                "relación).\n"
                "  Elegir entre dos opciones que podés probar y deshacer NO es `humano`: es tu "
                "trabajo. Cada pendiente que anotás le come tiempo al dueño, así que anotalo "
                "sólo si de verdad se traba sin él.\n"
                "Máx 3 por corrida y sólo lo que de verdad hay que ejecutar. Si ya está en la "
                "lista de arriba, NO lo anotes de nuevo — ni siquiera 'como referencia': si "
                "querés mencionarlo, nombralo por su id en el TEXTO de tu reporte, nunca con "
                "una línea `PENDIENTE`. Cada línea `PENDIENTE` crea un ítem, y tres agentes "
                "'refiriéndose' al mismo pendiente le dejan al dueño la misma tarea tres veces.\n"
                "**Si el ítem trae una nota del dueño, esa nota manda: no vuelvas a preguntar "
                "lo que ya te contestó.**\n"
                "**Anotá sólo lo que VERIFICASTE.** Un pendiente falso es peor que ninguno: se "
                "lleva una de las tres acciones del día del dueño y, como el registro acumula "
                "días, con el tiempo parece más urgente en vez de menos. Ya pasó dos veces "
                "(un 'H1 vacío' que nunca estuvo vacío, reportado 22 días seguidos; y una "
                "'casilla inexistente' que era un grupo que funciona). Si es una sospecha y no "
                "la comprobaste, va en tu reporte como sospecha — NO como PENDIENTE. Y no "
                "supongas la CAUSA de algo que no miraste: describí el síntoma que sí viste.\n"
                "Cuando termines algo que estaba anotado: `RESUELTO(<id>): <evidencia concreta "
                "de que quedó hecho>` (sin evidencia no se cierra)."
            )
            if mates:
                parts.append(
                    f"- Si lo que descubriste le sirve a TODO tu sector, mandáselo de una "
                    f"con `NOTA_PARA({dept_id}): …` — le llega a los {len(mates)} de "
                    f"{dept.get('label', dept_id)} ({', '.join(mates)}).")
            return "\n".join(parts)
        except Exception as e:
            log.warning("collab_block_failed", agent=self.name, error=str(e)[:120])
            return ""

    def _harvest_collab(self, text: str, ctx: AgentContext) -> None:
        """Cosecha NOTA_PARA(...) y LECCION: del output del agente (texto CRUDO,
        antes de que el post_process lo reescriba). Best-effort."""
        if not text:
            return
        try:
            import re as _re2
            from ..integrations import agent_inbox, backlog, memory_store as ms
            from . import departments as dp
            from .registry import list_agents as _all
            valid = {a.name for a in _all()}
            sent = 0
            for m in _re2.finditer(r"^[\s>*`\-]*NOTA_PARA\(([a-z_]+)\)\s*[:：]\s*(.+)$",
                                   text, _re2.IGNORECASE | _re2.MULTILINE):
                to, note = m.group(1).lower(), m.group(2).strip().strip("`*")
                if len(note) < 10 or sent >= 3:
                    continue
                # El destinatario puede ser un agente o un DEPARTAMENTO entero
                # (broadcast al sector). Agente primero: `customer_success` es
                # ambos y ahí gana el agente.
                targets = [to] if to in valid else dp.DEPARTMENTS.get(to, {}).get("agents", [])
                # lista, NO generador: any() cortaría el broadcast en el primero.
                ok = [agent_inbox.leave(self.name, t, note)
                      for t in targets if t != self.name]
                if any(ok):
                    sent += 1
            learned = 0
            for m in _re2.finditer(r"^[\s>*`\-]*LECCI[OÓ]N\s*[:：]\s*(.+)$",
                                   text, _re2.IGNORECASE | _re2.MULTILINE):
                lesson = m.group(1).strip().strip("`*")
                if 15 <= len(lesson) <= 300 and learned < 2:
                    ms.record_outcome(self.name, lesson)
                    learned += 1
            # Backlog: los hallazgos van a un registro con fecha, no a la prosa
            # del reporte (donde se re-escribían todos los días sin ejecutarse).
            abiertos = 0
            # El cierre del marcador tolera backticks/negritas DESPUÉS del paréntesis
            # (`PENDIENTE(web)`: …) porque así es como el LLM lo escribe cuando lo
            # pone en una viñeta; sin eso el marcador se pierde y no se anota nada.
            for m in _re2.finditer(r"^[\s>*`\-]*PENDIENTE\(([a-z]+)\)[\s`*]*[:：]\s*(.+)$",
                                   text, _re2.IGNORECASE | _re2.MULTILINE):
                if abiertos >= 3:
                    break
                if backlog.abrir(m.group(1).lower(), m.group(2).strip().strip("`*"), self.name):
                    abiertos += 1
            cerrados = 0
            for m in _re2.finditer(r"^[\s>*`\-]*RESUELTO\(([a-z0-9]{6,10})\)[\s`*]*[:：]\s*(.+)$",
                                   text, _re2.IGNORECASE | _re2.MULTILINE):
                if cerrados >= 3:
                    break
                if backlog.resolver(m.group(1).lower(), m.group(2).strip().strip("`*"), self.name):
                    cerrados += 1
            if sent or learned or abiertos or cerrados:
                log.info("collab_harvested", agent=self.name, run_id=ctx.run_id,
                         notes=sent, lessons=learned,
                         pendientes=abiertos, resueltos=cerrados)
        except Exception as e:
            log.warning("collab_harvest_failed", agent=self.name, error=str(e)[:120])

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
        collab = self._collab_block()
        if collab:
            blocks.append(collab)
        # Cerebro de la empresa (vault de Obsidian + grafo del código): los
        # pasajes que hablan del tema de esta corrida. Va por relevancia y no
        # como tool porque así lo reciben TODOS los caminos (Hermes/Claude Code/
        # NVIDIA/MiniMax) sin que el modelo tenga que acordarse de pedirlo.
        try:
            from ..integrations import brain_search
            # La query es SOLO el mensaje de la corrida: agregarle self.description
            # hacía que el pasaje que más matcheara fuera la ficha del propio
            # agente (05-Agents/<él mismo>) y tapaba el tema real.
            brain = brain_search.block(user_msg[:2000])
            if brain:
                blocks.append(brain)
            if self.needs_creative_material:
                # Acá SÍ suma la descripción del agente: la capa material no tiene
                # fichas de agentes, así que no puede "encontrarse a sí mismo", y
                # el dominio ayuda a traer las tácticas de su formato.
                mat = brain_search.block(f"{self.description} {user_msg[:2000]}",
                                         k=5, layer="material")
                if mat:
                    blocks.append(mat)
        except Exception as e:
            log.warning("brain_block_failed", agent=self.name, error=str(e)[:120])
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
                    # Override APPENDEADO (no string-replace de una oración literal de
                    # _common.py: si alguien la reformulaba, el replace no matcheaba y
                    # force_global dejaba de funcionar EN SILENCIO).
                    local_system += (
                        "\n\n## OVERRIDE OPERATIVO\nEsta corrida fue autorizada "
                        "explícitamente con force_global=True: ignorá cualquier "
                        "instrucción previa sobre global_pause y ejecutá normalmente."
                    )
            except Exception:
                pass

            response: Optional[MiniMaxResponse] = None

            # 0) Hermes (hermes-agent, Nous Research) — harness PRINCIPAL de TODOS
            #    los agentes desde 2026-07-14. Backend: MiniMax-M3, o NVIDIA para
            #    los agentes con llm_provider. Si falla, cae a la cadena de siempre
            #    (OpenCode → Claude Code → NVIDIA directo → MiniMax) sin regresión.
            if getattr(ctx.settings, "hermes_enabled", True):
                from ..clients.hermes import run_hermes
                # Si el backend NVIDIA falla (429 del tier gratis, medido en prod),
                # reintentar Hermes con MiniMax antes de abandonar a la cadena vieja.
                providers = [self.llm_provider] + ([""] if self.llm_provider else [])
                # Override de operador para BAKE-OFF de backends: `args._force_provider`
                # fuerza un único backend (sin fallback) para poder medir su calidad pura.
                # "minimax"/"" → MiniMax; "deepseek"/"glm" → NVIDIA. Sin el flag, nada cambia.
                try:
                    fp = ctx.args.get("_force_provider") if isinstance(ctx.args, dict) else None
                    if fp is not None:
                        providers = ["" if str(fp).lower() in ("", "minimax") else str(fp).lower()]
                        log.info("backend_forced", agent=self.name, run_id=ctx.run_id,
                                 provider=providers[0] or "minimax")
                except Exception:
                    pass
                for prov in providers:
                    # El tier gratis de NVIDIA (deepseek/glm) puede COLGARSE bajo carga:
                    # medido en prod, Hermes esperaba los 600s COMPLETOS antes de caer a
                    # MiniMax (cada agente deepseek perdía ~10min/corrida). De ahí este
                    # corte más corto que el de MiniMax (prov="" → claude_code_timeout).
                    # 2026-08-02: el run sano (sonda con el prompt EXACTO de
                    # creative_strategist, 30k chars, 15 turnos) tarda 90s, así que 180s
                    # parecía de sobra. NO lo era: el cuelgue lo detecta Hermes solo
                    # (timeout de lectura + 2 reintentos, ver run_hermes) y un reintento
                    # arranca recién a los ~120s → los 180s caían EN MEDIO y mataban
                    # también los turnos ya terminados. Ahora el intento colgado muere a
                    # los 60s y este corte es sólo el respaldo: 420s = 3 intentos del peor
                    # turno (180s) + una corrida sana entera, y sigue siendo fail-fast
                    # contra los 600s de MiniMax. Bajarlo vuelve a cortar reintentos.
                    p_timeout = 420 if prov else self.claude_code_timeout
                    try:
                        h_text = run_hermes(
                            self._skills_preamble() + user_msg,
                            settings=ctx.settings, llm_provider=prov,
                            system_append=local_system, timeout=p_timeout,
                            max_turns=self.hermes_max_turns, agente=self.name)
                        response = MiniMaxResponse(
                            text=h_text, model=f"hermes:{prov or 'minimax'}",
                            input_tokens=0, output_tokens=0,
                            stop_reason="end_turn", raw={}, elapsed_ms=0,
                        )
                        log.info("agent_via_hermes", agent=self.name, run_id=ctx.run_id,
                                 provider=prov or "minimax")
                        break
                    except Exception as e:
                        log.warning("hermes_unavailable_fallback", agent=self.name,
                                    run_id=ctx.run_id, provider=prov or "minimax",
                                    error=str(e)[:200])
                        response = None

            # 0a) OpenCode (harness con tools+skills, backend NVIDIA GLM/DeepSeek).
            #     Antes los agentes con llm_provider corrían por completion PELADA:
            #     las skills y los WebFetch del prompt eran letra muerta. OpenCode
            #     lee .claude/skills tal cual y les da bash/webfetch/skill reales.
            if self.llm_provider and response is None \
                    and getattr(ctx.settings, "opencode_enabled", True) \
                    and getattr(ctx.settings, "nvidia_api_key", ""):
                try:
                    from ..clients.opencode import run_opencode
                    oc_prompt = self._skills_preamble() + user_msg
                    oc_text = run_opencode(
                        oc_prompt, settings=ctx.settings, provider=self.llm_provider,
                        system_append=local_system, timeout=self.claude_code_timeout)
                    response = MiniMaxResponse(
                        text=oc_text, model=f"opencode:{self.llm_provider}",
                        input_tokens=0, output_tokens=0,
                        stop_reason="end_turn", raw={}, elapsed_ms=0,
                    )
                    log.info("agent_via_opencode", agent=self.name, run_id=ctx.run_id,
                             provider=self.llm_provider)
                except Exception as e:
                    log.warning("opencode_unavailable_fallback", agent=self.name,
                                run_id=ctx.run_id, error=str(e)[:200])
                    response = None

            # 1) Claude Code headless con backend MiniMax — ANTES que NVIDIA pelado:
            #    si OpenCode falla, un agente con use_claude_code espera tools+skills;
            #    caer a una completion sin harness lo dejaba sin poder cumplir su
            #    prompt (WebFetch/skills = letra muerta) aunque "corriera".
            if self.use_claude_code and response is None:
                try:
                    cc_prompt = self._skills_preamble() + user_msg
                    mcp_servers = None
                    cc_tools = self.claude_code_tools
                    try:
                        mcp_servers = self.claude_code_mcp_servers(ctx.settings)
                        if mcp_servers:
                            from ..clients.claude_code import DEFAULT_ALLOWED_TOOLS
                            cc_tools = list(cc_tools or DEFAULT_ALLOWED_TOOLS)
                            cc_tools += [f"mcp__{name}" for name in mcp_servers]
                    except Exception as e:
                        log.warning("claude_code_mcp_setup_failed", agent=self.name, error=str(e))
                    cc_text = run_claude_code(
                        prompt=cc_prompt,
                        settings=ctx.settings,
                        system_append=local_system,
                        allowed_tools=cc_tools,
                        timeout=self.claude_code_timeout,
                        mcp_servers=mcp_servers,
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
                    response = None  # cae a NVIDIA directo / MiniMax

            # 1b) Backend LLM alternativo (NVIDIA: GLM/DeepSeek) — completion directa
            #     SIN tools ni skills. Último harness antes de MiniMax pelado.
            if self.llm_provider and response is None \
                    and getattr(ctx.settings, "nvidia_api_key", ""):
                try:
                    from ..clients.nvidia import complete_with_provider
                    response = complete_with_provider(
                        self.llm_provider, ctx.settings, local_system, user_msg,
                        self.max_tokens, self.temperature)
                    log.info("agent_via_nvidia", agent=self.name, run_id=ctx.run_id,
                             provider=self.llm_provider)
                except Exception as e:
                    log.warning("nvidia_unavailable_fallback", agent=self.name,
                                run_id=ctx.run_id, error=str(e)[:200])
                    response = None

            # 2) Path MiniMax directo (con o sin tool-use), o fallback del anterior.
            if response is None:
                try:
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
                except MiniMaxError as e:
                    # 2b) Último recurso GRATIS: si MiniMax agota cuota (429) o falla,
                    #     TokenRouter (kimi-k3-free). Lento pero sin costo: mejor
                    #     entregar tarde que fallar la corrida. Solo si está configurado.
                    from ..clients.tokenrouter import (complete_tokenrouter,
                                                       tokenrouter_enabled)
                    if not tokenrouter_enabled(ctx.settings):
                        raise
                    log.warning("minimax_failed_fallback_tokenrouter", agent=self.name,
                                run_id=ctx.run_id, error=str(e)[:200])
                    response = complete_tokenrouter(
                        ctx.settings, local_system, user_msg,
                        self.max_tokens, self.temperature)
                    log.info("agent_via_tokenrouter", agent=self.name, run_id=ctx.run_id)
            # Sanitización: MiniMax a veces inyecta caracteres CJK (chino/japonés)
            # en medio del español. Los limpiamos acá (un solo punto → cubre el
            # reporte de todos los agentes y los emails de outbound) antes de
            # persistir/entregar/enviar.
            clean_text, cjk_removed = sanitize_model_text(response.text)
            if cjk_removed:
                log.warning("sanitized_cjk_chars", agent=self.name,
                            run_id=ctx.run_id, removed=cjk_removed)
            # Colaboración: cosechar NOTA_PARA/LECCION del texto CRUDO — varios
            # post_process reescriben el output y las líneas se perderían.
            self._harvest_collab(clean_text, ctx)
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
            # Argumentos que la fn no acepta: devolver el error al modelo para que
            # corrija los args. NO reintentar posicional: si el TypeError saltó
            # DESPUÉS del side effect (mail enviado, insert en store) la acción se
            # ejecutaba dos veces, y los values() en orden del dict podían cruzar
            # parámetros (to/subject invertidos).
            return {"error": f"argumentos inválidos para la tool {name}: {e}. "
                             "Reintentá con los nombres de parámetros exactos del schema."}
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

        # Vueltas agotadas: pedir un cierre final SIN tools para forzar texto.
        # La instrucción va DENTRO del último mensaje user (el de los tool_results):
        # dos user consecutivos rompen la alternancia de roles que exige la API
        # Anthropic-compatible → 400 → se perdía todo el trabajo de las tools.
        log.warning("agent_tool_loop_exhausted", agent=self.name, run_id=ctx.run_id,
                    iterations=self.max_tool_iterations)
        closing = ("Cerrá ahora con el entregable final completo usando lo que ya "
                   "recolectaste. No pidas más tools.")
        if messages and messages[-1]["role"] == "user" and isinstance(messages[-1]["content"], list):
            messages[-1]["content"] = messages[-1]["content"] + [{"type": "text", "text": closing}]
        else:
            messages.append({"role": "user", "content": closing})
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
