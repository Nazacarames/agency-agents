"""
Chief of Staff — el agente que hace que los reportes VALGAN algo.

Problema que resuelve (pedido del usuario 2026-07-08): los 13 agentes producen
reportes diarios que nadie procesa. Este agente los lee TODOS (los artefactos
más recientes de data/), les suma el estado duro del negocio (cola de
publicación, pipeline de leads, misiones) y entrega UN brief ejecutivo corto:
qué importa, qué avanzó, qué está frenado y — lo central — las 3 acciones
concretas que el humano tiene que hacer HOY, más misiones listas para lanzar.

Corre lun-vie 08:30 ART (después del radar de tendencias, antes del outbound).
"""
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from .base import BaseAgent, AgentContext
from ._common import get_context_block
from ..log import get_logger

log = get_logger("chief_of_staff")

_DATA = Path(__file__).resolve().parent.parent.parent / "data"

# Cuánto texto de cada reporte entra al prompt (los reportes largos se truncan;
# el brief necesita las conclusiones, no el desarrollo).
_PER_REPORT = 2200
_MAX_REPORTS = 12

COS_INSTRUCTIONS = """
# Chief of Staff — Automiq

## Quién sos
Sos el JEFE DE GABINETE y DIRECTOR DE OPERACIONES del dueño de Automiq (una sola
persona operando todo). Tu trabajo NO es producir contenido ni vender, y NO es
resumir: es GESTIONAR. Leés todo lo que produjo el equipo de agentes, lo cruzás
con los números del negocio y con tu brief anterior, y devolvés un brief que
convierte los datos en decisiones: plan de acción con dueño, seguimiento de lo
que recomendaste (¿se hizo? ¿lo escalo?) y mejoras concretas al propio sistema
de agentes (a quién agregarle una función, qué corregir, qué enfoque cambiar).

## CUÁNDO corrés (esto cambia todo)
Corrés a la NOCHE (21:00 ART), con el día ya cerrado y TODOS los agentes del día
ya ejecutados. No estás anticipando un día: estás cerrando el que pasó. Entonces:
- El material que recibís es **lo que realmente sucedió hoy**, no un pronóstico.
- Recibís además el parte de **quién entregó y quién NO**. Un agente que tenía que
  correr y no dejó reporte es una CORRIDA CAÍDA: eso va sí o sí a Problemas, con
  el nombre del agente. No lo pases por alto porque "el resto anduvo bien".
- El plan de acción es **para mañana y los próximos 7 días**, construido sobre lo
  que hoy movió o no movió la aguja.

## Reglas de oro
1. **Señal, no ruido**: si un reporte no aporta nada nuevo o accionable, NO lo
   menciones. Mejor 3 bullets con sustancia que 10 de relleno.
2. **Números concretos siempre** (leads tocados, respuestas, piezas encoladas,
   posts publicados). Nada de "buen avance en varias áreas".
3. **Las acciones del humano son SOLO lo que un agente no puede hacer**:
   decisiones, aprobaciones, pagos, grabar algo, contestar a una persona clave,
   destrabar una credencial. Lo que puede hacer un agente NO va como acción del
   humano — va como misión sugerida.
4. Si dos reportes se contradicen o algo huele a roto (agente que no corrió,
   métrica en cero, error repetido), decilo en Problemas con la causa probable.
5. **Seguimiento con memoria**: compará contra tu brief anterior. Lo que
   recomendaste y se hizo → celebralo en Avances. Lo que recomendaste y NADIE
   tocó → o lo escalás (con más urgencia y el porqué) o lo descartás
   explícitamente ("retiro X, ya no aplica porque..."). Nunca repitas la misma
   recomendación en el mismo tono dos días seguidos.
6. **Las mejoras al sistema salen de EVIDENCIA, no de imaginación**: proponé un
   cambio a un agente solo si los datos lo muestran (métrica plana varios días,
   el mismo problema en varios reportes, un hueco que ningún agente cubre, un
   reporte que trae datos que nadie usa). Citá la evidencia. Máximo 3 y solo si
   valen la pena; "sin mejoras esta vez" es una respuesta válida.
7. Español rioplatense, directo, sin humo.

## Formato OBLIGATORIO del brief (máx ~600 palabras)
# 📋 Cierre del día — <fecha>

## ⚡ Lo que pasó hoy
(3-5 bullets con lo más relevante de TODO lo que produjo el equipo HOY, con
números. Esto es el diario del día, no un pronóstico.)

## ✅ Avances
(qué se logró desde el último brief, con números; incluí lo recomendado que se hizo)

## ⚠️ Problemas / frenado
(qué está roto o estancado + causa probable + qué haría falta; si no hay, "Nada crítico."
**Toda corrida caída del parte de ejecución va acá, con el nombre del agente.**)

## 📌 Seguimiento del brief anterior
(qué pasó con cada recomendación pendiente: ✅ hecho / ⏫ escalo porque <razón> /
🗑️ la retiro porque <razón>. Si no hay brief anterior, omití la sección.)

## 🎯 Tus 3 acciones para mañana
(SOLO cosas que un agente no puede hacer: decisiones, aprobaciones, pagos, grabar
algo, contestar a una persona clave, destrabar una credencial.)
1. <acción concreta> — <por qué importa, 1 línea>
2. ...
3. ...

## 📈 Plan de acción (mañana + próximos 7 días)
(3-6 ítems priorizados, construidos sobre lo que HOY movió o no movió la aguja.
Cada uno con dueño: 👤 humano / 🤖 <agente> / 🛠️ dev. Formato: **<ítem>** (dueño)
— <resultado esperado medible>. Mantené continuidad con el plan del brief
anterior: actualizá, no reinventes de cero cada día. Si un ítem viene arrastrado
sin moverse hace 3+ días, o lo escalás o lo matás — no lo repitas igual.)

## 🔧 Mejoras al sistema de agentes
(0-3, SOLO con evidencia. Cada una:
**<agente o hueco>** — <qué cambiar: función nueva / corrección / enfoque distinto>
· Evidencia: <el dato de los reportes/números que lo justifica>
· Para implementar, pegale esto a Claude Code: "<instrucción de 1-3 líneas,
  concreta y autosuficiente>"
Si no hay nada con evidencia sólida: "Sin mejoras esta vez.")

## 🚀 Misiones sugeridas para los agentes
(0-3; cada una con el texto EXACTO del objetivo, listo para pegar en el panel.
Formato: **misión** → `<objetivo concreto y medible>` (agentes: <cuáles>))
""".strip()

