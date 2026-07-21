"""
Web Optimizer — ciclo de SEO/GEO sobre la landing de Automiq, con datos reales.

Cada 2 semanas: mira Search Console (qué subió, qué cayó, qué está a tiro de
página 1) + el beacon de tráfico desde asistentes de IA (GEO), lee su propia
bitácora de las iteraciones anteriores, DECIDE solo qué mover, lo implementa en
la landing y deploya un preview. Al terminar reescribe la bitácora: qué probó,
qué funcionó, qué no, y qué ataca la próxima vez.

La landing (`automiq-landing-astro`, Astro) se deploya por CLI sin repo git, así
que la fuente de verdad es el último deploy de producción: se baja, se edita, se
deploya. La bitácora NO puede vivir ahí (el temp se borra) → va al volumen, en
`data/seo-progress.md` (ver integrations/seo_progress.py).

Gateado: sin VERCEL_TOKEN/VERCEL_PROJECT no corre. Sin GSC_SITE_URL corre igual
pero a ciegas, y lo dice en el reporte en vez de inventar números.
"""
from __future__ import annotations

import json
import shutil
import tempfile
from collections import Counter
from pathlib import Path

from .base import BaseAgent, AgentContext
from ._common import get_context_block
from ..clients.claude_code import run_claude_code, ClaudeCodeError
from ..clients.hermes import run_hermes
from ..integrations.vercel_client import get_vercel_client, VercelError
from ..integrations import search_console, seo_progress
from ..log import get_logger

log = get_logger("web_optimizer")


WEB_OPTIMIZER_SYSTEM = """
# Web Optimizer — Automiq (SEO orgánico + GEO)

Sos un ingeniero front-end + especialista en SEO técnico y GEO (optimización
para que te citen los asistentes de IA). Editás la landing de Automiq (Astro).

## Tu objetivo
Hacer crecer el tráfico orgánico CALIFICADO: PyMEs argentinas que buscan
automatizar procesos con IA. Dos frentes, los dos importan:
- **SEO**: rankear en Google (búsqueda tradicional).
- **GEO**: que ChatGPT/Perplexity/Gemini te citen cuando alguien les pregunta
  por agencias de IA o automatización de WhatsApp en Argentina.

## Cómo trabajás: por DATOS, no por checklist
Recibís datos reales de Search Console y del beacon de IA, más tu propia
bitácora de las iteraciones anteriores. **Vos decidís qué mover.** No hay una
lista fija de tareas: leé qué pasó, comparalo con lo que probaste antes, y
apostá donde haya evidencia.

Criterios que suelen rendir (elegí, no los hagas todos):
- **Doblar la apuesta en lo que sube**: si una consulta ganó impresiones,
  profundizá ese contenido, dale su propia sección o página, enlazala internamente.
- **A tiro de página 1** (posición 8-20): es donde menos esfuerzo rinde más.
  Mejorá título, intención y enlazado interno hacia esa página.
- **Enlazado interno**: las páginas satélite tienen que enlazarse entre sí y
  desde la home con anchor text descriptivo. Es de lo más barato que hay.
- **Lo que cayó**: entendé por qué antes de tocarlo. A veces es estacionalidad.
- **GEO**: respuestas directas y citables (párrafo de 2-3 líneas que responde la
  pregunta antes de desarrollar), datos concretos, FAQ con preguntas reales,
  schema, `llms.txt` al día.
- **Contenido nuevo** sólo si los datos muestran demanda que hoy no cubrís.

## Reglas DURAS
- Español argentino (vos). Mantené la marca Automiq: nombre, colores, tono.
- Editá los archivos EXISTENTES in place. Podés CREAR páginas nuevas si los datos
  lo justifican, siguiendo el layout de las satélites que ya existen.
- **NUNCA inventes datos, testimonios, reseñas, logos ni números de clientes.**
  Si un bloque necesita prueba social real, dejá el placeholder marcado.
- NO agregues dependencias npm. NO cambies el stack. El sitio DEBE seguir
  compilando (Astro). Si tocás sintaxis, dejala válida.
- NO borres secciones enteras sin reemplazo.
- **NO toques el tag de Google Ads (AW-...) ni el beacon de IA**: son la medición.
- NO corras deploys ni comandos de build/vercel: de eso me encargo yo después.
""".strip()


