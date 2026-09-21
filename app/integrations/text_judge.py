"""
text_judge — juez de calidad de TEXTO con Gemini (Vertex), el gemelo del QA visual.

El loop creativo ya hace QA de imágenes/shorts con Gemini y reinyecta las lecciones.
Esto lleva el mismo lazo al texto: cold-emails (outbound), contenido social y
propuestas. Gemini puntúa contra una rúbrica dura y devuelve el ÚNICO fix de mayor
impacto; el agente lo registra como LECCION y lo aplica en su próxima corrida.

Reusa el auth de Vertex de `vision` (service account, SIN key nueva → sin costo extra
más allá de lo que ya pagamos). Best-effort: si Vertex no está o falla, devuelve {}.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from ..log import get_logger

log = get_logger("text_judge")

# Debajo de este score consideramos que el lote tiene margen real → se aprende.
LEARN_BELOW = 80
# Debajo de este score NO conviene auto-publicar: se frena y queda para revisión humana.
HOLD_BELOW = 50

# El juez no conoce la restricción de presupuesto cero: mira una pieza orgánica y
# concluye que le falta pauta. Grabar ESO como lección le enseña al agente a pedir
# lo único que ya está contestado que no — y después el pedido reaparece en el
# backlog `humano`. Entre 2026-08-29 y 2026-09-08 llegaron ocho pedidos de pauta
# distintos: ésta es una de las canillas. Se descarta la LECCIÓN, no el score: si
# la pieza es floja por otra cosa, el juez lo dice en otro fix y el freno opera igual.
_FIX_IMPRACTICABLE = re.compile(
    r"pauta|presupuesto|invertir en (?:ads|publicidad)|google ads|meta ads|"
    r"publicidad paga|promoci[oó]n paga|contenido promocionado|\bboost(?:ear)?\b",
    re.I,
)


def enabled() -> bool:
    from . import vision
    return vision.enabled()


_EMAIL_RUBRIC = """
Sos un director de ventas B2B argentino, exigente. Puntuás cold-emails con esta rúbrica
(0-100 cada uno; penalizá fuerte lo que huela a plantilla o a bot):
1. Abre con una SEÑAL ESPECÍFICA del prospecto (su negocio/dolor), no con lo que vendemos.
2. Subject ≤45 caracteres, sin MAYÚSCULAS/"!!!"/"gratis"/"oferta", que no sea genérico.
3. UN beneficio medible y creíble (mejor con número).
4. CTA claro y de baja fricción (mirar demo / 15 min / ejemplo por WhatsApp).
5. Suena escrito por una persona 1-a-1, español rioplatense, sin "Estimado señor".
""".strip()

_SOCIAL_RUBRIC = """
Sos un director creativo de social media argentino, exigente. Puntuás posts para redes
(IG/LinkedIn/TikTok) con esta rúbrica (0-100 cada uno; penalizá fuerte lo genérico):
1. HOOK que frena el scroll en los primeros 3 segundos / primera línea.
2. NO suena a anuncio ni a folleto: aporta valor o entretiene primero.
3. UN mensaje claro por pieza (no mete 5 ideas), con CTA concreto.
4. Español rioplatense natural; NO promete resultados garantizados ni infla.
5. Se diferencia (ángulo fresco), no es el post obvio que haría cualquiera.
""".strip()

_PROPOSAL_RUBRIC = """
Sos un consultor senior que revisa propuestas comerciales, exigente. Puntuás con esta
rúbrica (0-100; penalizá lo vago y lo que no cierra la venta):
1. Arranca por el problema/beneficio del cliente, no por nosotros.
2. Alcance CONCRETO y medible (qué se entrega, en cuánto tiempo).
3. Precio claro y anclado (el cliente entiende qué paga y por qué conviene).
4. Diferenciador creíble frente a la competencia, sin humo.
5. Cierre con próximo paso simple y de baja fricción.
""".strip()

_RUBRICS = {"email": _EMAIL_RUBRIC, "social": _SOCIAL_RUBRIC, "proposal": _PROPOSAL_RUBRIC}


def _rubric_for(kind: str) -> str:
    """Rúbrica de `kind`. Para 'social' la enriquece con lo que REALMENTE funcionó en
    nuestro IG (la idea del post-scorer: puntuar contra performance real, no opinión
    genérica). Si aún no hay engagement propio, cae a la rúbrica base. Best-effort."""
    base = _RUBRICS.get(kind, "")
    if kind != "social" or not base:
        return base
    try:
        from . import content_autopsy
        data = content_autopsy.cached_block().strip()
    except Exception:
        data = ""
    if not data:
        return base
    return (base + "\n\n6. ADEMÁS, puntualo contra NUESTROS datos reales de IG (abajo): "
            "premiá el borrador que replica el formato/gancho de los ✅ y penalizá si cae "
            "en el patrón de los ❌.\n" + data)

_OUTPUT_SPEC = (
    "\n\nTe paso el/los texto(s). Devolvé EXCLUSIVAMENTE un objeto JSON (sin ``` ni texto):\n"
    '{"avg": <promedio 0-100 entero>, '
    '"top_fix": "<el ÚNICO cambio de mayor impacto para subir la calidad, 1 frase accionable>"}'
)


def _parse_obj(text: str) -> Dict[str, Any]:
    """Extrae el primer objeto JSON del texto (Gemini a veces lo envuelve). {} si falla."""
    if not text:
        return {}
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\n?|\n?```$", "", t).strip()
    try:
        return json.loads(t)
    except Exception:
        pass
    m = re.search(r"\{.*\}", t, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            return {}
    return {}


def _parse_array(text: str) -> List[Dict[str, Any]]:
    """Extrae un array JSON del texto (Gemini a veces lo envuelve). [] si falla."""
    if not text:
        return []
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\n?|\n?```$", "", t).strip()
    for candidate in (t, (re.search(r"\[.*\]", t, re.DOTALL) or [None])[0] if "[" in t else None):
        if not candidate:
            continue
        try:
            arr = json.loads(candidate)
            if isinstance(arr, list):
                return [e for e in arr if isinstance(e, dict)]
        except Exception:
            continue
    return []


def score_items(kind: str, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Puntúa CADA texto por separado. `items`: [{label, text}, ...].
    Devuelve una lista alineada por índice: [{score:int, issue:str} | None]. [] si falla."""
    rubric = _RUBRICS.get(kind)
    n = len(items[:8])
    if not rubric or not enabled() or not n:
        return []
    from . import vision
    payload = "\n\n".join(f"[{i}] {it.get('label', '?')}\nAsunto: {it.get('subject', '')}\n"
                          f"{it.get('text', '')}" for i, it in enumerate(items[:8]))
    spec = ("\n\nPuntuá CADA texto por su número [i]. Devolvé EXCLUSIVAMENTE un array JSON "
            '(sin ``` ni texto): [{"i": <indice>, "score": <0-100>, "issue": "<problema principal, corto>"}]')
    raw = vision.synthesize(payload[:12000], rubric + spec, max_tokens=1400)
    arr = _parse_array(raw)
    out: List[Any] = [None] * n
    for e in arr:
        try:
            i = int(e.get("i"))
            if 0 <= i < n:
                out[i] = {"score": int(e.get("score", 0)), "issue": str(e.get("issue", "")).strip()}
        except Exception:
            continue
    log.info("text_judge_scored", kind=kind, n=n, got=sum(1 for x in out if x))
    return out