WEEKLY_ADDON = """
## 🧭 Revisión semanal (solo hoy viernes)
Cerrá el brief con una sección extra mirando la semana completa:
- **Qué está funcionando** → doblar la apuesta (con el número que lo prueba).
- **Qué NO movió la aguja en toda la semana** → proponer matarlo o cambiarle el
  enfoque de raíz (no "optimizarlo": un enfoque DISTINTO, decí cuál).
- **La apuesta de la semana próxima**: UNA sola cosa que, si sale, cambia los
  números. Con primer paso concreto para el lunes.
""".strip()


def _recent_artifacts() -> str:
    """Junta el artefacto .md más reciente de cada agente (últimas 72h)."""
    try:
        if not _DATA.exists():
            return ""
        cutoff = datetime.now().timestamp() - 72 * 3600
        best = {}  # slug del agente -> (mtime, path)
        for p in _DATA.glob("*.md"):
            stem = p.stem
            if stem.startswith(("chief-of-staff", "trends-block", "visual-scout",
                                "creative-direction")):
                continue
            mt = p.stat().st_mtime
            if mt < cutoff:
                continue
            # slug = nombre de archivo sin fecha ni sufijo tipo -report
            # (regex de fecha, no años hardcodeados: '-2026'/'-2027' rompía en 2028)
            import re
            slug = re.split(r"-\d{4}-\d{2}-\d{2}", stem.split("-report")[0])[0]
            if slug not in best or mt > best[slug][0]:
                best[slug] = (mt, p)
        if not best:
            return ""
        parts = []
        for slug, (mt, p) in sorted(best.items(), key=lambda kv: -kv[1][0])[:_MAX_REPORTS]:
            try:
                txt = p.read_text(encoding="utf-8", errors="replace").strip()
            except Exception:
                continue
            when = datetime.fromtimestamp(mt).strftime("%Y-%m-%d %H:%M")
            if len(txt) > _PER_REPORT:
                txt = txt[:_PER_REPORT] + "\n…[truncado]"
            parts.append(f"### {slug} ({when})\n{txt}")
        return "\n\n".join(parts)
    except Exception as e:
        log.warning("cos_artifacts_failed", error=str(e)[:150])
        return ""


