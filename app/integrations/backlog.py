"""
backlog — los hallazgos que hay que EJECUTAR, con edad y dueño.

Por qué existe: los agentes reportan el mismo hallazgo un día tras otro y nadie
puede decir hace cuánto está abierto, porque la prosa del reporte de ayer no es
un registro. Al 2026-08-11 el trío "H1 del home vacío + 9 contadores en 0 +
falta Meta Pixel/GA4" llevaba 4 cierres consecutivos del Chief y ~3 semanas sin
ejecutarse: las 3 auditorías lo re-escribían cada día y ahí moría, porque el que
audita no tiene manos y el que tiene manos (web_optimizer) no leía sus reportes.

Un ítem se abre UNA sola vez, acumula días y cuántas veces se re-reportó, y se
cierra SÓLO con evidencia. Eso es lo que convierte "lo volvimos a mencionar" en
"lleva 21 días abierto, reportado 12 veces" — el dato que hoy no existe en
ningún lado y sin el cual no hay presión para ejecutar nada.

El área dice QUIÉN puede cerrarlo, que es la distinción que faltaba:
  - `web`    → la landing. Lo ejecuta web_optimizer (baja el deploy, edita, redeploya).
  - `dev`    → el código del sistema de agentes. NINGÚN agente puede: se pide en
               el panel/Claude Code. Delegarlo a un agente es lo que hizo que la
               misma orden a outbound se re-delegara dos veces sin efecto.
  - `humano` → decisión, aprobación, pago, credencial. No hay agente que lo destrabe.

Marcadores (los emite cualquier agente en su output; se cosechan en base.py,
igual que NOTA_PARA/LECCION):
    PENDIENTE(<area>): <título>
    RESUELTO(<id>): <evidencia de que quedó hecho>
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..log import get_logger
from .jsonstore import write_json_atomic

log = get_logger("backlog")

_FILE = Path(__file__).resolve().parent.parent.parent / "data" / "backlog.json"

AREAS = ("web", "dev", "humano")
# Dos redacciones del mismo hallazgo tienen que ser UN ítem: el LLM escribe "H1
# del home vacío" un día y "el home no tiene H1" al siguiente. Sin esto el store
# se llena de casi-duplicados y la edad — que es todo el valor — se resetea sola.
_SIMILAR = 0.82
RESUELTO_TTL_DIAS = 90


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _norm(s: str) -> str:
    """Para comparar títulos: sin acentos, sin puntuación, minúsculas."""
    s = unicodedata.normalize("NFKD", (s or "").lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9 ]+", " ", re.sub(r"\s+", " ", s)).strip()


def _load() -> Dict[str, Any]:
    try:
        data = json.loads(_FILE.read_text(encoding="utf-8"))
        data.setdefault("items", [])
        return data
    except Exception:
        return {"items": []}


def _save(data: Dict[str, Any]) -> None:
    write_json_atomic(_FILE, data, indent=1)


def _dias(desde: str) -> int:
    try:
        d = datetime.fromisoformat(desde)
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return max(0, (datetime.now(timezone.utc) - d).days)
    except Exception:
        return 0


def _match(items: List[Dict[str, Any]], area: str, titulo: str) -> Optional[Dict[str, Any]]:
    """El ítem abierto del mismo área que ya dice lo mismo, si existe."""
    n = _norm(titulo)
    for it in items:
        if it.get("estado") != "abierto" or it.get("area") != area:
            continue
        otro = _norm(it.get("titulo", ""))
        if otro == n or SequenceMatcher(None, otro, n).ratio() >= _SIMILAR:
            return it
    return None


def abrir(area: str, titulo: str, origen: str = "", dias_atras: int = 0) -> Optional[Dict[str, Any]]:
    """Abre un pendiente (o suma una re-aparición al que ya estaba). Best-effort.

    `dias_atras` es para cargar a mano lo que ya venía arrastrándose: un hallazgo
    que lleva tres semanas dando vueltas por los reportes no puede entrar al store
    con edad cero, porque la edad es justamente lo que tiene que hacer presión.
    """
    area = (area or "").strip().lower()
    titulo = " ".join((titulo or "").split())[:300]
    if area not in AREAS or len(titulo) < 10:
        return None
    data = _load()
    ya = _match(data["items"], area, titulo)
    if ya:
        # No pisamos el título original: la primera redacción es la que el humano
        # ya leyó en briefs anteriores, y cambiarla cada día hace irreconocible al
        # mismo ítem. Sólo sube el contador y la última vez que se lo vio.
        ya["veces"] = int(ya.get("veces", 1)) + 1
        ya["visto_ultima"] = _now()
        if origen and origen not in (ya.get("origenes") or []):
            ya.setdefault("origenes", []).append(origen)
        _save(data)
        return ya
    desde = _now()
    if dias_atras > 0:
        desde = (datetime.now(timezone.utc) - timedelta(days=int(dias_atras))).isoformat()
    item = {
        "id": hashlib.sha1(f"{area}:{_norm(titulo)}".encode()).hexdigest()[:8],
        "area": area, "titulo": titulo, "estado": "abierto",
        "abierto": desde, "visto_ultima": _now(), "veces": 1,
        "origenes": [origen] if origen else [],
        "evidencia": "", "resuelto_at": "",
    }
    data["items"].append(item)
    _save(data)
    log.info("backlog_abierto", id=item["id"], area=area, origen=origen)
    return item


def resolver(item_id: str, evidencia: str, por: str = "") -> bool:
    """Cierra un pendiente. Exige evidencia: sin eso, 'resuelto' es una opinión."""
    evidencia = " ".join((evidencia or "").split())[:500]
    if len(evidencia) < 10:
        return False
    data = _load()
    for it in data["items"]:
        if it.get("id") == item_id and it.get("estado") == "abierto":
            it.update({"estado": "resuelto", "evidencia": evidencia,
                       "resuelto_at": _now(), "resuelto_por": por})
            _podar(data)
            _save(data)
            log.info("backlog_resuelto", id=item_id, por=por,
                     dias=_dias(it.get("abierto", "")))
            return True
    return False


def _podar(data: Dict[str, Any]) -> None:
    """Saca los resueltos viejos (el histórico vive en los reportes, no acá)."""
    data["items"] = [it for it in data["items"]
                     if it.get("estado") == "abierto"
                     or _dias(it.get("resuelto_at") or it.get("abierto", "")) < RESUELTO_TTL_DIAS]


def abiertos(area: str = "") -> List[Dict[str, Any]]:
    """Pendientes abiertos, del más viejo al más nuevo, con `dias` calculado."""
    out = []
    for it in _load()["items"]:
        if it.get("estado") != "abierto":
            continue
        if area and it.get("area") != area:
            continue
        out.append({**it, "dias": _dias(it.get("abierto", ""))})
    out.sort(key=lambda i: -i["dias"])
    return out


def resumen() -> Dict[str, Any]:
    ab = abiertos()
    return {
        "abiertos": len(ab),
        "por_area": {a: sum(1 for i in ab if i["area"] == a) for a in AREAS},
        "mas_viejo_dias": ab[0]["dias"] if ab else 0,
        "resueltos_30d": sum(1 for it in _load()["items"]
                             if it.get("estado") == "resuelto"
                             and _dias(it.get("resuelto_at", "")) <= 30),
    }


def bloque(area: str = "", limite: int = 12, titulo: str = "") -> str:
    """Los pendientes como texto para meter en el prompt de un agente."""
    ab = abiertos(area)[:limite]
    if not ab:
        return ""
    cab = titulo or ("## PENDIENTES ABIERTOS" if not area
                     else f"## PENDIENTES ABIERTOS ({area})")
    filas = [f"- `{i['id']}` [{i['area']}] **{i['titulo']}** — abierto hace "
             f"{i['dias']} día(s), reportado {i.get('veces', 1)} vez/veces"
             + (f" (por {', '.join(i.get('origenes') or [])})" if i.get("origenes") else "")
             for i in ab]
    return cab + "\n" + "\n".join(filas)