def judge(kind: str, payload: str) -> Dict[str, Any]:
    """Puntúa `payload` con la rúbrica de `kind` ('email'|'social'|'proposal').
    Devuelve {avg, top_fix} o {} si el juez no está disponible/falla."""
    rubric = _rubric_for(kind)
    if not rubric or not enabled() or not (payload or "").strip():
        return {}
    from . import vision
    raw = vision.synthesize(payload[:12000], rubric + _OUTPUT_SPEC, max_tokens=900)
    obj = _parse_obj(raw)
    if not isinstance(obj, dict) or "avg" not in obj:
        log.warning("text_judge_no_parse", kind=kind, chars=len(raw or ""))
        return {}
    try:
        obj["avg"] = int(obj["avg"])
    except Exception:
        return {}
    log.info("text_judge_done", kind=kind, avg=obj.get("avg"))
    return obj


def judge_emails(emails: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Puntúa una lista de emails [{company, subject, body, step}, ...]."""
    if not emails:
        return {}
    payload = "\n\n".join(
        f"### {e.get('company', '?')} (step {e.get('step', 0)})\n"
        f"Asunto: {e.get('subject', '')}\n{e.get('body', '')}"
        for e in emails[:8]
    )
    return judge("email", payload)


RACHA_MALA = 2          # cuántas corridas flojas seguidas antes de frenar al agente
RACHA_UMBRAL = 70       # qué se considera "flojo" para contar la racha


def _ruta_rachas():
    from pathlib import Path
    return Path(__file__).resolve().parent.parent.parent / "data" / "qa-rachas.json"


def _anotar_score(agente: str, kind: str, avg: float, fix: str) -> str:
    """Lleva la cuenta de corridas flojas seguidas y frena al agente si insiste.

    Un agente que entrega flojo un día no es un problema. Uno que entrega flojo
    todos los días SÍ, y hasta ahora nadie lo notaba: cada corrida se juzgaba sola,
    publicaba igual mientras superara el piso, y al día siguiente empezaba de cero.
    El mismo patrón que dejó dos modelos muertos un mes: sin memoria entre corridas,
    lo que falla siempre parece un incidente aislado.

    Devuelve el texto a agregar al reporte cuando hay que frenar, o "" si va todo bien.
    """
    import json as _json
    try:
        p = _ruta_rachas()
        estado = {}
        if p.exists():
            estado = _json.loads(p.read_text(encoding="utf-8"))
        clave = f"{agente}:{kind}"
        r = estado.get(clave, {"seguidas": 0, "fixes": []})
        if avg < RACHA_UMBRAL:
            r["seguidas"] = int(r.get("seguidas", 0)) + 1
            r["fixes"] = ([*r.get("fixes", []), fix or ""])[-3:]
        else:
            r = {"seguidas": 0, "fixes": []}     # una buena corta la racha
        estado[clave] = r
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(_json.dumps(estado, ensure_ascii=False, indent=2), encoding="utf-8")

        if r["seguidas"] < RACHA_MALA:
            return ""

        # El mismo fix repetido significa que el agente NO está aprendiendo del
        # feedback: no alcanza con frenar la publicación, hay que avisarle a alguien.
        repetido = len(set(f for f in r["fixes"] if f)) == 1 and len(r["fixes"]) >= 2
        try:
            from . import backlog
            backlog.abrir("dev",
                          f"{agente} lleva {r['seguidas']} corridas seguidas con QA por "
                          f"debajo de {RACHA_UMBRAL} sobre {kind}"
                          + (f", siempre con el mismo fix pendiente: {r['fixes'][-1][:120]}"
                             if repetido else "")
                          + ". Se le freno la auto-publicacion. Requiere revision del "
                            "pipeline, no otra corrida.",
                          origen=agente)
        except Exception:
            pass
        return (f" · ⛔ **FRENADO POR RACHA**: {r['seguidas']} corridas seguidas por debajo "
                f"de {RACHA_UMBRAL}."
                + (f" Y siempre el MISMO fix sin aplicar (_{r['fixes'][-1][:110]}_), así que "
                   "el problema no es la corrida: es el pipeline." if repetido else "")
                + " No se publica nada hasta que alguien lo revise.")
    except Exception as e:
        log.warning("qa_racha_failed", agent=agente, error=str(e)[:140])
        return ""


def qa_gate(agent_name: str, kind: str, payload: str,
            hold_below: Optional[int] = None, qa_mode: str = "") -> Dict[str, Any]:
    """Juzga `payload`, aprende si está flojo, y decide si conviene auto-publicar.
    Devuelve {line, avg, publish_ok}. publish_ok=False solo si el score < HOLD_BELOW
    (contenido muy flojo → se frena el auto-publish y queda para revisión humana).
    Si el juez no está disponible, NUNCA bloquea (publish_ok=True). Best-effort.

    `hold_below` baja el umbral para lotes que la rúbrica base castiga por diseño:
    una placa tipográfica o una escena surreal puntúa bajo en "estética de foto"
    aunque cumpla su trabajo, que es leerse. `qa_mode` sólo se imprime, para que
    en el reporte se vea con qué vara se midió."""
    try:
        if not enabled():
            return {"line": "", "avg": None, "publish_ok": True}
        res = judge(kind, payload)
        if not res:
            return {"line": "", "avg": None, "publish_ok": True}
        avg = res.get("avg", 0)
        fix = (res.get("top_fix") or "").strip()
        impracticable = bool(fix and _FIX_IMPRACTICABLE.search(fix))
        if fix and avg < LEARN_BELOW and not impracticable:
            from . import memory_store as ms
            ms.record_outcome(agent_name, f"QA de calidad (Gemini) sobre {kind}: {fix}")
        if impracticable:
            log.info("text_judge_fix_descartado", agent=agent_name, kind=kind, fix=fix[:160])
        tope = int(hold_below) if hold_below else HOLD_BELOW
        publish_ok = avg >= tope
        # Registrar el score ANTES de armar la línea: si el agente viene fallando
        # seguido, eso cambia lo que hay que reportar.
        racha = _anotar_score(agent_name, kind, avg, fix)
        line = f"\n## 🧪 QA Gemini\nScore promedio: **{avg}/100**"
        if qa_mode:
            line += f" · `qa_mode={qa_mode}` (umbral {tope})"
        if racha:
            publish_ok = False
            line += racha
        if not publish_ok:
            line += (f" · ⛔ **AUTO-PUBLICACIÓN FRENADA** (score < {tope}): quedó para tu "
                     f"revisión. Fix sugerido: _{fix}_" if fix else
                     f" · ⛔ **AUTO-PUBLICACIÓN FRENADA** (score < {tope}): revisá antes de publicar.")
        elif impracticable and avg < LEARN_BELOW:
            line += (f" · ⚠️ El fix sugerido pide pauta/presupuesto, que está descartado: "
                     f"**no se guardó como lección**. Literal de Gemini: _{fix}_")
        elif fix and avg < LEARN_BELOW:
            line += f" · Fix aplicado a futuras corridas: _{fix}_"
        else:
            line += " · sin cambios (buen lote)"
        return {"line": line, "avg": avg, "publish_ok": publish_ok}
    except Exception as e:
        log.warning("text_judge_gate_failed", agent=agent_name, kind=kind, error=str(e)[:150])
        return {"line": "", "avg": None, "publish_ok": True}


def qa_and_learn(agent_name: str, kind: str, payload: str) -> str:
    """Juzga `payload`, y si el score es flojo (<LEARN_BELOW) registra el fix como
    LECCION para `agent_name`. Devuelve una línea markdown para el reporte ('' si no
    corrió). Best-effort: nunca levanta."""
    try:
        if not enabled():
            return ""
        res = judge(kind, payload)
        if not res:
            return ""
        avg = res.get("avg", 0)
        fix = (res.get("top_fix") or "").strip()
        learned = bool(fix and avg < LEARN_BELOW)
        if learned:
            from . import memory_store as ms
            ms.record_outcome(agent_name, f"QA de calidad (Gemini) sobre {kind}: {fix}")
        tail = f" · Fix aplicado a futuras corridas: _{fix}_" if learned else " · sin cambios (buen lote)"
        return f"\n## 🧪 QA Gemini\nScore promedio: **{avg}/100**{tail}"
    except Exception as e:
        log.warning("text_judge_qa_failed", agent=agent_name, kind=kind, error=str(e)[:150])
        return ""


def improve_text(agent_name: str, kind: str, text: str, regenerate,
                 *, below: int = 70, min_len_ratio: float = 0.6) -> Dict[str, Any]:
    """Evaluator-optimizer (el patrón de 'reliable agents': generar → juzgar → si flojo,
    corregir → re-juzgar). Juzga `text`; si el score < `below`, pide UNA revisión a
    `regenerate(text, fix)` y la re-juzga; se queda con la de MAYOR score (y solo si no se
    achicó por debajo de `min_len_ratio` del original, para no aceptar una versión mutilada).
    Registra el fix como LECCION igual. Best-effort: si el juez no está o algo falla, devuelve
    el texto original intacto. `regenerate(text, fix) -> str|None`.
    Devuelve {text, avg, improved, line}."""
    try:
        if not enabled() or not (text or "").strip():
            return {"text": text, "avg": None, "improved": False, "line": ""}
        res = judge(kind, text)
        if not res:
            return {"text": text, "avg": None, "improved": False, "line": ""}
        avg = res.get("avg", 0)
        fix = (res.get("top_fix") or "").strip()
        head = "\n## 🧪 QA Gemini (evaluator-optimizer)"
        if not (fix and avg < below):
            return {"text": text, "avg": avg, "improved": False,
                    "line": f"{head}\nScore: **{avg}/100** · sin cambios (buen lote)"}
        # Un solo pase de auto-corrección con el fix como guía.
        new_text = None
        try:
            new_text = regenerate(text, fix)
        except Exception as e:
            log.warning("improve_regen_failed", agent=agent_name, error=str(e)[:150])
        final_text, final_avg, improved = text, avg, False
        if new_text and len(new_text.strip()) >= len(text.strip()) * min_len_ratio:
            res2 = judge(kind, new_text)
            new_avg = res2.get("avg", 0) if res2 else 0
            if new_avg > avg:
                final_text, final_avg, improved = new_text, new_avg, True
        # Lección para mejorar de raíz a futuro (además del fix in-run).
        from . import memory_store as ms
        ms.record_outcome(agent_name, f"QA de calidad (Gemini) sobre {kind}: {fix}")
        tail = (f" · ✍️ auto-corregido {avg}→{final_avg}/100"
                if improved else f" · fix aplicado a futuras corridas: _{fix}_")
        log.info("text_judge_improved", agent=agent_name, kind=kind,
                 avg=avg, final=final_avg, improved=improved)
        return {"text": final_text, "avg": final_avg, "improved": improved,
                "line": f"{head}\nScore: **{final_avg}/100**{tail}"}
    except Exception as e:
        log.warning("text_judge_improve_failed", agent=agent_name, kind=kind, error=str(e)[:150])
        return {"text": text, "avg": None, "improved": False, "line": ""}


def competitor_gap(agent_name: str, our_text: str, aplica: str = "imagen") -> str:
    """Cierra el loop competitivo: Gemini compara NUESTRA pieza recién generada contra el
    ESTUDIO del competidor (reel_study) y devuelve la ÚNICA táctica que nos falta. La registra
    como lección creativa → se reinyecta en la próxima pieza. Read-only sobre nuestro contenido
    (no regenera nada). Best-effort: sin juez/estudio o si falla, devuelve ''."""
    try:
        if not enabled() or not (our_text or "").strip():
            return ""
        from . import reel_study, creative_learnings, vision
        comp = reel_study.block().strip()
        if not comp:
            return ""
        prompt = (
            "Sos director creativo de Automiq (agencia argentina de IA). Arriba te paso el "
            "ESTUDIO del contenido de la competencia (Gemini miró sus reels). Abajo va UNA pieza "
            "NUESTRA recién generada. Comparalas y devolvé EXCLUSIVAMENTE la ÚNICA táctica de la "
            "competencia que a nuestra pieza le FALTA y más le sumaría, en 1 frase accionable y "
            "concreta (sin preámbulo, sin listas).\n\n=== ESTUDIO DE LA COMPETENCIA ===\n" + comp)
        gap = (vision.synthesize(our_text[:4000], prompt, max_tokens=200) or "").strip()
        gap = gap.strip("-•* ").strip()
        if len(gap) < 12:
            return ""
        creative_learnings.add(gap, "gap_vs_competencia", aplica)
        log.info("competitor_gap_learned", agent=agent_name, aplica=aplica)
        return f"\n## 🔍 Brecha vs competencia (aprendida para la próxima)\n{gap}"
    except Exception as e:
        log.warning("competitor_gap_failed", agent=agent_name, error=str(e)[:150])
        return ""