WEB_OPTIMIZER_TASK = """
Estás DENTRO del directorio del proyecto de la landing (Astro). Es una iteración
del ciclo quincenal de SEO/GEO.

1. **Leé la bitácora** de arriba: qué se probó, qué funcionó, qué no. No repitas
   lo que ya se descartó.
2. **Leé los datos** de Search Console y del beacon de IA. Cruzalos con la
   bitácora: ¿lo que hiciste la vez pasada movió la aguja? Sé honesto — si no
   movió nada, decilo y cambiá de hipótesis.
3. **Explorá el sitio** (Glob/Read): páginas, componentes, sitemap, llms.txt y
   cómo están enlazadas entre sí hoy.
4. **Decidí y ejecutá** 3-6 cambios de alto impacto según los datos. Implementalos
   editando los archivos (Edit/Write). Priorizá enlazado interno y las consultas
   a tiro de página 1: son las que más rinden por esfuerzo.
5. **Respuesta final**, en este orden exacto:
   - `## Qué decidí y por qué` (cada cambio atado al dato que lo justifica)
   - `## Cambios aplicados` (por archivo, concreto)
   - `## Qué medir la próxima` (qué señal diría que esto funcionó)
   - Y AL FINAL, la bitácora actualizada COMPLETA dentro de un bloque
     ```bitacora ... ``` con estas secciones:
     `# Bitácora SEO/GEO — automiq.agency`, `## Estado` (línea de base actual con
     números), `## Qué funcionó` (con la evidencia), `## Qué NO funcionó` (para no
     volver a intentarlo), `## Acciones para la próxima iteración` (numeradas).

La bitácora se REESCRIBE entera, no se appendea: consolidá, borrá las hipótesis
que ya se demostraron falsas y mantenela por debajo de ~20.000 caracteres. Es lo
único que la próxima corrida va a saber de todo esto — si algo no queda escrito
ahí, se pierde.

NO corras vercel/npm/deploy. Solo analizá, editá y resumí.
""".strip()


def _geo_block() -> str:
    """Tráfico desde asistentes de IA (GEO). Search Console NO lo mide: para
    Google una visita desde ChatGPT es un referral cualquiera. Sale del beacon
    propio (/api/web/ai-visit). Se lee el archivo directo, NO por HTTP: la app
    pegándole a su propio endpoint se auto-bloquea (ya pasó)."""
    path = Path(__file__).resolve().parent.parent.parent / "data" / "ai-visits.json"
    try:
        visits = json.loads(path.read_text(encoding="utf-8"))["visits"]
    except Exception:
        return ("### GEO — visitas desde asistentes de IA\nSin registros todavía "
                "(o el beacon no reportó). Tratalo como línea de base en cero.\n")
    if not visits:
        return ("### GEO — visitas desde asistentes de IA\nCero visitas registradas. "
                "El GEO todavía no trae tráfico medible.\n")
    fuentes = Counter(v.get("source", "?") for v in visits)
    paginas = Counter(v.get("path", "/") for v in visits)
    return (
        "### GEO — visitas desde asistentes de IA (beacon propio)\n"
        f"Total histórico: {len(visits)}\n"
        f"Por fuente: {dict(fuentes.most_common(8))}\n"
        f"Por página: {dict(paginas.most_common(10))}\n"
        f"Últimas 5: {json.dumps(visits[-5:], ensure_ascii=False)}\n"
    )


def _gsc_block() -> str:
    """Datos de Search Console, ya comparados contra el período anterior."""
    if not search_console.enabled():
        return ("### Search Console\n⚠️ NO CONFIGURADO (falta `GSC_SITE_URL` y/o la "
                "service account agregada como usuario de la propiedad). Trabajás a "
                "ciegas: no inventes métricas, decilo en el reporte y limitate a "
                "mejoras que no dependan de datos.\n")
    snap = search_console.snapshot()
    if not snap.get("ok"):
        return (f"### Search Console\n⚠️ NO PUDE LEER LOS DATOS: {snap.get('error')}\n"
                "No inventes métricas. Reportá esta falla como primer punto.\n")
    t = snap["totales"]
    return (
        f"### Search Console — {snap['sitio']}\n"
        f"Período: {snap['periodo']} (vs anterior {snap['periodo_anterior']})\n"
        f"Clicks: {t['clicks']} (antes {t['clicks_antes']}) · "
        f"Impresiones: {t['impresiones']} (antes {t['impresiones_antes']})\n\n"
        f"**Consultas que SUBEN** (delta de impresiones):\n"
        f"{json.dumps(snap['subiendo'], ensure_ascii=False, indent=1)}\n\n"
        f"**A tiro de página 1** (posición 8-20 — máximo rendimiento por esfuerzo):\n"
        f"{json.dumps(snap['a_tiro_de_pagina1'], ensure_ascii=False, indent=1)}\n\n"
        f"**Consultas que CAEN:**\n"
        f"{json.dumps(snap['cayendo'], ensure_ascii=False, indent=1)}\n\n"
        f"**Páginas:**\n{json.dumps(snap['paginas'], ensure_ascii=False, indent=1)}\n"
    )