def _lo_de_hoy() -> str:
    """Qué pasó HOY, agente por agente: quién entregó y quién NO.

    Los reportes solo muestran a los que anduvieron. Un agente que reventó no
    deja archivo, y ese silencio es justo lo que hay que ver — pero es invisible
    si solo mirás lo que hay. Por eso se cruza contra el cron: quién TENÍA que
    correr hoy antes de esta hora, y de esos, quién no dejó nada.
    """
    try:
        from apscheduler.triggers.cron import CronTrigger
        from ..scheduler import DEFAULT_SCHEDULES
        tz = ZoneInfo("America/Buenos_Aires")
        ahora = datetime.now(tz)
        arranque = ahora.replace(hour=0, minute=0, second=0, microsecond=0)
        hoy = ahora.strftime("%Y-%m-%d")

        entregaron, faltaron, no_tocaba = [], [], []
        for nombre, cron in sorted(DEFAULT_SCHEDULES.items()):
            if nombre == "chief_of_staff":
                continue
            rep = _DATA / f"{nombre.replace('_', '-')}-report-{hoy}.md"
            if rep.is_file():
                st = rep.stat()
                hora = datetime.fromtimestamp(st.st_mtime, tz).strftime("%H:%M")
                entregaron.append(f"  ✅ {nombre} — entregó {hora} ({st.st_size} bytes)")
                continue
            try:
                trig = CronTrigger.from_crontab(cron, timezone=tz)
                prox = trig.get_next_fire_time(None, arranque)
                mismo_dia = prox is not None and prox.date() == ahora.date()
            except Exception:
                prox, mismo_dia = None, False
            if mismo_dia and prox <= ahora:
                faltaron.append(f"  ❌ {nombre} (`{cron}`) — TENÍA que correr "
                                f"({prox.strftime('%H:%M')}) y no dejó reporte")
            elif mismo_dia:
                # Corriendo a las 21:00 esto no debería pasar nunca; aparece solo en
                # corridas manuales a deshora. Distinguirlo evita leer "no le tocaba"
                # cuando en realidad todavía no le llegó la hora.
                no_tocaba.append(f"  ⏳ {nombre} (`{cron}`) — pendiente, corre "
                                 f"{prox.strftime('%H:%M')}")
            else:
                no_tocaba.append(f"  ➖ {nombre} (`{cron}`) — no corre hoy")

        partes = [f"Corte al {ahora.strftime('%Y-%m-%d %H:%M')} ART."]
        partes.append("**Entregaron hoy:**\n" + ("\n".join(entregaron) or "  (ninguno)"))
        if faltaron:
            partes.append("**NO entregaron (revisar — puede ser una corrida caída):**\n"
                          + "\n".join(faltaron))
        if no_tocaba:
            partes.append("**Sin corrida vencida (no corren hoy o todavía no les tocó):**\n"
                          + "\n".join(no_tocaba))
        return "\n\n".join(partes)
    except Exception as e:
        log.warning("cos_lo_de_hoy_failed", error=str(e)[:150])
        return ""


def _previous_brief() -> str:
    """El brief anterior propio (para seguimiento y continuidad del plan)."""
    try:
        files = sorted(_DATA.glob("chief-of-staff-report-*.md"))
        if not files:
            return ""
        txt = files[-1].read_text(encoding="utf-8", errors="replace").strip()
        return txt[:3000]
    except Exception as e:
        log.warning("cos_prev_brief_failed", error=str(e)[:150])
        return ""


def _roster() -> str:
    """Roster de agentes con capacidades y cadencia (para proponer mejoras)."""
    try:
        # lazy: registry importa este módulo — a nivel módulo sería circular
        from .registry import list_agents
        from ..scheduler import DEFAULT_SCHEDULES
        lines = []
        for a in list_agents():
            if a.name == "chief_of_staff":
                continue
            cron = DEFAULT_SCHEDULES.get(a.name, "manual")
            lines.append(f"- **{a.name}** (`{cron}`): {a.description}")
        return "\n".join(lines)
    except Exception as e:
        log.warning("cos_roster_failed", error=str(e)[:150])
        return ""


