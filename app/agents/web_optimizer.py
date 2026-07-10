"""
Web Optimizer — mejora la landing de Automiq y deploya un PREVIEW en Vercel.

La landing (`automiq-landing-astro`, Astro) se deploya por CLI (sin repo git), así
que la fuente de verdad es el último deploy de producción. Flujo del agente:
  1. Baja la fuente del último deploy de prod (vercel_client.download_source).
  2. La mejora con Claude Code (CRO/SEO/diseño/copy) editando los archivos in place,
     en el directorio descargado (run_claude_code con cwd=root).
  3. Deploya un PREVIEW en Vercel (no producción) y avisa por Discord con la URL
     para que el humano apruebe/promueva a prod. (Si web_auto_deploy=True, va a prod.)

Gateado: si faltan VERCEL_TOKEN / VERCEL_PROJECT, no corre (reporta pendiente) y NO
consume cuota de Claude Code.
"""
from __future__ import annotations

import shutil
import tempfile

from .base import BaseAgent, AgentContext
from ._common import get_context_block
from ..clients.claude_code import run_claude_code, ClaudeCodeError
from ..integrations.vercel_client import get_vercel_client, VercelError
from ..log import get_logger

log = get_logger("web_optimizer")


WEB_OPTIMIZER_SYSTEM = """
# Web Optimizer — Automiq (landing que CONVIERTE)

Sos un ingeniero front-end + especialista en CRO. Estás editando la landing de
Automiq (sitio Astro), cuyo objetivo es UNO: que un visitante (PyME/empresa)
deje sus datos o agende una llamada para potenciar su negocio con IA (agentes,
automatización, sistemas a medida, consultoría).

## Principios (aplicá los que muevan la aguja, no toques por tocar)
- **Claridad del mensaje en 5 segundos**: el hero debe decir QUÉ hace Automiq, PARA
  QUIÉN y QUÉ gana el cliente (resultado concreto), sin jerga.
- **Una sola acción primaria**: un CTA dominante y repetido (agendar / pedir demo),
  con copy de beneficio ("Agendá tu diagnóstico gratis"), no "Enviar".
- **Prueba social y confianza**: testimonios, logos, números, garantías — si no hay
  datos reales, NO inventes; dejá el bloque preparado con placeholders claros.
- **Fricción mínima**: formularios cortos, jerarquía visual, contraste AA, foco en mobile.
- **Estructura de oferta**: problema → solución → cómo funciona → resultados → oferta → FAQ → CTA final.
- **SEO on-page**: <title>, meta description, OG tags, headings jerárquicos, alt en imágenes.
- **Performance**: no agregues dependencias pesadas; preferí CSS/markup nativo.

## Reglas DURAS (no romper el sitio)
- Español argentino. Mantené la marca Automiq (nombre, colores, tono).
- Editá los archivos EXISTENTES in place. NO cambies el stack ni la estructura de Astro.
- NO agregues dependencias npm nuevas salvo que sea imprescindible.
- NO borres secciones enteras sin reemplazo; mejorá incrementalmente.
- El sitio DEBE seguir compilando (Astro). Si tocás sintaxis, dejala válida.
- NO ejecutes deploys ni comandos de build/vercel: de eso me encargo yo después.
""".strip()


WEB_OPTIMIZER_TASK = """
Cargá y seguí las skills `marketing-landing` y `cro` (usá la tool Skill) para guiar el
análisis CRO, `ui-ux-pro-max` para decisiones visuales/UX y `humanizer` para que el copy
no suene a IA. Nota: no tenés Bash — los scripts de búsqueda de `ui-ux-pro-max` no corren;
buscá directo en sus `data/*.csv` con Grep.

Estás dentro del directorio del proyecto de la landing (Astro). Hacé esto:
1. Explorá la estructura (Glob/Read): encontrá las páginas/componentes (probablemente
   `src/pages/index.astro` y/o componentes) y entendé el contenido actual.
2. Identificá las 4-6 mejoras de MAYOR impacto en conversión (hero, CTA, prueba social,
   claridad de oferta, SEO meta, FAQ) según los principios del sistema.
3. IMPLEMENTALAS editando los archivos in place (Edit/Write). Mantené el sitio válido y
   on-brand. No agregues deps ni cambies el stack.
4. Al terminar, IMPRIMÍ como respuesta final un resumen en markdown con:
   - `## Cambios aplicados` (lista concreta: qué cambiaste y por qué, por archivo)
   - `## Impacto esperado` (en conversión/SEO)
   - `## Pendiente / a revisar` (lo que necesita datos reales o decisión humana)
NO corras vercel/npm/deploy. Solo editá y resumí.
""".strip()