class WebOptimizerAgent(BaseAgent):
    name = "web_optimizer"
    description = "Ciclo quincenal de SEO/GEO sobre la landing, guiado por Search Console"
    # Quincenal: días 1 y 15. Con día-del-mes no hace falta guardar estado para
    # saber si "toca esta semana" (un cron semanal + contador se desincroniza en
    # cuanto una corrida falla).
    schedule = "0 20 1,15 * *"
    timezone = "America/Buenos_Aires"
    deliver_to_discord = True
    use_claude_code = True
    claude_code_skill = "marketing-seo-contenido,ai-seo,schema,seo-audit,humanizer"
    claude_code_timeout = 1800
    # Sin Bash a propósito: que NO pueda deployar ni romper por su cuenta (el
    # deploy lo hace este archivo, en Python, después de revisar).
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
        bloques = (
            "## BITÁCORA DE LAS ITERACIONES ANTERIORES (leela ANTES de decidir)\n"
            f"{seo_progress.read()}\n\n"
            "## DATOS DE ESTA ITERACIÓN\n"
            f"{_gsc_block()}\n{_geo_block()}\n"
        )
        return task + bloques + WEB_OPTIMIZER_TASK

    # Override completo: descarga determinística + edición CC + deploy determinístico.
    def run(self, ctx: AgentContext) -> str:
        if not ctx.settings.web_optimizer_configured:
            return self._deliver(ctx, (
                "⚙️ **Web Optimizer pendiente de configuración.** Faltan `VERCEL_TOKEN` y/o "
                "`VERCEL_PROJECT` (+ `VERCEL_TEAM_ID`) en las env vars. Cuando estén, el agente "
                "baja la fuente de la landing, la mejora (SEO/GEO) y deploya un preview "
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
        prompt = self._skills_preamble() + self.build_user_message(ctx)
        try:
            from ..integrations import memory_store as ms
            lessons = ms.lessons_for(self.name)
            if lessons:
                prompt = ("## PREFERENCIAS ACUMULADAS DEL OPERADOR (reviews previas — "
                          f"respetarlas SIEMPRE)\n{lessons}\n\n{prompt}")
        except Exception:
            pass

        # Edición dentro del directorio del proyecto. HERMES primero, igual que el
        # resto del equipo: este agente overridea run(), así que la migración a
        # Hermes del 2026-07-14 lo había salteado y seguía en Claude Code.
        # Sin `terminal` ni `code_execution` a propósito: que edite archivos pero
        # NO pueda deployar ni correr comandos. El deploy lo hace este archivo, en
        # Python, después. Claude Code queda de red de seguridad, no de camino.
        cc_text = ""
        try:
            cc_text = run_hermes(
                prompt, settings=ctx.settings,
                system_append=self.system_prompt,
                timeout=self.claude_code_timeout,
                cwd=root,
                toolsets="web,file,skills,memory,todo",
                max_turns=self.hermes_max_turns,
                agente=self.name,
            )
            log.info("webopt_via_hermes", run_id=ctx.run_id)
        except Exception as e:
            log.warning("webopt_hermes_failed", run_id=ctx.run_id, error=str(e)[:200])
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
                log.info("webopt_via_claude_code_fallback", run_id=ctx.run_id)
            except ClaudeCodeError as e2:
                log.warning("webopt_cc_failed", run_id=ctx.run_id, error=str(e2))
                self._cleanup(workdir)
                return self._deliver(ctx, (
                    "⚠️ **Web Optimizer:** no pude correr la mejora — "
                    f"Hermes: {str(e)[:150]} · Claude Code: {e2}"))

        # La bitácora se persiste ANTES del deploy: si el deploy falla, el
        # aprendizaje de esta iteración no se pierde igual.
        nueva = seo_progress.extract(cc_text)
        if nueva:
            seo_progress.write(nueva)
        else:
            log.warning("webopt_sin_bitacora", run_id=ctx.run_id)
        cc_text = seo_progress.strip_bloque(cc_text)

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
        self._cleanup(workdir)

        return self._deliver(ctx, self._render(prod, url, cc_text, bool(nueva)))

    # ── helpers ──
    def _render(self, prod: bool, url: str, cc_text: str, bitacora_ok: bool) -> str:
        if prod:
            head = [
                "# 🌐 Web Optimizer — iteración SEO/GEO PUBLICADA en producción",
                f"**URL:** {url}",
                "_web_auto_deploy=True → se publicó directo. Revisá que esté todo OK._",
                "",
            ]
        else:
            head = [
                "# 🌐 Web Optimizer — iteración SEO/GEO lista para tu aprobación",
                f"**Preview:** {url}",
                "👉 Revisalo. Si te gusta, promovelo a producción desde Vercel "
                "(Deployments → ··· → Promote to Production) o avisame.",
                "",
            ]
        if not bitacora_ok:
            head.append("⚠️ _El agente no dejó bitácora nueva: la próxima iteración "
                        "arranca con la anterior._\n")
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
