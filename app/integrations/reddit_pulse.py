"""
reddit_pulse — "voz de audiencia" del scout: escucha lo que la gente dice en Reddit
sobre chatbots / automatización / IA para PyMEs y destila los DOLORES reales, el
LENGUAJE textual y las OBJECIONES → data/audience-voice.md, inyectado a los agentes
de contenido como señal corta (igual que trends/radar).

Es texto (discurso de audiencia), NO video: complementa al visual scout (edición/hooks)
con QUÉ decir y en qué palabras, sin ensuciar el playbook de video.

Reddit cerró el JSON público (403 sin auth). Se usa el OAuth oficial "application-only"
(client_credentials) con un **token gratis de app tipo 'script'** — 2 min, sin aprobación:
  1. reddit.com/prefs/apps → "create app" → tipo **script** → redirect http://localhost
  2. copiar el client_id (bajo el nombre) y el secret
  3. setear REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET en Railway → esto se activa solo.
Sin las dos vars, enabled()=False y todo se saltea (best-effort, no rompe nada).
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any, Dict, List

import httpx

from ..log import get_logger

log = get_logger("reddit_pulse")

_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
_FILE = _DATA_DIR / "audience-voice.md"

# UA descriptiva (Reddit la exige o tira 429). Formato recomendado por Reddit.
_UA = "python:automiq-scout:1.1 (audiencia PyMEs)"

# Nuestro nicho, en las palabras que usa la audiencia (dueños de PyME evaluando
# bots/automatización). EN pesa más en Reddit; se suman queries en ES por si pega.
_QUERIES = [
    "whatsapp chatbot for business worth it",
    "AI automation small business results",
    "chatbot customer service experience",
    "automate customer messages whatsapp",
    "hired an AI agency",
    "chatbot atención al cliente negocio",
]

_TOK: Dict[str, Any] = {"v": "", "exp": 0.0}

_DISTILL_SYSTEM = (
    "Sos estratega de contenido de una agencia argentina de automatización con IA "
    "(bots de WhatsApp para PyMEs). Abajo hay posts/títulos REALES de Reddit de gente "
    "hablando del tema. Destilá SOLO lo accionable para ganchos de contenido, en "
    "español rioplatense, con EXACTAMENTE estas secciones markdown:\n"
    "## Dolores reales (en sus palabras)\n## Frases/lenguaje textual para robar en hooks\n"
    "## Objeciones a desactivar\n## Ángulos de contenido que esto sugiere\n"
    "Citá lo concreto (no generalices). Sé breve: máx ~300 palabras TOTAL. "
    "Nada de relleno ni disclaimers."
)


def enabled() -> bool:
    return bool(os.environ.get("REDDIT_CLIENT_ID") and os.environ.get("REDDIT_CLIENT_SECRET"))


def _token() -> str:
    """Token application-only (client_credentials), cacheado en proceso ~50 min."""
    if _TOK["v"] and _TOK["exp"] > time.time():
        return _TOK["v"]
    cid = os.environ.get("REDDIT_CLIENT_ID", "")
    sec = os.environ.get("REDDIT_CLIENT_SECRET", "")
    if not (cid and sec):
        return ""
    try:
        r = httpx.post("https://www.reddit.com/api/v1/access_token",
                       auth=(cid, sec), data={"grant_type": "client_credentials"},
                       headers={"User-Agent": _UA}, timeout=20.0)
        if r.status_code != 200:
            log.warning("reddit_token_failed", status=r.status_code)
            return ""
        data = r.json()
        _TOK["v"] = data.get("access_token", "")
        _TOK["exp"] = time.time() + min(int(data.get("expires_in", 3600)) - 60, 3000)
        return _TOK["v"]
    except Exception as e:
        log.warning("reddit_token_exc", error=str(e)[:150])
        return ""


def _search(query: str, n: int = 8, period: str = "month") -> List[Dict[str, Any]]:
    tok = _token()
    if not tok:
        return []
    try:
        r = httpx.get("https://oauth.reddit.com/search",
                      params={"q": query, "sort": "top", "t": period,
                              "limit": n, "type": "link"},
                      headers={"User-Agent": _UA, "Authorization": f"Bearer {tok}"},
                      timeout=20.0)
        if r.status_code != 200:
            return []
        out = []
        for c in r.json().get("data", {}).get("children", []):
            p = c.get("data", {})
            out.append({
                "title": (p.get("title") or "").strip(),
                "sub": p.get("subreddit", ""),
                "score": p.get("score", 0),
                "text": (p.get("selftext") or "").strip()[:300],
            })
        return out
    except Exception as e:
        log.warning("reddit_search_exc", q=query, error=str(e)[:120])
        return []


def refresh() -> Dict[str, Any]:
    """Escucha Reddit, destila la voz de audiencia y escribe data/audience-voice.md."""
    if not enabled():
        return {"ok": False, "reason": "REDDIT_CLIENT_ID/SECRET sin setear"}

    blocks: List[str] = []
    for q in _QUERIES:
        for p in _search(q, 8):
            line = f"- [r/{p['sub']} ↑{p['score']}] {p['title']}"
            if p["text"]:
                line += f" — {p['text']}"
            blocks.append(line)
    # dedup preservando orden
    seen, uniq = set(), []
    for b in blocks:
        if b not in seen:
            seen.add(b); uniq.append(b)
    if len(uniq) < 5:
        log.warning("reddit_pulse_thin", found=len(uniq))
        return {"ok": False, "reason": f"Reddit devolvió poco ({len(uniq)})"}

    user = "Posts reales de Reddit:\n\n" + "\n".join(uniq[:60]) + "\n\nDestilá la voz de audiencia."
    try:
        from ..config import get_settings
        from ..clients.minimax import MiniMaxClient
        with MiniMaxClient(get_settings()) as mc:
            resp = mc.complete(_DISTILL_SYSTEM, [{"role": "user", "content": user}],
                               max_tokens=1200, temperature=0.4)
        text = (resp.text or "").strip()
    except Exception as e:
        log.warning("reddit_distill_failed", error=str(e)[:150])
        return {"ok": False, "reason": "distill falló"}

    if len(text) < 200 or "Dolores" not in text:
        return {"ok": False, "reason": "destilado pobre"}

    today = time.strftime("%Y-%m-%d")
    body = ("=== VOZ DE AUDIENCIA — lo que dice la gente (Reddit, escuchado por el scout) ===\n"
            f"_Auto-destilado de posts reales de Reddit el {today}. Foco: qué decir y en qué palabras._\n\n"
            + text.strip() + "\n=== fin voz de audiencia ===\n")
    try:
        _DATA_DIR.mkdir(exist_ok=True)
        _FILE.write_text(body, encoding="utf-8")
    except Exception as e:
        log.error("reddit_pulse_save_failed", error=str(e)[:150])
        return {"ok": False, "reason": "no se pudo guardar"}
    log.info("reddit_pulse_ok", chars=len(text), posts=len(uniq))
    return {"ok": True, "chars": len(text), "posts": len(uniq)}


def block() -> str:
    """Bloque corto para inyectar a los agentes. '' si todavía no se escuchó nada."""
    try:
        t = _FILE.read_text(encoding="utf-8").strip()
        return ("\n\n" + t) if t else ""
    except Exception:
        return ""


if __name__ == "__main__":
    if not enabled():
        print("[reddit_pulse] REDDIT_CLIENT_ID/SECRET sin setear -> desactivado.\n"
              "Para activar (gratis, 2 min):\n"
              "  1. reddit.com/prefs/apps -> create app -> tipo 'script' -> redirect http://localhost\n"
              "  2. copia client_id (bajo el nombre) + secret\n"
              "  3. export REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET (o setealo en Railway)")
        raise SystemExit(0)
    print("[reddit_pulse] escuchando Reddit…")
    print(refresh())