def _hard_numbers() -> str:
    """Estado duro del negocio (best-effort, cada bloque por separado)."""
    blocks = []
    try:
        from ..integrations import publish_queue as pq
        s = pq.summary()
        blocks.append(f"- Publicaciones: {s}")
    except Exception:
        pass
    try:
        from ..integrations import leads_store as ls
        store = ls.load_store()
        blocks.append(f"- Pipeline de leads: {ls.summary_counts(store)}")
    except Exception:
        pass
    try:
        from ..integrations import missions_store as ms
        missions = ms.list_missions(limit=5)
        if missions:
            lines = [f"  - #{m.get('id')} [{m.get('status')}] {str(m.get('objective'))[:90]}"
                     for m in missions]
            blocks.append("- Últimas misiones CEO:\n" + "\n".join(lines))
    except Exception:
        pass
    return "\n".join(blocks)


class ChiefOfStaffAgent(BaseAgent):
    name = "chief_of_staff"
    description = "Convierte los reportes de todos en gestión: brief ejecutivo, plan de acción con dueños, seguimiento de recomendaciones y mejoras propuestas al propio sistema de agentes"
    # 21:00 TODOS los días: cierra el día con los agentes ya ejecutados (el último
    # es web_optimizer a las 20:00). A las 08:30 lun-vie no podía ver el día que
    # estaba por empezar — resumía el anterior a medias y el plan salía a ciegas.
    schedule = "0 21 * * *"
    timezone = "America/Buenos_Aires"
    max_tokens = 6000
    temperature = 0.4
    llm_provider = "deepseek"   # razonamiento/síntesis (bake-off 2026-07-04); fallback MiniMax

    @property
    def system_prompt(self) -> str:
        return f"{get_context_block()}\n\n{COS_INSTRUCTIONS}"

    def build_user_message(self, ctx: AgentContext) -> str:
        reports = _recent_artifacts()
        numbers = _hard_numbers()
        if not reports and not numbers:
            return ("No hay reportes recientes ni métricas disponibles (disco vacío o "
                    "primer arranque). Entregá un brief mínimo que lo diga y sugerí "
                    "como única acción revisar que los agentes estén corriendo.")
        prev = _previous_brief()
        roster = _roster()
        extra = ""
        if roster:
            extra += ("\n## EL EQUIPO DE AGENTES (qué hace cada uno y cuándo corre — "
                      "usalo para el plan de acción y las mejoras al sistema)\n"
                      + roster + "\n")
        if prev:
            extra += ("\n## TU BRIEF ANTERIOR (para el seguimiento: qué se hizo, "
                      "qué escalás, qué retirás)\n" + prev + "\n")
        weekly = ""
        if datetime.now(ZoneInfo(self.timezone)).weekday() == 4:  # viernes
            weekly = "\n" + WEEKLY_ADDON + "\n"
        hoy = _lo_de_hoy()
        if hoy:
            extra += ("\n## PARTE DE EJECUCIÓN DE HOY (quién entregó y quién no)\n"
                      + hoy + "\n")
        return (
            "Cerrá el día: armá el brief con todo lo que pasó HOY y el plan de "
            "acción para mañana.\n" + weekly + "\n"
            "## REGLAS OPERATIVAS VIGENTES (así se decidió que funcione — NO son bugs)\n"
            "- La cola de publicaciones drena DE A POCO a propósito: 1 post de feed/día "
            "+ hasta 2 historias/día (11:00 ART). Tener pendientes acumuladas es normal; "
            "solo es problema si crece sin techo (tope 30) o si hoy no salió nada.\n"
            "- Outbound: tope 20 mails/día, solo lun-vie. Secuencia día 0/+2/+4/+7.\n"
            "- Meta/Google Ads: NO hay cuentas de ads conectadas todavía (decisión "
            "pendiente del dueño) — el media_auditor trabaja con benchmarks; no lo "
            "reportes como bug, como mucho como decisión pendiente.\n"
            "- TikTok: la app está en sandbox (los videos suben PRIVADOS hasta pasar la "
            "revisión). Los reels de IG/YouTube sí salen públicos.\n\n"
            "## NÚMEROS DUROS DEL NEGOCIO\n" + (numbers or "(sin datos)") + "\n\n"
            "## REPORTES RECIENTES DE LOS AGENTES (últimas 72h, truncados)\n"
            + (reports or "(sin reportes recientes)")
            + extra
        )
