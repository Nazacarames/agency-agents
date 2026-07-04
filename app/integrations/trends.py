"""
trends — trae tendencias reales del MCP de TrendsMCP y las deja como un bloque que se
inyecta al playbook de los agentes de contenido (content/social/tiktok/creative).

Lo más accionable para nosotros es el MOMENTUM de nuestros temas (get_growth): saber
qué está subiendo/bajando en búsquedas → los agentes priorizan en hooks/copy lo que
sube. El zeitgeist global (get_top_trends) va como referencia de trend-jacking, con la
advertencia de no forzarlo.

Refresh SEMANAL (free tier 100 req/mes). Best-effort: si falla, no rompe nada.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import List

from ..log import get_logger
from . import trends_client as tc

log = get_logger("trends")

_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
_FILE = _DATA_DIR / "trends-block.md"

# Temas de nuestro nicho a vigilar (búsqueda Google). Editable.
NICHE_KEYWORDS = [
    "inteligencia artificial", "automatización", "agente de ia",
    "chatbot whatsapp", "chatgpt", "whatsapp business",
]


def _arrow(direction: str, pct) -> str:
    d = (direction or "").lower()
    try:
        p = f"{abs(float(pct)):.0f}%"
    except Exception:
        p = ""
    if "incre" in d or "up" in d or "rising" in d:
        return f"⬆️ subiendo {p}".strip()
    if "decre" in d or "down" in d or "falling" in d:
        return f"⬇️ bajando {p}".strip()
    return f"➡️ estable {p}".strip()


def refresh() -> dict:
    """Reconsulta las tendencias y reescribe data/trends-block.md. Devuelve {ok, ...}."""
    if not tc.enabled():
        return {"ok": False, "reason": "sin TRENDS_API_KEY"}
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines: List[str] = []
    momentum = 0
    for kw in NICHE_KEYWORDS:
        g = tc.growth(kw, period="3M")
        if isinstance(g, dict) and g.get("direction"):
            lines.append(f"- {kw}: {_arrow(g.get('direction'), g.get('growth'))}")
            momentum += 1
    zeit = []
    for rank_term in (tc.top_trends("Google Trends", limit=8) or [])[:8]:
        if isinstance(rank_term, (list, tuple)) and len(rank_term) >= 2:
            zeit.append(str(rank_term[1]))

    if momentum == 0 and not zeit:
        log.warning("trends_refresh_empty")
        return {"ok": False, "reason": "sin datos"}

    block = ["=== TENDENCIAS AHORA (datos reales, " + today + ") ==="]
    if lines:
        block.append("Momentum de NUESTROS temas (búsqueda Google, últimos 3 meses):")
        block += lines
        block.append("Regla: priorizá en el hook/copy los temas que están SUBIENDO; a los que "
                     "bajan bajales el volumen (no los abandones).")
    if zeit:
        block.append("\nZeitgeist global del momento (solo para trend-jacking si CRUZA natural "
                     "con automatización/PyMEs — NO lo fuerces): " + ", ".join(zeit))
    block.append("=== fin tendencias ===")
    text = "\n".join(block)
    try:
        _DATA_DIR.mkdir(exist_ok=True)
        _FILE.write_text(text, encoding="utf-8")
    except Exception as e:
        log.error("trends_save_failed", error=str(e)[:150])
        return {"ok": False, "reason": "no se pudo guardar"}
    log.info("trends_refresh_ok", momentum=momentum, zeitgeist=len(zeit))
    return {"ok": True, "momentum": momentum, "zeitgeist": len(zeit)}


def load_block() -> str:
    """Bloque de tendencias vigente ('' si nunca se refrescó)."""
    try:
        t = _FILE.read_text(encoding="utf-8")
        return t.strip()
    except FileNotFoundError:
        return ""
    except Exception as e:
        log.warning("trends_load_failed", error=str(e)[:150])
        return ""
