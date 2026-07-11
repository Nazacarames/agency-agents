"""
roundtable — mesa redonda semanal ENTRE agentes (debate real, no reportes aislados).

Pedido del usuario (2026-07-10): que los agentes hablen y debatan entre ellos y
que esa comunicación los potencie. Formato:

  1. Ronda 1 — cada participante (con SU system prompt y SUS números) propone
     el cambio más importante de la semana y critica lo ya dicho.
  2. Ronda 2 — cada uno responde a los demás (acuerda, refuta, mejora).
  3. Síntesis — el chief of staff modera: acuerdos concretos, disensos, y
     reparte `LECCION:` (al store de aprendizaje) y `NOTA_PARA(<agente>):`
     (al buzón) para que lo debatido llegue a la próxima corrida de cada uno.

Corre lunes 07:30 ART (antes del brief de 08:30, que la lee como un reporte
más). LLM: NVIDIA (GLM/DeepSeek, gratis) con fallback MiniMax. Best-effort:
una voz que falla se saltea, la mesa sigue.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

from ..config import get_settings
from ..log import get_logger

log = get_logger("roundtable")

_DATA = Path(__file__).resolve().parent.parent.parent / "data"

# Voces de la mesa (diversidad de perspectivas: growth/creatividad/contenido/ventas).
PARTICIPANTS = ["growth_hacker", "creative_strategist", "content_creator", "outbound"]
MODERATOR = "chief_of_staff"

_TURN_MAX_TOKENS = 700
_SYNTH_MAX_TOKENS = 1500


def _complete(agent, system: str, user: str, max_tokens: int) -> str:
    """Completion con el provider del agente (NVIDIA) y fallback MiniMax."""
    s = get_settings()
    provider = getattr(agent, "llm_provider", "") or "glm"
    try:
        from ..clients.nvidia import complete_with_provider
        r = complete_with_provider(provider, s, system, user, max_tokens, 0.6)
        return (r.text or "").strip()
    except Exception as e:
        log.warning("roundtable_nvidia_fallback", agent=agent.name, error=str(e)[:120])
    try:
        from ..clients.minimax import MiniMaxClient
        with MiniMaxClient(s) as mc:
            r = mc.complete(system, [{"role": "user", "content": user}],
                            max_tokens=max_tokens, temperature=0.6)
            return (r.text or "").strip()
    except Exception as e:
        log.error("roundtable_voice_failed", agent=agent.name, error=str(e)[:150])
        return ""


def _material() -> str:
    """Números duros + reportes recientes (reusa los insumos del chief)."""
    from ..agents.chief_of_staff import _hard_numbers, _recent_artifacts
    numbers = _hard_numbers()
    reports = _recent_artifacts()
    return ("## NÚMEROS DUROS DEL NEGOCIO\n" + (numbers or "(sin datos)")
            + "\n\n## REPORTES RECIENTES DEL EQUIPO (truncados)\n"
            + (reports or "(sin reportes)"))


def run_roundtable(topic: Optional[str] = None) -> Dict:
    from ..agents.registry import get_agent
    from ..agents._common import today_ar, sanitize_model_text

    today = today_ar()
    material = _material()
    tema = (topic or "").strip() or (
        "¿Cuál es EL cambio de mayor impacto que el equipo debería hacer esta semana "
        "para conseguir la primera reunión con una distribuidora y mejorar los números?"
    )

    thread: List[str] = []   # ["**agente**: texto", ...]

    def _thread_txt() -> str:
        return "\n\n".join(thread) if thread else "(sos el primero en hablar)"

    # ── Ronda 1: propuesta + crítica de lo ya dicho ──
    for name in PARTICIPANTS:
        try:
            ag = get_agent(name)
        except Exception:
            continue
        user = (
            f"# MESA REDONDA SEMANAL DEL EQUIPO — {today}\n\n"
            f"TEMA: {tema}\n\n{material}\n\n"
            "## LO QUE DIJERON ANTES QUE VOS\n" + _thread_txt() + "\n\n"
            "## TU TURNO (Ronda 1)\n"
            f"Hablás como **{name}**, desde TU especialidad. En ≤150 palabras: "
            "(1) tu propuesta CONCRETA de la semana con el porqué (con números del "
            "material), y (2) si alguien ya habló, marcá en qué NO estás de acuerdo "
            "o qué le falta a su propuesta. Sin diplomacia vacía: debatí en serio. "
            "Español rioplatense, primera persona."
        )
        text = _complete(ag, ag.system_prompt, user, _TURN_MAX_TOKENS)
        text, _ = sanitize_model_text(text)
        if text:
            thread.append(f"**{name}** (ronda 1):\n{text}")

    # ── Ronda 2: responder a los demás ──
    for name in PARTICIPANTS:
        try:
            ag = get_agent(name)
        except Exception:
            continue
        user = (
            f"# MESA REDONDA SEMANAL — {today} (Ronda 2)\n\n"
            f"TEMA: {tema}\n\n## EL DEBATE HASTA ACÁ\n" + _thread_txt() + "\n\n"
            f"## TU TURNO\nSos **{name}**. En ≤100 palabras respondé a los demás: "
            "qué acordás, qué refutás (con argumento), y tu posición FINAL para la "
            "síntesis. Si te convencieron, decilo y ajustá tu propuesta."
        )
        text = _complete(ag, ag.system_prompt, user, _TURN_MAX_TOKENS)
        text, _ = sanitize_model_text(text)
        if text:
            thread.append(f"**{name}** (ronda 2):\n{text}")

    if not thread:
        log.error("roundtable_empty")
        return {"ok": False, "reason": "ninguna voz respondió"}

    # ── Síntesis del moderador ──
    try:
        chief = get_agent(MODERATOR)
    except Exception:
        chief = None
    synth_user = (
        f"# MESA REDONDA — {today}\nTEMA: {tema}\n\n## DEBATE COMPLETO\n"
        + _thread_txt() + "\n\n"
        "## TU ROL: MODERADOR\nSintetizá la mesa en este formato EXACTO:\n"
        "# 🗣️ Mesa redonda — " + today + "\n"
        "## 💬 El debate en 5 líneas\n(qué se discutió y dónde chocaron)\n"
        "## ✅ Acuerdos de la semana\n(máx 3, concretos y medibles, con dueño)\n"
        "## ⚔️ Disensos abiertos\n(si los hay; qué dato los resolvería)\n"
        "## 📌 Para que el equipo aprenda y ejecute\n"
        "Emití líneas literales (el sistema las reparte automáticamente):\n"
        "- `LECCION: <aprendizaje durable del debate>` (máx 2)\n"
        "- `NOTA_PARA(<agente>): <instrucción concreta que salió de la mesa>` "
        "(una por agente afectado, máx 4; agentes válidos: "
        + ", ".join(PARTICIPANTS + ["web_auditor", "social_media", "tiktok_creator",
                                    "seo_specialist", "media_auditor"]) + ")"
    )
    synthesis = _complete(chief, chief.system_prompt, synth_user,
                          _SYNTH_MAX_TOKENS) if chief else ""
    synthesis, _ = sanitize_model_text(synthesis)

    # Repartir lo acordado — llega a la próxima corrida de cada agente:
    # NOTA_PARA(x) → buzón de x; LECCION → la aprenden TODOS los participantes
    # (record_outcome dedupa y refuerza por agente).
    if synthesis:
        try:
            import re
            from . import agent_inbox
            from . import memory_store as ms
            from ..agents.registry import list_agents as _all
            valid = {a.name for a in _all()}
            sent = 0
            for m in re.finditer(r"^[\s>*`\-]*NOTA_PARA\(([a-z_]+)\)\s*[:：]\s*(.+)$",
                                 synthesis, re.IGNORECASE | re.MULTILINE):
                to, note = m.group(1).lower(), m.group(2).strip().strip("`*")
                if to in valid and len(note) >= 10 and sent < 4:
                    if agent_inbox.leave("mesa_redonda", to, note):
                        sent += 1
            learned = 0
            for m in re.finditer(r"^[\s>*`\-]*LECCI[OÓ]N\s*[:：]\s*(.+)$",
                                 synthesis, re.IGNORECASE | re.MULTILINE):
                lesson = m.group(1).strip().strip("`*")
                if 15 <= len(lesson) <= 300 and learned < 2:
                    for name in PARTICIPANTS:
                        ms.record_outcome(name, lesson)
                    learned += 1
            log.info("roundtable_distributed", notes=sent, lessons=learned)
        except Exception as e:
            log.warning("roundtable_harvest_failed", error=str(e)[:150])

    full_md = (synthesis or "# 🗣️ Mesa redonda — " + today) + \
        "\n\n---\n\n## 📜 Transcripción del debate\n\n" + "\n\n".join(thread)

    # Persistir (el chief la lee en el brief de las 08:30 como un reporte más)
    try:
        _DATA.mkdir(exist_ok=True)
        (_DATA / f"roundtable-report-{today}.md").write_text(full_md, encoding="utf-8")
    except Exception as e:
        log.warning("roundtable_persist_failed", error=str(e)[:150])

    # Discord (canal del chief of staff)
    try:
        from ..clients.discord import DiscordWebhook
        s = get_settings()
        if s.discord_configured:
            dw = DiscordWebhook(s)
            dw.send_agent_output(agent_name="🗣️ Mesa redonda del equipo", text=full_md,
                                 run_id=f"roundtable-{today}",
                                 url=s.discord_webhook_for(MODERATOR))
            dw.close()
    except Exception as e:
        log.warning("roundtable_discord_failed", error=str(e)[:150])

    log.info("roundtable_done", turns=len(thread), synth_chars=len(synthesis or ""))
    return {"ok": True, "turns": len(thread), "synthesis_chars": len(synthesis or "")}
