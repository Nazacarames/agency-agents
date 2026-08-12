"""
video_bank — el stock de video adelantado, y su goteo hacia la cola de publicación.

Por qué existe: el bundle ilimitado de Higgsfield dura 10 días y sirve para generar
un año de contenido de una sentada. Pero `publish_queue` NO es un depósito — tiene
tope 14 pendientes de feed y vence a los 14 días (`expire_stale`), justamente para
que la cola no se fosilice. Meterle 156 videos ahí sería perderlos casi todos.

Entonces el stock vive acá: cada pieza queda con su prompt, su copy y su turno, y un
job la pasa a la cola recién cuando le toca. El video en sí NO se guarda en el
volumen (son ~800 MB): vive en Drive y se baja cuando llega su fecha.

El ilimitado de Higgsfield es sólo para uso humano en su web — no se puede
automatizar ni por API ni por MCP sin consumir créditos y sin violar sus términos.
Por eso el flujo es: el sistema arma los prompts → el humano los genera y sube los
MP4 → el sistema los aparea, los monta y los publica durante el año.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..log import get_logger
from .jsonstore import write_json_atomic

log = get_logger("video_bank")

_FILE = Path(__file__).resolve().parent.parent.parent / "data" / "video-bank.json"

# Estados: `prompt` (guion listo, falta generarlo) → `listo` (MP4 subido y apareado)
# → `encolado` (pasó a publish_queue) → `publicado`.
PENDIENTE, LISTO, ENCOLADO, PUBLICADO = "prompt", "listo", "encolado", "publicado"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load() -> Dict[str, Any]:
    try:
        d = json.loads(_FILE.read_text(encoding="utf-8"))
        d.setdefault("items", [])
        return d
    except Exception:
        return {"items": []}


def _save(d: Dict[str, Any]) -> None:
    write_json_atomic(_FILE, d, indent=1)


def agregar(prompt: str, copy: str = "", gancho: str = "", kind: str = "reel",
            origen: str = "") -> Optional[Dict[str, Any]]:
    """Suma una pieza al banco y le asigna el próximo número de lote.

    El número es la única forma de aparear después: el humano genera en Higgsfield
    en orden y guarda los archivos como 001.mp4, 002.mp4… Sin número correlativo
    habría que adivinar qué clip corresponde a qué guion.
    """
    prompt = (prompt or "").strip()
    if len(prompt) < 30:
        return None
    d = _load()
    n = max([int(i.get("n", 0)) for i in d["items"]], default=0) + 1
    item = {
        "n": n, "archivo": f"{n:03d}.mp4",
        "prompt": prompt[:2000], "copy": (copy or "").strip()[:800],
        "gancho": (gancho or "").strip()[:200], "kind": kind,
        "estado": PENDIENTE, "origen": origen,
        "creado": _now(), "media": "", "publicar_el": "",
    }
    d["items"].append(item)
    _save(d)
    return item


def marcar_listo(n: int, media: str) -> Optional[Dict[str, Any]]:
    """El MP4 número `n` ya está subido: queda disponible para encolarse."""
    d = _load()
    for it in d["items"]:
        if int(it.get("n", 0)) == int(n) and it.get("estado") == PENDIENTE:
            it.update({"estado": LISTO, "media": media, "subido": _now()})
            _save(d)
            log.info("video_bank_listo", n=n)
            return it
    return None


def _reparto(items: List[Dict[str, Any]], por_semana: int) -> None:
    """Le pone fecha a cada pieza lista, repartidas `por_semana` a lo largo del año."""
    hoy = date.today()
    paso = 7.0 / max(1, por_semana)
    for i, it in enumerate(items):
        it["publicar_el"] = (hoy + timedelta(days=round(i * paso))).isoformat()


def planificar(por_semana: int = 3) -> int:
    """Reparte las fechas de todo lo que está listo y sin fecha. Devuelve cuántas."""
    d = _load()
    sin_fecha = [i for i in d["items"]
                 if i.get("estado") == LISTO and not i.get("publicar_el")]
    if not sin_fecha:
        return 0
    sin_fecha.sort(key=lambda i: int(i.get("n", 0)))
    ya = [i for i in d["items"] if i.get("publicar_el")]
    # Arranca después de lo ya planificado, para no pisar fechas al subir un 2º lote.
    desfase = len(ya)
    _reparto(sin_fecha, por_semana)
    if desfase:
        paso = 7.0 / max(1, por_semana)
        for i, it in enumerate(sin_fecha):
            base = date.today() + timedelta(days=round((desfase + i) * paso))
            it["publicar_el"] = base.isoformat()
    _save(d)
    log.info("video_bank_planificado", piezas=len(sin_fecha), por_semana=por_semana)
    return len(sin_fecha)


def toca_hoy(hoy: Optional[str] = None) -> List[Dict[str, Any]]:
    """Las piezas listas cuya fecha ya llegó (o pasó) y que no se encolaron todavía."""
    hoy = hoy or date.today().isoformat()
    return sorted(
        [i for i in _load()["items"]
         if i.get("estado") == LISTO and i.get("publicar_el") and i["publicar_el"] <= hoy],
        key=lambda i: (i.get("publicar_el", ""), int(i.get("n", 0))))


def marcar_encolado(n: int) -> bool:
    d = _load()
    for it in d["items"]:
        if int(it.get("n", 0)) == int(n) and it.get("estado") == LISTO:
            it.update({"estado": ENCOLADO, "encolado_at": _now()})
            _save(d)
            return True
    return False


def resumen() -> Dict[str, Any]:
    items = _load()["items"]
    por = {}
    for it in items:
        por[it.get("estado", "?")] = por.get(it.get("estado", "?"), 0) + 1
    listos = [i for i in items if i.get("estado") == LISTO and i.get("publicar_el")]
    return {
        "total": len(items), "por_estado": por,
        "semanas_de_stock": round(len(listos) / 3.0, 1),
        "hasta": max([i["publicar_el"] for i in listos], default=""),
        "sin_generar": sum(1 for i in items if i.get("estado") == PENDIENTE),
    }


_NUM_RE = re.compile(r"(\d{1,4})")


def numero_de(nombre: str) -> Optional[int]:
    """El número de lote a partir del nombre del archivo (`012.mp4`, `12 (1).mp4`)."""
    m = _NUM_RE.search(Path(nombre or "").stem)
    return int(m.group(1)) if m else None


def drenar(max_por_corrida: int = 2) -> Dict[str, Any]:
    """Pasa a la cola de publicación lo que ya le tocaba. Best-effort.

    Va de a poco a propósito: `publish_queue` publica 1 pieza de feed por día y
    vence lo que lleva 14 días esperando, así que empujarle más de lo que drena
    sólo lograría que el stock se venza dentro de la cola en vez de afuera.
    """
    from . import publish_queue as pq
    metidas, saltadas = [], 0
    for it in toca_hoy()[:max_por_corrida]:
        if not it.get("media"):
            continue
        if pq.pending_count(lane="feed") >= pq.MAX_PENDING_FEED:
            saltadas += 1
            break                      # la cola está llena: mañana será
        enc = pq.enqueue(it["media"], caption=it.get("copy", ""),
                         source="video_bank", kind=it.get("kind") or "reel")
        if enc:
            marcar_encolado(int(it["n"]))
            metidas.append(int(it["n"]))
    if metidas or saltadas:
        log.info("video_bank_drenado", metidas=len(metidas), saltadas=saltadas)
    return {"encoladas": metidas, "cola_llena": bool(saltadas)}


# ── identidad: se pega en código, no se le pide al modelo ──
#
# El primer lote salió con 0 de 20 prompts conteniendo alguna de las anclas de
# NAZARENO_IDENTITY, y dos decían "dark brown hair" cuando es castaño CLARO. Pedirle
# a un LLM que reproduzca 500 caracteres exactos en cada una de 156 piezas es pedirle
# que no derive, y deriva: saldrían 156 personas distintas. El agente describe la
# ESCENA; la persona la pone esta función, igual siempre.

# Frases que contradicen el ancla y hay que sacar de la escena antes de pegarla.
_CONTRADICE = (
    r"(?:short |straight |wavy )?(?:dark[- ]brown|black|blond[e]?|red)\s+hair",
    r"a young argentine man[^,.]*",
    r"young man[^,.]*",
)


def _escena_limpia(texto: str) -> str:
    """Saca del texto la descripción de la persona: la pone el ancla, no el modelo."""
    out = texto or ""
    for pat in _CONTRADICE:
        out = re.sub(pat, "", out, flags=re.IGNORECASE)
    return re.sub(r"\s{2,}", " ", re.sub(r"\s+([,.])", r"\1", out)).strip(" ,.")


def prompt_final(item: Dict[str, Any]) -> str:
    """El prompt listo para pegar: identidad exacta + escena + encuadre."""
    try:
        from ..agents.tiktok_creator import NAZARENO_IDENTITY
    except Exception:
        NAZARENO_IDENTITY = ""
    escena = _escena_limpia(item.get("prompt", ""))
    partes = [p for p in (NAZARENO_IDENTITY.strip(), f"SCENE: {escena}") if p.strip(" SCENE:")]
    return " ".join(partes) + " Vertical 9:16 format, 5 seconds, natural spoken Argentine Spanish."
