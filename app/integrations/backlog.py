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
# Gracia después de cerrar: si el agente lo vuelve a reportar antes de esto, se
# cuenta la re-aparición pero NO se reabre (cerrar tiene que servir de algo).
REABRIR_TRAS_DIAS = 3


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
    """El ítem del mismo área que ya dice lo mismo, abierto O resuelto.

    Antes sólo miraba los abiertos, y como el id es `sha1(area:titulo)` un
    pendiente resuelto que el agente volvía a reportar entraba como ítem NUEVO
    con el MISMO id: dos filas con la misma clave y el historial partido al
    medio. Ahora se reabre el que ya estaba (ver `abrir`).
    """
    n = _norm(titulo)
    for it in items:
        if it.get("area") != area:
            continue
        otro = _norm(it.get("titulo", ""))
        if otro == n or SequenceMatcher(None, otro, n).ratio() >= _SIMILAR:
            return it
    return None


_ID_RE = re.compile(r"\b([0-9a-f]{8})\b")

# El agente que no tiene nada pendiente igual completa el marcador, y "ninguno en
# esta corrida" entraba como ítem (pasó el 2026-08-13 con seo_specialist). Un
# pendiente que no existe ensucia la lista y le saca autoridad a los que sí.
_NADA_QUE_ANOTAR = re.compile(
    r"^(ningun[oa]|nada|n/?a|no aplica|no hay|sin (pendientes?|novedades))\b",
    re.IGNORECASE)


def _titular(texto: str, tope: int = 300) -> str:
    """El título, cortado donde se entiende: en la última oración o palabra entera.

    El agente escribe un párrafo donde va un título, y `texto[:300]` lo dejaba
    cortado a mitad de palabra ("...publicar la página con outline d"). El 08-17
    eran 5 de 24 ítems. Lo que no se entiende no le hace presión a nadie.
    """
    t = " ".join((texto or "").split())
    if len(t) <= tope:
        return t
    corte = t.rfind(". ", 0, tope + 1)
    if corte < tope // 2:                       # sin oración cerrada cerca: palabra entera
        corte = t.rfind(" ", 0, tope + 1)
    return (t[:corte].rstrip(" .,;:") if corte > 0 else t[:tope]) + "…"


def _citado(items: List[Dict[str, Any]], titulo: str) -> Optional[Dict[str, Any]]:
    """El pendiente abierto cuyo id aparece mencionado en el texto, si lo hay."""
    ids = set(_ID_RE.findall((titulo or "").lower()))
    if not ids:
        return None
    for it in items:
        if it.get("estado") == "abierto" and it.get("id") in ids:
            return it
    return None


def abrir(area: str, titulo: str, origen: str = "", dias_atras: int = 0) -> Optional[Dict[str, Any]]:
    """Abre un pendiente (o suma una re-aparición al que ya estaba). Best-effort.

    `dias_atras` es para cargar a mano lo que ya venía arrastrándose: un hallazgo
    que lleva tres semanas dando vueltas por los reportes no puede entrar al store
    con edad cero, porque la edad es justamente lo que tiene que hacer presión.
    """
    area = (area or "").strip().lower()
    titulo = _titular(titulo)
    if area not in AREAS or len(titulo) < 10 or _NADA_QUE_ANOTAR.match(titulo):
        return None
    data = _load()
    # Si el texto CITA el id de un pendiente que ya existe, es una referencia, no
    # uno nuevo. Pasó el 2026-08-12: seo_specialist escribió tres PENDIENTE que
    # decían "(PENDIENTE 22dfcb1e, ... sin duplicar — solo referencia)" y entraron
    # igual como ítems nuevos. El dedup difuso no los agarra: reformulados dan 0.48
    # de similitud, y bajar el umbral a eso fusionaría cosas distintas.
    citado = _citado(data["items"], titulo)
    if citado:
        citado["veces"] = int(citado.get("veces", 1)) + 1
        citado["visto_ultima"] = _now()
        if origen and origen not in (citado.get("origenes") or []):
            citado.setdefault("origenes", []).append(origen)
        _save(data)
        log.info("backlog_referencia", id=citado["id"], origen=origen)
        return citado
    ya = _match(data["items"], area, titulo)
    if ya:
        # No pisamos el título original: la primera redacción es la que el humano
        # ya leyó en briefs anteriores, y cambiarla cada día hace irreconocible al
        # mismo ítem. Sólo sube el contador y la última vez que se lo vio.
        ya["veces"] = int(ya.get("veces", 1)) + 1
        ya["visto_ultima"] = _now()
        if origen and origen not in (ya.get("origenes") or []):
            ya.setdefault("origenes", []).append(origen)
        if ya.get("estado") == "resuelto":
            # El dueño lo dio por cerrado y el agente lo vuelve a ver: se REABRE,
            # pero recién pasado el período de gracia. Sin eso, cerrar a la mañana
            # y que el brief de la noche lo resucite hace que cerrar no sirva.
            if _dias(ya.get("resuelto_at") or "") >= REABRIR_TRAS_DIAS:
                ya.update({"estado": "abierto", "abierto": _now(),
                           "reabierto_at": _now(),
                           "evidencia_previa": ya.get("evidencia", ""),
                           "evidencia": "", "resuelto_at": ""})
                log.info("backlog_reabierto", id=ya["id"], area=area, origen=origen)
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


