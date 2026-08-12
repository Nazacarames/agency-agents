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
import time
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


# Debajo de esto, "todo en cero" es una cuenta que recién arranca y no hay nada que
# concluir. Por encima, es el resultado de semanas de publicar.
_MIN_PIEZAS_SIN_TRACCION = 8


def block(n: int = 20) -> str:
    """Bloque para inyectar a los agentes de contenido: nuestro top/bottom real."""
    rows = analyze(n)
    if not rows:
        return ""
    if rows[0]["interactions"] == 0:
        # Con 2 o 3 piezas, todo en cero es una cuenta nueva y no dice nada. Con
        # muchas ya publicadas, es EL dato: lo que estamos haciendo no llega a
        # nadie. Callarlo era peor que no medir — los agentes seguían produciendo
        # más de lo mismo sin enterarse nunca (2026-08-12: 20 piezas, 0 interacciones).
        if len(rows) < _MIN_PIEZAS_SIN_TRACCION:
            return ""
        alcance = sum(r.get("reach") or 0 for r in rows)
        return (
            "\n\n=== LO NUESTRO NO ESTÁ TRACCIONANDO (dato real de IG) ===\n"
            f"Últimas {len(rows)} piezas publicadas: **0 interacciones** en todas "
            f"(alcance sumado: {alcance}).\n"
            "Esto NO se arregla escribiendo otra pieza igual. El problema está antes que "
            "el copy: distribución, hashtags, horario, formato o que todavía no hay "
            "audiencia a la que llegarle.\n"
            "Qué hacer HOY: proponé UN cambio de enfoque concreto y decí qué señal lo "
            "validaría. Si lo que hace falta es una decisión o un acceso que vos no tenés "
            "(pauta, colaboración, cambio de cuenta), anotalo con `PENDIENTE(humano): …` "
            "en vez de volver a proponer lo mismo.\n=== fin ===")
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


_CACHE: Dict[str, object] = {"t": 0.0, "txt": ""}


def cached_block(n: int = 20, ttl: float = 21600.0) -> str:
    """block() memoizado `ttl` segundos (6h por defecto). Generación y juez lo piden con
    segundos de diferencia; sin caché serían ~21 llamadas Graph repetidas por corrida.
    Best-effort: si block() falla, devuelve lo último cacheado ('' si nunca hubo)."""
    now = time.time()
    if now - float(_CACHE["t"]) < ttl:
        return str(_CACHE["txt"])
    try:
        _CACHE["txt"] = block(n)
    except Exception:
        pass  # deja el valor viejo
    _CACHE["t"] = now
    return str(_CACHE["txt"])
