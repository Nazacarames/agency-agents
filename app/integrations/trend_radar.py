"""
trend_radar — la PÁGINA DE TENDENCIAS: todos los días busca NOTICIAS recientes (últimos
7 días, modo news de Tavily) del nicho REAL de Automiq (PyMEs argentinas, distribuidoras,
WhatsApp/ventas, costos PyME, IA aplicada), etiqueta cada novedad como `potencial de
gancho` / `explicativo` / `ignorar` (Gemini), rankea las 5 con más potencial y manda el
resumen por Discord a las 7 AM.

Distinto de trends.py (momentum de búsquedas vía TrendsMCP): esto son NOTICIAS del día
para trend-jacking en los guiones. Store: data/trend-radar.json. Best-effort siempre.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

from ..log import get_logger

log = get_logger("trend_radar")

_DATA = Path(__file__).resolve().parent.parent.parent / "data"
_FILE = _DATA / "trend-radar.json"

# Las fuentes que se revisan cada mañana (query, etiqueta, solo_medios_AR).
# Nicho REAL: dueños de PyMEs argentinas (distribuidoras, comercios, inmobiliarias)
# y lo que Automiq les vende (bots de WhatsApp, automatización de ventas/atención).
# Las queries locales se restringen a medios argentinos: el modo news de Tavily
# ignora el idioma y sin esto devuelve noticias yanquis (verificado 2026-07-14).
_AR_DOMAINS = ["infobae.com", "lanacion.com.ar", "clarin.com", "ambito.com",
               "cronista.com", "iprofesional.com", "iproup.com", "forbesargentina.com"]

SOURCES = [
    ("inteligencia artificial pymes", "IA / PyMEs AR", True),
    ("automatización ventas atención al cliente empresas", "Automatización AR", True),
    ("WhatsApp Business novedades empresas", "WhatsApp/Meta", False),
    ("distribuidoras mayoristas comercio", "Distribuidoras", True),
    ("costos pymes empleo comercios", "Dolor PyME", True),
    ("comercio electrónico pymes tiendanube mercado libre", "E-commerce AR", True),
    ("agentes de inteligencia artificial para negocios", "Agentes IA", False),
    ("lanzamiento OpenAI Anthropic Google inteligencia artificial", "Big IA", False),
]

_TAG_PROMPT = (
    "Sos el radar de tendencias de Automiq: agencia argentina que vende automatización "
    "con IA (bots de WhatsApp que responden clientes, toman pedidos y agendan) a PyMEs "
    "argentinas: distribuidoras mayoristas, comercios, inmobiliarias. El contenido son "
    "TikToks/Reels para DUEÑOS de esas PyMEs. Abajo hay novedades numeradas "
    "(fecha + título + snippet). Para CADA una devolvé UNA línea con este formato EXACTO:\n"
    "<número>|<etiqueta>|<idea de gancho o vacío>\n"
    "Etiquetas posibles:\n"
    "- ignorar: página de producto, landing SEO, homepage, listado genérico, nota vieja, "
    "o cualquier cosa que un dueño de PyME argentina no frenaría a mirar.\n"
    "- gancho: SOLO si es una novedad concreta y reciente que cruza DIRECTO con el nicho "
    "(plata, ventas, costos, WhatsApp, empleo, IA aplicable a una PyME). La idea de gancho: "
    "español rioplatense, filosa, máx 12 palabras, conectando la noticia con lo que vende Automiq.\n"
    "- explicativo: sirve para contenido educativo del nicho aunque no sea viral.\n"
    "Sé DURO: ante la duda, ignorar. Nada más que esas líneas. NOVEDADES:\n"
)


def load_radar() -> Dict:
    try:
        return json.loads(_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _news_search(q: str, n: int, ar_only: bool = False) -> List[Dict]:
    """NOTICIAS recientes (Tavily topic=news, últimos 7 días, con fecha).
    ar_only restringe a medios argentinos. Fallback: web_search genérico."""
    key = os.environ.get("TAVILY_API_KEY", "")
    if key:
        try:
            import httpx
            body = {"api_key": key, "query": q, "max_results": n,
                    "topic": "news", "days": 7, "search_depth": "basic"}
            if ar_only:
                body["include_domains"] = _AR_DOMAINS
            r = httpx.post("https://api.tavily.com/search", json=body, timeout=20.0)
            if r.status_code < 400:
                out = [{"title": (it.get("title") or "").strip(), "url": it.get("url", ""),
                        "snippet": (it.get("content") or "")[:220],
                        "date": (it.get("published_date") or "")[:16]}
                       for it in (r.json().get("results") or [])[:n]]
                if out:
                    return out
        except Exception as e:
            log.warning("trend_radar_news_failed", q=q[:40], error=str(e)[:120])
    try:
        from packs.automiq.tools.web_search import web_search
        return [{"title": (r.get("title") or "").strip(), "url": r.get("url", ""),
                 "snippet": (r.get("snippet") or "")[:220], "date": ""}
                for r in (web_search(q, n) or [])[:n]]
    except Exception as e:
        log.warning("trend_radar_no_search", error=str(e)[:150])
        return []


def _is_stale(date_str: str) -> bool:
    """True si la fecha parsea y tiene más de 10 días (con include_domains Tavily
    ignora el parámetro days y devuelve notas viejas — verificado 2026-07-14).
    Sin fecha no se descarta: el etiquetador decide."""
    try:
        d = datetime.strptime(date_str.strip(), "%a, %d %b %Y").replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - d).days > 10
    except Exception:
        return False


def _collect() -> List[Dict]:
    """Busca las fuentes y junta items únicos {title, url, snippet, date, source}."""
    items: List[Dict] = []
    seen = set()
    for q, src, ar_only in SOURCES:
        try:
            for r in _news_search(q, 4, ar_only):
                t = r["title"]
                if not t or t.lower() in seen or _is_stale(r.get("date", "")):
                    continue
                seen.add(t.lower())
                r["source"] = src
                items.append(r)
        except Exception as e:
            log.warning("trend_radar_query_failed", q=q[:40], error=str(e)[:120])
    return items


def _tag(items: List[Dict]) -> List[Dict]:
    """Etiqueta cada item con Gemini (gancho/explicativo/ignorar + idea de gancho)."""
    try:
        from . import vision
        if not vision.enabled():
            return items
        blob = "\n".join(f"{i+1}. [{it.get('date') or 'sin fecha'}] {it['title']} — {it['snippet']}"
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


def _top_hooks(items: List[Dict], n: int) -> List[Dict]:
    """Los mejores 'gancho' sin repetir la misma historia (dedup por idea de gancho)."""
    out: List[Dict] = []
    seen = set()
    for i in items:
        if i.get("tag") != "gancho":
            continue
        k = (i.get("hook_idea") or i.get("title") or "").strip().lower()
        if k in seen:
            continue
        seen.add(k)
        out.append(i)
        if len(out) >= n:
            break
    return out


def send_digest() -> Dict:
    """Manda el top 5 'potencial de gancho' por Discord (el resumen de las 7 AM)."""
    data = load_radar()
    top = _top_hooks(data.get("items", []), 5)
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
        top = _top_hooks(data.get("items", []), n)
        if not top:
            return ""
        lines = [f"- ({t.get('source', '?')}) {t['title']}"
                 + (f" → gancho: \"{t['hook_idea']}\"" if t.get("hook_idea") else "")
                 for t in top]
        return ("\n\n=== RADAR DE HOY (noticias REALES del nicho — trend-jacking) ===\n"
                + "\n".join(lines)
                + "\nUSALO: si alguna cruza natural con la pieza que estás armando, abrí el "
                "hook con esa novedad ('¿viste que...?') y aterrizala en el dolor del dueño "
                "de PyME. Cuando hay ganchos acá, al menos UNA pieza del día tiene que "
                "surfear el radar.\n=== fin radar ===\n")
    except Exception:
        return ""
