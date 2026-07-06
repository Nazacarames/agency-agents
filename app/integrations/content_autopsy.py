"""
content_autopsy — analiza qué contenido NUESTRO funcionó (no el de la competencia).
Consulta las métricas reales de nuestras publicaciones de Instagram vía la Graph API
(mismo token de publicación), las rankea por engagement y arma un bloque "qué funcionó /
qué no" que se inyecta a los agentes de contenido → aprenden de DATOS PROPIOS
(complementa el visual scout, que aprende de la competencia).

Best-effort: si no hay token o falla, devuelve "" y no rompe nada.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Dict, List

from ..config import get_settings
from ..log import get_logger

log = get_logger("content_autopsy")

_GRAPH = "https://graph.facebook.com/v21.0"
_METRICS = "reach,likes,comments,saved,shares,total_interactions"


def enabled() -> bool:
    s = get_settings()
    return bool(getattr(s, "ig_business_id", "") and getattr(s, "meta_page_token", ""))


def _get(path: str, params: Dict) -> Dict:
    s = get_settings()
    params = {**params, "access_token": s.meta_page_token}
    url = f"{_GRAPH}/{path}?{urllib.parse.urlencode(params)}"
    try:
        return json.load(urllib.request.urlopen(url, timeout=30))
    except urllib.error.HTTPError as e:
        try:
            return json.load(e)
        except Exception:
            return {}
    except Exception as ex:
        log.warning("autopsy_http_failed", error=str(ex)[:150])
        return {}


def _our_media(n: int) -> List[Dict]:
    s = get_settings()
    r = _get(str(s.ig_business_id) + "/media",
             {"fields": "id,caption,media_type,media_product_type,permalink,timestamp", "limit": n})
    return r.get("data") or []


def _engagement(media_id: str) -> Dict[str, int]:
    r = _get(f"{media_id}/insights", {"metric": _METRICS})
    out: Dict[str, int] = {}
    for m in (r.get("data") or []):
        try:
            out[m["name"]] = int((m.get("values") or [{}])[0].get("value") or 0)
        except Exception:
            pass
    return out


def analyze(n: int = 20) -> List[Dict]:
    """Devuelve nuestros posts recientes con engagement, ordenados de mejor a peor."""
    if not enabled():
        return []
    rows: List[Dict] = []
    for m in _our_media(n):
        eng = _engagement(m["id"])
        score = eng.get("total_interactions") or (
            eng.get("likes", 0) + eng.get("comments", 0) + eng.get("saved", 0) + eng.get("shares", 0))
        rows.append({
            "caption": (m.get("caption") or "")[:90].replace("\n", " "),
            "type": m.get("media_product_type") or m.get("media_type"),
            "permalink": m.get("permalink"),
            "reach": eng.get("reach", 0),
            "interactions": score,
            "saved": eng.get("saved", 0),
            "shares": eng.get("shares", 0),
        })
    rows.sort(key=lambda r: r["interactions"], reverse=True)
    return rows


def block(n: int = 20) -> str:
    """Bloque para inyectar a los agentes de contenido: nuestro top/bottom real."""
    rows = analyze(n)
    # Silencio hasta que haya engagement real (cuenta nueva = todo 0 → no aporta señal).
    if not rows or rows[0]["interactions"] == 0:
        return ""
    top = [r for r in rows[:3] if r["interactions"] > 0]
    bottom = rows[-2:] if len(rows) > 4 else []
    lines = ["\n\n=== QUÉ FUNCIONÓ DE LO NUESTRO (datos reales de IG — replicá lo de arriba) ==="]
    for r in top:
        lines.append(f"✅ [{r['type']}] {r['interactions']} interacc · {r['saved']} guardados · "
                     f"{r['shares']} shares — \"{r['caption']}\"")
    for r in bottom:
        lines.append(f"❌ flojo [{r['type']}] {r['interactions']} interacc — \"{r['caption']}\"")
    lines.append("Replicá el formato/gancho de los ✅ y evitá el patrón de los ❌.\n=== fin ===")
    return "\n".join(lines)