def anotar(item_id: str, nota: str, por: str = "dueño") -> Optional[Dict[str, Any]]:
    """Contexto del dueño sobre un pendiente, SIN cerrarlo.

    Faltaba el canal de vuelta: el sistema sabía pedir y no sabía escuchar. Con
    CLAMEVET el dueño ya estaba en contacto y los agentes se lo seguían pidiendo,
    porque no había dónde decir "de esto me ocupo yo". La nota se les inyecta con
    el ítem y manda sobre lo que el agente hubiera supuesto.
    """
    nota = " ".join((nota or "").split())[:600]
    if len(nota) < 3:
        return None
    data = _load()
    for it in data["items"]:
        if it.get("id") == item_id and it.get("estado") == "abierto":
            it.setdefault("notas", []).append({"texto": nota, "por": por, "cuando": _now()})
            it["notas"] = it["notas"][-5:]      # sólo lo último dicho
            _save(data)
            log.info("backlog_anotado", id=item_id, por=por)
            return {**it, "dias": _dias(it.get("abierto", ""))}
    return None


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


def resueltos_recientes(area: str = "", dias: int = 14) -> List[Dict[str, Any]]:
    """Lo cerrado hace poco, con su evidencia. Del más nuevo al más viejo."""
    out = []
    for it in _load()["items"]:
        if it.get("estado") != "resuelto":
            continue
        if area and it.get("area") != area:
            continue
        d = _dias(it.get("resuelto_at") or "")
        if d <= dias:
            out.append({**it, "dias": d})
    out.sort(key=lambda i: i["dias"])
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
        return _ya_contestado(area).lstrip()
    cab = titulo or ("## PENDIENTES ABIERTOS" if not area
                     else f"## PENDIENTES ABIERTOS ({area})")
    filas = []
    for i in ab:
        filas.append(
            f"- `{i['id']}` [{i['area']}] **{i['titulo']}** — abierto hace "
            f"{i['dias']} día(s), reportado {i.get('veces', 1)} vez/veces"
            + (f" (por {', '.join(i.get('origenes') or [])})" if i.get("origenes") else ""))
        # La nota del dueño va debajo del ítem y manda: es lo último que se sabe.
        for n in (i.get("notas") or []):
            filas.append(f"    ↳ 💬 **{n.get('por', 'dueño')} dijo:** {n['texto']} "
                         "(esto MANDA sobre lo que supongas: no lo vuelvas a pedir)")
    return cab + "\n" + "\n".join(filas) + _ya_contestado(area)


def _ya_contestado(area: str = "", dias: int = 14, limite: int = 10) -> str:
    """Lo cerrado hace poco, para que el agente no lo vuelva a preguntar.

    Antes la respuesta del dueño le llegaba al agente porque el ítem seguía
    ABIERTO con su nota debajo. Desde que contestar CIERRA, sin esto la respuesta
    desaparecía del prompt y el agente volvía a pedir lo mismo a los tres días,
    que es justo lo que había que evitar.
    """
    hechos = resueltos_recientes(area, dias)[:limite]
    if not hechos:
        return ""
    filas = [f"- **{h['titulo']}** → {h.get('evidencia') or 'cerrado'} "
             f"(hace {h['dias']} día(s))" for h in hechos]
    return ("\n\n## YA CONTESTADO — NO LO VUELVAS A PEDIR\n"
            + "\n".join(filas)
            + "\nSi tenés evidencia NUEVA de que sigue pasando, decilo con el dato; "
              "si no, dalo por cerrado.")
