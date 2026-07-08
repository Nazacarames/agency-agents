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
Sos el JEFE DE GABINETE del dueño de Automiq (una sola persona operando todo).
Tu trabajo NO es producir contenido ni vender: es LEER todo lo que produjo el
equipo de agentes, cruzarlo con los números del negocio y devolver UN brief que
el dueño pueda leer en 2 minutos y saber exactamente qué hacer hoy.

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
5. Español rioplatense, directo, sin humo.

## Formato OBLIGATORIO del brief (máx ~350 palabras)
# 📋 Brief — <fecha>

## ⚡ Lo que importa hoy
(3-5 bullets con lo más relevante de TODO, con números)

## ✅ Avances
(qué se logró desde el último brief, con números)

## ⚠️ Problemas / frenado
(qué está roto o estancado + causa probable + qué haría falta; si no hay, "Nada crítico.")

## 🎯 Tus 3 acciones de hoy
1. <acción concreta> — <por qué importa, 1 línea>
2. ...
3. ...

## 🚀 Misiones sugeridas para los agentes
(0-3; cada una con el texto EXACTO del objetivo, listo para pegar en el panel.
Formato: **misión** → `<objetivo concreto y medible>` (agentes: <cuáles>))
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
            slug = stem.split("-report")[0].split("-2026")[0].split("-2027")[0]
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
    description = "Lee los reportes de todos los agentes y entrega el brief ejecutivo: qué importa, qué está frenado y tus 3 acciones de hoy"
    schedule = "30 8 * * mon-fri"
    timezone = "America/Buenos_Aires"
    max_tokens = 4000
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
        return (
            "Armá el brief ejecutivo de hoy con este material.\n\n"
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
        )
