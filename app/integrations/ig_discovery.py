"""
ig_discovery — descubre AUTOMÁTICAMENTE los reels recientes de competidores/marcas de
referencia vía la Instagram **Business Discovery API** (oficial). Resuelve "que los
agentes consigan las URLs solos": no hace falta pegar URLs a mano ni scrapear perfiles
(el extractor de perfiles de yt-dlp está roto) ni cookies del browser.

Ventaja clave: es API oficial de Meta → **NO se bloquea por IP de datacenter** (a
diferencia de yt-dlp), así que puede correr en prod. Reusa el token de publicación que
ya tenemos (meta_page_token + ig_business_id), sin credencial nueva.

Devuelve por cada media: permalink (la URL del reel) + media_url (el video en el CDN,
descargable directo) + caption. Best-effort: si algo falla, devuelve [].
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Dict, List

from ..config import get_settings
from ..log import get_logger

log = get_logger("ig_discovery")

_GRAPH = "https://graph.facebook.com/v21.0"

# Handles de IG reales VERIFICADOS 2026-07-05 con Business Discovery (ojo a las trampas:
# Tiendanube publica como "nuvemshop"; Mercado Libre AR como "mercadolibre.arg").
IG_HANDLES = {
    "kommo":      "kommocrm",
    "manychat":   "manychat",
    "shopify":    "shopify",
    "tiendanube": "nuvemshop",
    "meli":       "mercadolibre.arg",
}


def enabled() -> bool:
    s = get_settings()
    return bool(getattr(s, "ig_business_id", "") and getattr(s, "meta_page_token", ""))


def recent_media(handle: str, n: int = 3) -> List[Dict]:
    """Media reciente pública de una cuenta business (por username). [] si falla."""
    s = get_settings()
    if not enabled() or not handle:
        return []
    fields = (f"business_discovery.username({handle})"
              f"{{username,followers_count,media.limit({n})"
              f"{{media_type,media_product_type,media_url,permalink,caption,timestamp}}}}")
    q = urllib.parse.urlencode({"fields": fields, "access_token": s.meta_page_token})
    try:
        r = json.load(urllib.request.urlopen(f"{_GRAPH}/{s.ig_business_id}?{q}", timeout=30))
    except urllib.error.HTTPError as e:
        try:
            r = json.load(e)
        except Exception:
            return []
    except Exception as ex:
        log.warning("ig_discovery_failed", handle=handle, error=str(ex)[:150])
        return []
    if "error" in r:
        log.warning("ig_discovery_error", handle=handle,
                    msg=str(r["error"].get("message"))[:120])
        return []
    return (r.get("business_discovery", {}).get("media", {}).get("data") or [])


def recent_reels(handle: str, n: int = 15) -> List[Dict]:
    """Reels/videos con video_url descargable. `n` = ventana de media a escanear
    (las cuentas mezclan carruseles/fotos con reels → conviene escanear ~15)."""
    return [m for m in recent_media(handle, n)
            if m.get("media_type") == "VIDEO" and m.get("media_url")]


def discover_all(n: int = 3) -> Dict[str, List[Dict]]:
    """{clave: [reels]} para todo el roster de handles conocidos."""
    out: Dict[str, List[Dict]] = {}
    for key, handle in IG_HANDLES.items():
        reels = recent_reels(handle, n)
        if reels:
            out[key] = reels
    return out
