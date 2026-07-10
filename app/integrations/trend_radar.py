"""
trend_radar — la PÁGINA DE TENDENCIAS: todos los días revisa fuentes reales del nicho
(Anthropic, OpenAI, IA para negocios, WhatsApp/Meta, e-commerce AR), etiqueta cada
novedad como `potencial de gancho` / `explicativo` / `ignorar` (Gemini), rankea las 5
con más potencial y manda el resumen por Discord a las 7 AM.

Distinto de trends.py (momentum de búsquedas vía TrendsMCP): esto son NOTICIAS del día
para trend-jacking en los guiones. Store: data/trend-radar.json. Best-effort siempre.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

from ..log import get_logger

log = get_logger("trend_radar")

_DATA = Path(__file__).resolve().parent.parent.parent / "data"
_FILE = _DATA / "trend-radar.json"

# Las fuentes que se revisan cada mañana (query → etiqueta de fuente).
SOURCES = [
    ("Anthropic Claude news announcement", "Anthropic"),
    ("OpenAI announcement news this week", "OpenAI"),
    ("inteligencia artificial novedades empresas", "IA / negocios"),
    ("WhatsApp Business API novedades", "WhatsApp/Meta"),
    ("ecommerce argentina novedades tiendanube mercado libre", "E-commerce AR"),
    ("AI agents automation small business news", "Agentes IA"),
    ("viral marketing AI video trend tiktok", "Contenido/TikTok"),
]

_TAG_PROMPT = (
    "Sos el radar de tendencias de una agencia argentina que hace TikToks/Reels sobre IA "
    "y bots de WhatsApp para PyMEs. Abajo hay novedades numeradas (título + snippet). "
    "Para CADA una devolvé UNA línea con este formato EXACTO:\n"
    "<número>|<etiqueta>|<idea de gancho o vacío>\n"
    "Etiquetas posibles: gancho (sirve para un video con potencial viral YA), "
    "explicativo (sirve para contenido educativo), ignorar (viejo, irrelevante o humo). "
    "Si es 'gancho', la idea de gancho va en español rioplatense, filosa, máx 12 palabras. "
    "Nada más que esas líneas. NOVEDADES:\n"
)


def load_radar() -> Dict:
    try:
        return json.loads(_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _collect() -> List[Dict]:
    """Busca las fuentes y junta items únicos {title, url, snippet, source}."""
    try:
        from packs.automiq.tools.web_search import web_search
    except Exception as e:
        log.warning("trend_radar_no_search", error=str(e)[:150])
        return []
    items: List[Dict] = []
    seen = set()
    for q, src in SOURCES:
        try:
            for r in (web_search(q, 4) or [])[:4]:
                t = (r.get("title") or "").strip()
                if not t or t.lower() in seen:
                    continue
                seen.add(t.lower())
                items.append({"title": t, "url": r.get("url", ""),
                              "snippet": (r.get("snippet") or "")[:220], "source": src})
        except Exception as e:
            log.warning("trend_radar_query_failed", q=q[:40], error=str(e)[:120])
    return items


def _tag(items: List[Dict]) -> List[Dict]:
    """Etiqueta cada item con Gemini (gancho/explicativo/ignorar + idea de gancho)."""
    try:
        from . import vision
        if not vision.enabled():
            return items
        blob = "\n".join(f"{i+1}. {it['title']} — {it['snippet']}"
                         for i, it in enumerate(items))
        out = vision.synthesize(blob, _TAG_PROMPT, max_tokens=1600) or ""
        for line in out.splitlines():
            m = re.match(r"\s*(\d+)\s*\|\s*(gancho|explicativo|ignorar)\s*\|\s*(.*)", line.strip(),
                         re.IGNORECASE)
            if not m:
                continue
            idx = int(m.group(1)) - 1
            if 0 <= idx < len(items):
                items[idx]["tag"] = m.group(2).lower()
                items[idx]["hook_idea"] = m.group(3).strip()
    except Exception as e:
        log.warning("trend_radar_tag_failed", error=str(e)[:150])
    return items


def refresh() -> Dict:
    """Revisa las fuentes, etiqueta y escribe data/trend-radar.json."""
    items = _collect()
    if not items:
        return {"ok": False, "reason": "sin resultados de búsqueda"}
    items = _tag(items)
    order = {"gancho": 0, "explicativo": 1, "ignorar": 2}
    items.sort(key=lambda i: order.get(i.get("tag", "explicativo"), 1))
    data = {"updated_at": datetime.now(timezone.utc).isoformat(), "items": items}
    from .jsonstore import write_json_atomic
    write_json_atomic(_FILE, data, indent=1)
    n_hook = sum(1 for i in items if i.get("tag") == "gancho")
    log.info("trend_radar_ok", items=len(items), ganchos=n_hook)
    return {"ok": True, "items": len(items), "ganchos": n_hook}


def send_digest() -> Dict:
    """Manda el top 5 'potencial de gancho' por Discord (el resumen de las 7 AM)."""
    data = load_radar()
    top = [i for i in data.get("items", []) if i.get("tag") == "gancho"][:5]
    if not top:
        return {"ok": False, "reason": "sin ganchos hoy"}
    try:
        from ..config import get_settings
        from ..clients.discord import DiscordWebhook
        s = get_settings()
        if not getattr(s, "discord_configured", False):
            return {"ok": False, "reason": "discord no configurado"}
        lines = [f"**{i+1}.** {t['title']}" + (f"\n> 🎣 {t['hook_idea']}" if t.get("hook_idea") else "")
                 + (f"\n> {t['url']}" if t.get("url") else "")
                 for i, t in enumerate(top)]
        msg = "📡 **Radar de tendencias — top 5 con potencial de gancho**\n" + "\n".join(lines)
        dw = DiscordWebhook(s)
        dw.send(msg[:1900])
        dw.close()
        return {"ok": True, "sent": len(top)}
    except Exception as e:
        log.warning("trend_radar_digest_failed", error=str(e)[:150])
        return {"ok": False, "reason": str(e)[:150]}


def block(n: int = 5) -> str:
    """Bloque para los agentes: las novedades de HOY con potencial de gancho."""
    try:
        data = load_radar()
        top = [i for i in data.get("items", []) if i.get("tag") == "gancho"][:n]
        if not top:
            return ""
        lines = [f"- {t['title']}" + (f" → gancho: \"{t['hook_idea']}\"" if t.get("hook_idea") else "")
                 for t in top]
        return ("\n\n=== RADAR DE HOY (novedades con potencial de gancho — trend-jacking) ===\n"
                + "\n".join(lines) + "\n=== fin radar ===\n")
    except Exception:
        return ""