class WebOptimizerAgent(BaseAgent):
    name = "web_optimizer"
    description = "Mejora la landing (CRO/SEO/diseño) y deploya un preview en Vercel para aprobar"
    schedule = "0 20 * * wed"   # miércoles 20:00 ART (semanal, fuera del horario de los demás)
    timezone = "America/Buenos_Aires"
    deliver_to_discord = True
    use_claude_code = True
    claude_code_skill = "marketing-landing,cro,ui-ux-pro-max,humanizer"
    claude_code_timeout = 1800
    # Solo tools de edición: que NO pueda deployar/romper por su cuenta (de eso me ocupo en Python).
    claude_code_tools = ["Read", "Write", "Edit", "Glob", "Grep", "Skill", "WebFetch"]

    @property
    def system_prompt(self) -> str:
        return f"{get_context_block()}\n\n{WEB_OPTIMIZER_SYSTEM}"

    def build_user_message(self, ctx: AgentContext) -> str:
        # Directivas del operador (tarea del panel): qué mantener, qué cambiar, qué
        # no tocar. Van PRIMERO y mandan sobre el checklist genérico.
        task = ""
        try:
            if isinstance(ctx.args, dict) and ctx.args.get("task_prompt"):
                task = (
                    "## DIRECTIVAS DEL OPERADOR (PRIORITARIAS — mandan sobre todo lo demás)\n"
                    f"{ctx.args['task_prompt'].strip()}\n"
                    "Respetá esto a rajatabla: lo que pida MANTENER no se toca; lo que pida "
                    "cambiar/quitar se hace tal cual.\n\n"
                )
        except Exception:
            pass
        return task + WEB_OPTIMIZER_TASK

    # Override completo: descarga determinística + edición CC + deploy determinístico.
    def run(self, ctx: AgentContext) -> str:
        if not ctx.settings.web_optimizer_configured:
            return self._deliver(ctx, (
                "⚙️ **Web Optimizer pendiente de configuración.** Faltan `VERCEL_TOKEN` y/o "
                "`VERCEL_PROJECT` (+ `VERCEL_TEAM_ID`) en las env vars. Cuando estén, el agente "
                "baja la fuente de la landing, la mejora (CRO/SEO/diseño) y deploya un preview "
                "en Vercel para que apruebes."))

        vc = get_vercel_client(ctx.settings)
        workdir = None
        # Base de trabajo: por default el último deploy de PRODUCCIÓN. Si la corrida
        # viene de una REVIEW del operador (args.base_deployment = uid del preview
        # reviewado), se itera SOBRE ESE preview — los cambios previos no se pierden.
        base_dep = ""
        try:
            if isinstance(ctx.args, dict):
                base_dep = str(ctx.args.get("base_deployment") or "").strip()
        except Exception:
            base_dep = ""
        try:
            dep_id = base_dep or vc.latest_production_deployment()["uid"]
            workdir = tempfile.mkdtemp(prefix="webopt_")
            nfiles = vc.download_source(dep_id, workdir)
            root = vc.find_project_root(workdir)
            log.info("webopt_source_ready", run_id=ctx.run_id, files=nfiles, root=root,
                     base="preview" if base_dep else "production")
        except (VercelError, Exception) as e:
            log.error("webopt_download_failed", run_id=ctx.run_id, error=str(e))
            self._cleanup(workdir)
            return self._deliver(ctx, f"⚠️ **Web Optimizer:** no pude bajar la fuente de la landing — {e}")

        # Preferencias acumuladas: cada review del operador queda como lección
        # persistente → TODAS las corridas futuras la respetan (qué mantener/qué no).
        prompt = self.build_user_message(ctx)
        try:
            from ..integrations import memory_store as ms
            lessons = ms.lessons_for(self.name)
            if lessons:
                prompt = ("## PREFERENCIAS ACUMULADAS DEL OPERADOR (reviews previas — "
                          f"respetarlas SIEMPRE)\n{lessons}\n\n{prompt}")
        except Exception:
            pass

        # Mejora con Claude Code dentro del directorio del proyecto.
        cc_text = ""
        try:
            cc_text = run_claude_code(
                prompt=prompt,
                settings=ctx.settings,
                system_append=self.system_prompt,
                allowed_tools=self.claude_code_tools,
                timeout=self.claude_code_timeout,
                cwd=root,
                extra_env={"VERCEL_TOKEN": ctx.settings.vercel_token},
            )
        except ClaudeCodeError as e:
            log.warning("webopt_cc_failed", run_id=ctx.run_id, error=str(e))
            self._cleanup(workdir)
            return self._deliver(ctx, f"⚠️ **Web Optimizer:** no pude correr la mejora (Claude Code) — {e}")

        # Deploy: preview por default; prod sólo si web_auto_deploy.
        prod = bool(ctx.settings.web_auto_deploy)
        try:
            url = vc.deploy(root, prod=prod)
        except (VercelError, Exception) as e:
            log.error("webopt_deploy_failed", run_id=ctx.run_id, error=str(e))
            self._cleanup(workdir)
            return self._deliver(ctx, (
                "⚠️ **Web Optimizer:** mejoré la landing pero falló el deploy — "
                f"{e}\n\n{(cc_text or '')[:1500]}"))
        finally:
            pass
        self._cleanup(workdir)

        return self._deliver(ctx, self._render(prod, url, cc_text))

    # ── helpers ──
    def _render(self, prod: bool, url: str, cc_text: str) -> str:
        if prod:
            head = [
                "# 🌐 Web Optimizer — cambios PUBLICADOS en producción",
                f"**URL:** {url}",
                "_web_auto_deploy=True → se publicó directo. Revisá que esté todo OK._",
                "",
            ]
        else:
            head = [
                "# 🌐 Web Optimizer — PREVIEW listo para tu aprobación",
                f"**Preview:** {url}",
                "👉 Revisalo. Si te gusta, promovelo a producción desde Vercel "
                "(Deployments → ··· → Promote to Production) o avisame.",
                "",
            ]
        return "\n".join(head) + (cc_text or "_(sin resumen de cambios)_")

    def _deliver(self, ctx: AgentContext, text: str) -> str:
        if self.deliver_to_discord and ctx.discord:
            try:
                ctx.discord.send_agent_output(
                    agent_name=self.name, text=text, run_id=ctx.run_id,
                    url=ctx.settings.discord_webhook_for(self.name),
                )
            except Exception as e:
                log.error("webopt_discord_failed", error=str(e))
        try:
            BaseAgent.post_process(self, text, ctx)  # persistencia best-effort a data/
        except Exception:
            pass
        return text

    @staticmethod
    def _cleanup(workdir) -> None:
        if workdir:
            shutil.rmtree(workdir, ignore_errors=True)
