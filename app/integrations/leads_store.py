"""
Leads store — el "CRM" mínimo de Automiq: un JSON en el volume (data/leads-store.json)
que es la ÚNICA fuente de verdad del pipeline de cada lead.

Cierra el loop output-de-agentes → reuniones:
  - leadhunter produce el reporte diario  → `ingest_report` lo vuelca al store (estado=nuevo)
  - outbound corre la SECUENCIA de toques  → `due_for_touch` + `record_touch` (día 0,+2,+5,+9)
  - inbox_assistant detecta una respuesta   → `mark_replied` corta la secuencia (estado=respondió)

Estados del lead:
  nuevo        → recién ingestado, sin contactar
  contactado   → al menos 1 toque enviado, esperando respuesta (tiene next_touch_at)
  respondió    → contestó → secuencia FRENADA (lead caliente para cerrar)
  reunión      → se agendó reunión (transición manual)
  propuesta    → se envió propuesta (manual)
  cerrado      → ganado (manual)
  perdido      → descartado (manual)
  sin_respuesta→ se agotaron los 4 toques sin respuesta (nurture)

⚠️ Operacional: este archivo vive SOLO en el volume (no se commitea al repo: puede
tener datos de contacto). Está en .gitignore.
"""
from __future__ import annotations

import json
import re
import threading
import unicodedata
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..log import get_logger

log = get_logger("leads_store")

# Serializa las mutaciones cortas (update/delete desde el panel). Los flujos largos
# (outbound/inbox sostienen el store durante toda la corrida) no se pueden envolver
# acá; su ventana de carrera se asume (tráfico bajo, 1 worker).
_LOCK = threading.Lock()

_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
_STORE_FILE = _DATA_DIR / "leads-store.json"

# Cadencia de la secuencia: toque 0 (día 0), luego esperar estos días entre toques.
# [2, 2, 3] → toques en día 0, 2, 4, 7. 4 toques en total (step 0..3). Cadencia
# comprimida (2026-06-23) para que la mayoría de los toques caigan DENTRO de la
# semana → más respuestas rápido (el 80% de las respuestas vienen de los follow-ups).
FOLLOWUP_OFFSETS_DAYS = [2, 2, 3]
MAX_STEP = len(FOLLOWUP_OFFSETS_DAYS)  # 3 → steps 0,1,2,3

# Etiqueta humana por step (para los mensajes y el reporte).
STEP_LABEL = {
    0: "Primer toque",
    1: "Follow-up 1",
    2: "Follow-up 2",
    3: "Follow-up 3 (último)",
}

ACTIVE_STATES = ("nuevo", "contactado")  # estados que siguen en secuencia

# Reenganche de dormidos: un lead que RESPONDIÓ y después se quedó callado queda
# congelado (la secuencia no lo toca, a propósito). Tras este silencio le mandamos
# UN solo reenganche automático y después queda quieto (marca `reengaged_at`).
REENGAGE_AFTER_DAYS = 5

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
# Teléfono argentino: +54 ... (tolerante a espacios/guiones/paréntesis).
_PHONE_RE = re.compile(r"\+54[\s\-()]?[\d\s\-()]{8,}")
# Header de lead en el MD de leadhunter: "### Lead 3: Empresa", "## 🟢 Lead #3 — Empresa", etc.
_LEAD_HEADER_RE = re.compile(
    r"^#{2,4}\s+(?:🟢\s+)?Lead\s*#?\s*(\d+)\s*[:\-—–]?\s*(.*?)\s*$",
    re.IGNORECASE,
)


# ───────────────────────── normalización / keys ─────────────────────────

def normalize_email(s: str) -> str:
    if not s:
        return ""
    m = _EMAIL_RE.search(s)
    return m.group(0).strip().lower() if m else ""


def normalize_phone(s: str) -> str:
    """Devuelve el teléfono en formato compacto +54XXXXXXXXXX (solo dígitos tras +54)."""
    if not s:
        return ""
    m = _PHONE_RE.search(s)
    if not m:
        return ""
    digits = re.sub(r"[^\d]", "", m.group(0))
    if not digits.startswith("54"):
        return ""
    return "+" + digits


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (s or "").strip().lower()).strip("-")[:48]


def lead_key(email: str = "", phone: str = "", company: str = "") -> str:
    """Identidad estable del lead. Prioridad: email > teléfono > slug de empresa."""
    e = normalize_email(email)
    if e:
        return e
    p = normalize_phone(phone)
    if p:
        return "tel:" + p
    c = _slug(company)
    return ("co:" + c) if c else ""


# ───────────────────────── persistencia ─────────────────────────

def _empty_store() -> Dict[str, Any]:
    return {"version": 1, "updated_at": None, "leads": {}}


def load_store() -> Dict[str, Any]:
    try:
        data = json.loads(_STORE_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("leads"), dict):
            return data
    except FileNotFoundError:
        pass
    except Exception as e:
        log.warning("leads_store_load_failed", error=str(e))
    return _empty_store()


def save_store(store: Dict[str, Any]) -> None:
    try:
        _DATA_DIR.mkdir(exist_ok=True)
        store["updated_at"] = datetime.now(timezone.utc).isoformat()
        # Escritura atómica: tmp + replace (evita store corrupto si el proceso muere).
        tmp = _STORE_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(store, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(_STORE_FILE)
    except Exception as e:
        log.error("leads_store_save_failed", error=str(e))


# ───────────────────────── fechas ─────────────────────────

def _today_str(tz_today: Optional[str] = None) -> str:
    return tz_today or date.today().isoformat()


def _add_days(iso_day: str, days: int) -> str:
    d = date.fromisoformat(iso_day)
    return (d + timedelta(days=days)).isoformat()


def _is_due(next_touch_at: Optional[str], today: str) -> bool:
    if not next_touch_at:
        return False
    try:
        return date.fromisoformat(next_touch_at) <= date.fromisoformat(today)
    except ValueError:
        return False


# ───────────────────────── mutaciones ─────────────────────────

def upsert_lead(
    store: Dict[str, Any],
    *,
    company: str = "",
    email: str = "",
    phone: str = "",
    decisor: str = "",
    industria: str = "",
    web: str = "",
    today: Optional[str] = None,
    seed_touched_on: Optional[str] = None,
) -> Optional[str]:
    """Agrega un lead nuevo o refresca campos estáticos de uno existente SIN pisar
    su estado/secuencia. Devuelve la key, o None si no hay identidad usable.

    `seed_touched_on`: si se pasa (fecha ISO) y el lead es NUEVO, lo siembra como ya
    contactado en step 0 esa fecha (para no re-mailear leads históricos del sent-log).
    """
    today = _today_str(today)
    e = normalize_email(email)
    p = normalize_phone(phone)
    key = lead_key(e, p, company)
    if not key:
        return None

    leads = store.setdefault("leads", {})
    existing = leads.get(key)
    if existing is not None:
        # Refrescar sólo lo estático / completar lo que falte. No tocar state/touches.
        if company and not existing.get("company"):
            existing["company"] = company
        if e and not existing.get("email"):
            existing["email"] = e
        if p and not existing.get("phone"):
            existing["phone"] = p
        for fld, val in (("decisor", decisor), ("industria", industria), ("web", web)):
            if val and not existing.get(fld):
                existing[fld] = val
        return key

    channel = "email" if e else ("whatsapp" if p else "desconocido")
    lead = {
        "key": key,
        "company": company,
        "email": e,
        "phone": p,
        "decisor": decisor,
        "industria": industria,
        "web": web,
        "channel": channel,
        "state": "nuevo",
        "next_step": 0,
        # Sólo agendamos toque automático si hay email (el canal auto es email).
        "next_touch_at": today if e else None,
        "touches": [],
        "first_seen": today,
        "last_reply_at": None,
        "notes": [],
    }
    if seed_touched_on and e:
        # Sembrar como ya contactado (step 0) en esa fecha → próximo follow-up agendado.
        lead["touches"].append({
            "step": 0, "date": seed_touched_on, "channel": "email",
            "msg_id": "", "subject": "(histórico sent-log)",
        })
        lead["state"] = "contactado"
        lead["next_step"] = 1
        lead["next_touch_at"] = _add_days(seed_touched_on, FOLLOWUP_OFFSETS_DAYS[0])
    leads[key] = lead
    return key


def record_touch(
    store: Dict[str, Any],
    key: str,
    *,
    step: int,
    channel: str = "email",
    msg_id: str = "",
    subject: str = "",
    thread_id: str = "",
    today: Optional[str] = None,
) -> None:
    """Registra un toque enviado y AVANZA la secuencia (agenda el siguiente, o la cierra).
    `thread_id`: hilo de Gmail del toque — los follow-ups se mandan DENTRO de ese hilo."""
    today = _today_str(today)
    lead = store.get("leads", {}).get(key)
    if not lead:
        return
    lead.setdefault("touches", []).append({
        "step": step, "date": today, "channel": channel,
        "msg_id": msg_id, "subject": subject, "thread_id": thread_id,
    })
    nxt = step + 1
    lead["next_step"] = nxt
    lead["state"] = "contactado"
    if step < len(FOLLOWUP_OFFSETS_DAYS):
        lead["next_touch_at"] = _add_days(today, FOLLOWUP_OFFSETS_DAYS[step])
    else:
        # Se agotó la secuencia sin respuesta.
        lead["next_touch_at"] = None
        lead["state"] = "sin_respuesta"


def record_reengage(
    store: Dict[str, Any],
    key: str,
    *,
    msg_id: str = "",
    subject: str = "",
    thread_id: str = "",
    today: Optional[str] = None,
) -> None:
    """Registra el toque de reenganche a un lead dormido y lo marca (`reengaged_at`)
    para que NO se lo vuelva a tocar. NO cambia el estado: sigue "respondió" (caliente
    para el humano), sólo dejamos de reengancharlo automáticamente."""
    today = _today_str(today)
    lead = store.get("leads", {}).get(key)
    if not lead:
        return
    lead.setdefault("touches", []).append({
        "step": "reengage", "date": today, "channel": "email",
        "msg_id": msg_id, "subject": subject, "thread_id": thread_id,
    })
    lead["reengaged_at"] = today


def mark_replied(
    store: Dict[str, Any], email: str = "", phone: str = "", when: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """Marca al lead (por email o teléfono) como que RESPONDIÓ → frena la secuencia.
    Devuelve el lead (caliente) o None si el remitente no era un lead nuestro."""
    when = when or datetime.now(timezone.utc).isoformat()
    e = normalize_email(email)
    p = normalize_phone(phone)
    leads = store.get("leads", {})
    lead = None
    if e and e in leads:
        lead = leads[e]
    elif e:
        for l in leads.values():
            if normalize_email(l.get("email", "")) == e:
                lead = l
                break
    if lead is None and p:
        key = "tel:" + p
        lead = leads.get(key) or next(
            (l for l in leads.values() if normalize_phone(l.get("phone", "")) == p), None
        )
    if lead is None:
        return None
    # Si ya estaba en una etapa avanzada (reunión/propuesta/cerrado), no degradar.
    if lead.get("state") in ("reunión", "propuesta", "cerrado"):
        lead["last_reply_at"] = when
        return lead
    lead["state"] = "respondió"
    lead["next_touch_at"] = None
    lead["last_reply_at"] = when
    _learn_from_reply(lead)
    return lead


def _learn_from_reply(lead: Dict[str, Any]) -> None:
    """Aprendizaje automático (Fase 2): un lead que responde es la señal de que el
    ángulo/secuencia para ese rubro funciona → se registra como lección de outcome
    para outbound y creative_strategist. Best-effort, con dedup."""
    try:
        from . import memory_store as ms
        industria = (lead.get("industria") or "su rubro").strip() or "su rubro"
        n = len(lead.get("touches", []))
        channel = lead.get("channel") or "email"
        lesson = (f"Conversión real: una empresa de {industria} respondió tras {n} "
                  f"toque(s) por {channel}. El ángulo/secuencia para {industria} funciona — "
                  f"priorizá ese rubro y replicá el enfoque.")
        ms.record_outcome("outbound", lesson, weight=2)
        ms.record_outcome("creative_strategist", lesson, weight=2)
        # El leadhunter también aprende: un perfil que RESPONDE es buena materia prima →
        # buscar más empresas como esa (respuesta llega mucho antes que la venta).
        lh = (f"Señal de demanda: una PyME de {industria} respondió al outreach. "
              f"Buscá MÁS empresas de {industria} (mismo perfil/tamaño) — convierten mejor.")
        ms.record_outcome("leadhunter", lh, weight=2)
    except Exception:
        pass


def set_state(store: Dict[str, Any], key: str, state: str) -> bool:
    lead = store.get("leads", {}).get(key)
    if not lead:
        return False
    lead["state"] = state
    if state in ("reunión", "propuesta", "cerrado", "perdido"):
        lead["next_touch_at"] = None
    return True


# ───────────────────────── mantenimiento / purga ─────────────────────────

def match_keys(
    store: Dict[str, Any],
    *,
    keys: Optional[List[str]] = None,
    states: Optional[List[str]] = None,
    channels: Optional[List[str]] = None,
    email_contains: Optional[List[str]] = None,
    untouched_only: bool = False,
) -> List[str]:
    """Devuelve las keys de leads que matchean TODOS los filtros provistos (AND).

    Filtros omitidos (None) no restringen. `keys` explícitas se incluyen siempre
    (si existen). Pensado para previsualizar una purga antes de ejecutarla.
    """
    leads = store.get("leads", {})
    explicit = {k for k in (keys or []) if k in leads}
    matched: List[str] = []
    for k, l in leads.items():
        if states is not None and l.get("state") not in states:
            continue
        if channels is not None and l.get("channel") not in channels:
            continue
        if email_contains and not any(
            s.lower() in (l.get("email", "") or "").lower() for s in email_contains
        ):
            continue
        if untouched_only and l.get("touches"):
            continue
        matched.append(k)
    # unir con las explícitas, preservando orden y sin duplicar
    for k in explicit:
        if k not in matched:
            matched.append(k)
    return matched


def remove_keys(store: Dict[str, Any], keys: List[str]) -> int:
    """Borra los leads de esas keys. Devuelve cuántos borró."""
    leads = store.get("leads", {})
    removed = 0
    for k in keys:
        if leads.pop(k, None) is not None:
            removed += 1
    return removed


def reset_store() -> Dict[str, Any]:
    """Vacía el store por completo (escribe un store nuevo). Devuelve el store vacío."""
    fresh = _empty_store()
    save_store(fresh)
    return fresh


def delete_lead(key: str) -> bool:
    with _LOCK:
        store = load_store()
        leads = store.get("leads", {})
        if key in leads:
            del leads[key]
            save_store(store)
            return True
    return False


def update_lead(key: str, fields: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    with _LOCK:
        store = load_store()
        lead = store.get("leads", {}).get(key)
        if not lead:
            return None
        for k in ("company", "email", "phone", "channel", "state", "next_step",
                  "reengaged_at",
                  # outbound asistido por LinkedIn (perfil del decisor + nota/DM + estado)
                  "linkedin", "li_headline", "li_note", "li_dm", "li_state", "li_at"):
            if k in fields and fields[k] is not None:
                lead[k] = fields[k]
        save_store(store)
        return lead_view(lead)


def lead_view(lead: Dict[str, Any]) -> Dict[str, Any]:
    """Vista compacta de un lead para listar (sin volcar todo el historial)."""
    return {
        "key": lead.get("key"),
        "company": lead.get("company"),
        "email": lead.get("email"),
        "phone": lead.get("phone"),
        "channel": lead.get("channel"),
        "state": lead.get("state"),
        "next_step": lead.get("next_step"),
        "next_touch_at": lead.get("next_touch_at"),
        "touches": len(lead.get("touches", [])),
        "first_seen": lead.get("first_seen"),
        "last_reply_at": lead.get("last_reply_at"),
        "reengaged_at": lead.get("reengaged_at"),
        "decisor": lead.get("decisor"),
        "linkedin": lead.get("linkedin"),
        "li_state": lead.get("li_state"),
    }


# ───────────────────────── consultas ─────────────────────────

def due_for_touch(
    store: Dict[str, Any], today: Optional[str] = None, *, with_email: bool = True
) -> List[Dict[str, Any]]:
    """Leads que toca contactar HOY (secuencia automática por email)."""
    today = _today_str(today)
    out: List[Dict[str, Any]] = []
    for lead in store.get("leads", {}).values():
        if lead.get("state") not in ACTIVE_STATES:
            continue
        if lead.get("next_step", 0) > MAX_STEP:
            continue
        if with_email and not lead.get("email"):
            continue
        if _is_due(lead.get("next_touch_at"), today):
            out.append(lead)
    # Primero los MÁS VENCIDOS: con el cap diario la cola se satura, y ordenar por step
    # hacía que los steps altos nunca llegaran (los últimos follow-ups salían con 21 días
    # de atraso, rompiendo la cadencia 0/2/4/7). A igual vencimiento, primero el step más
    # alto: se terminan las secuencias abiertas antes de empezar otras nuevas.
    out.sort(key=lambda l: (l.get("next_touch_at") or "", -l.get("next_step", 0)))
    return out


def due_for_reengage(
    store: Dict[str, Any], today: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Leads que respondieron una vez y se quedaron callados ≥ REENGAGE_AFTER_DAYS,
    con email y sin reenganche previo → toca el ÚNICO reenganche automático."""
    today = _today_str(today)
    try:
        today_d = date.fromisoformat(today)
    except ValueError:
        return []
    out: List[Dict[str, Any]] = []
    for lead in store.get("leads", {}).values():
        if lead.get("state") != "respondió":
            continue
        if lead.get("reengaged_at"):
            continue
        if not lead.get("email"):
            continue
        lr = lead.get("last_reply_at")
        if not lr:
            continue
        try:
            reply_d = date.fromisoformat(str(lr)[:10])
        except ValueError:
            continue
        if (today_d - reply_d).days >= REENGAGE_AFTER_DAYS:
            out.append(lead)
    out.sort(key=lambda l: str(l.get("last_reply_at", "")))
    return out


def whatsapp_queue(store: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Leads nuevos SIN email (sólo WhatsApp/teléfono) → cola para contactar a mano."""
    return [
        l for l in store.get("leads", {}).values()
        if l.get("state") == "nuevo" and l.get("phone") and not l.get("email")
    ]


def summary_counts(store: Dict[str, Any]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for lead in store.get("leads", {}).values():
        counts[lead.get("state", "?")] = counts.get(lead.get("state", "?"), 0) + 1
    counts["total"] = len(store.get("leads", {}))
    return counts


_REPLIED_STATES = ("respondió", "reunión", "propuesta", "cerrado")


def known_companies(store: Dict[str, Any], limit: int = 150) -> List[str]:
    """Nombres de empresas que YA están en el pipeline (cualquier estado).
    Sirve para que el leadhunter NO vuelva a traer las mismas → leads netos nuevos."""
    seen, out = set(), []
    for l in store.get("leads", {}).values():
        c = (l.get("company") or "").strip()
        k = c.lower()
        if c and k not in seen:
            seen.add(k)
            out.append(c)
    return sorted(out)[:limit]


# ── Clasificación a los 4 verticales macro de la estrategia (Vision-2026) ──
# La `industria` que trae el leadhunter es hiper-específica ("Distribución bebidas
# Tandil") → 100+ rubros distintos, ninguno acumula señal. Estos 4 buckets macro
# sí acumulan → el digest puede decir qué VERTICAL convierte. Orden = prioridad de
# match (logística antes que distribución; distribución antes que manufactura para
# que "distribuidora de alimentos" caiga en distribución, no en manufactura).
VERTICAL_KEYWORDS = [
    ("logística", ["logist", "transport", "flota", "ultima milla", "courier",
                   "encomienda", "mudanza", "almacenaje", "cadena de frio", "deposito fiscal"]),
    ("distribución", ["distribu", "mayorista", "repuesto", "insumo", "ferreteria",
                      "corralon", "bebida", "autoservicio", "comercializ", "importador",
                      "proveedor", "abastec"]),
    ("inmobiliarias", ["inmobil", "brokerage", "propiedad", "real estate",
                       "bienes raices", "desarrollo urban", "loteo", "alquiler"]),
    ("manufacturing", ["manufactura", "fabrica", "industria", "metalurg", "metal",
                       "plastic", "textil", "autopart", "produccion", "aliment",
                       "quimic", "maquinaria", "envases", "carpinteria", "curtiembre",
                       "fundicion", "agroveterinaria"]),
]


def _strip_accents(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", (s or "").lower())
        if unicodedata.category(c) != "Mn"
    )


def classify_vertical(industria: str = "", company: str = "") -> str:
    """Mapea la industria fina (+ nombre de empresa) a uno de los 4 verticales macro,
    o 'otros' si no matchea ninguno."""
    t = _strip_accents(industria) + " " + _strip_accents(company)
    for vert, kws in VERTICAL_KEYWORDS:
        if any(k in t for k in kws):
            return vert
    return "otros"


def outcomes_by_vertical(store: Dict[str, Any]) -> Dict[str, Dict[str, int]]:
    """Igual que outcomes_by_industry pero agrupado por los 4 verticales macro.
    Da señal agregada que el rubro hiper-específico no puede dar."""
    agg: Dict[str, Dict[str, int]] = {}
    for l in store.get("leads", {}).values():
        vert = classify_vertical(l.get("industria", ""), l.get("company", ""))
        a = agg.setdefault(vert, {"contacted": 0, "replied": 0, "won": 0, "dead": 0, "total": 0})
        a["total"] += 1
        st = l.get("state", "")
        if st != "nuevo" or l.get("touches"):
            a["contacted"] += 1
        if st in _REPLIED_STATES:
            a["replied"] += 1
        if st == "cerrado":
            a["won"] += 1
        if st == "sin_respuesta":
            a["dead"] += 1
    return agg


def outcomes_by_industry(store: Dict[str, Any]) -> Dict[str, Dict[str, int]]:
    """Agregado por rubro: cuántos se contactaron, respondieron, ganaron, murieron.
    Base del digest de aprendizaje (qué rubros convierten vs cuáles son tierra muerta)."""
    agg: Dict[str, Dict[str, int]] = {}
    for l in store.get("leads", {}).values():
        ind = (l.get("industria") or "").strip().lower() or "(sin rubro)"
        a = agg.setdefault(ind, {"contacted": 0, "replied": 0, "won": 0, "dead": 0, "total": 0})
        a["total"] += 1
        st = l.get("state", "")
        if st != "nuevo" or (l.get("touches")):
            a["contacted"] += 1
        if st in _REPLIED_STATES:
            a["replied"] += 1
        if st == "cerrado":
            a["won"] += 1
        if st == "sin_respuesta":
            a["dead"] += 1
    return agg


# ───────────────────────── ingest del reporte de leadhunter ─────────────────────────

def _split_lead_blocks(report_md: str) -> List[Tuple[str, str]]:
    """Devuelve [(titulo_empresa, texto_del_bloque)] por cada lead del MD."""
    if not report_md:
        return []
    lines = report_md.splitlines()
    blocks: List[Tuple[str, List[str]]] = []
    current: Optional[Tuple[str, List[str]]] = None
    for line in lines:
        m = _LEAD_HEADER_RE.match(line)
        if m:
            if current:
                blocks.append(current)
            title = (m.group(2) or "").strip(" —-–:*").strip()
            current = (title, [])
        elif current is not None:
            current[1].append(line)
    if current:
        blocks.append(current)
    return [(t, "\n".join(ls)) for t, ls in blocks]


def _parse_contact_rows(report_md: str) -> List[Tuple[str, str, str, str]]:
    """Lee filas de tabla markdown y devuelve [(empresa, telefono, email, industria)].

    Robusto para reportes de leadhunter que ponen el contacto SOLO en la tabla
    resumen de arriba (y dejan los bloques de detalle vacíos/truncados).
    """
    out: List[Tuple[str, str, str, str]] = []
    for line in (report_md or "").splitlines():
        ln = line.strip()
        if not ln.startswith("|") or set(ln) <= set("|-: "):  # separador o no-fila
            continue
        phone = normalize_phone(ln)
        email = normalize_email(ln)
        if not (phone or email):
            continue  # sólo filas con contacto real (descarta header)
        cells = [c.strip() for c in ln.strip("|").split("|")]
        company = ""
        industria = ""
        for c in cells:
            cc = re.sub(r"\*", "", c).strip()
            # saltear celdas de contacto (teléfono/email) y placeholders numéricos
            if not cc or normalize_phone(cc) or normalize_email(cc):
                continue
            if re.fullmatch(r"#?\s*\d+", cc) or re.fullmatch(r"\d+\s*/\s*\d+", cc):
                continue  # número de fila o fit "5/6"
            if not re.search(r"[A-Za-zÁÉÍÓÚáéíóúÑñ]", cc):
                continue
            if not company:
                company = cc
            elif not industria:
                industria = cc
                break
        if company:
            out.append((company, phone, email, industria))
    return out


def _extract_field(block: str, *labels: str) -> str:
    """Primera línea del bloque que arranca con alguna de las labels → su valor."""
    for line in block.splitlines():
        low = line.lower()
        for lab in labels:
            if lab in low:
                # tomar lo que viene después de los dos puntos o el guion
                val = re.split(r"[:|]", line, maxsplit=1)
                if len(val) > 1:
                    return re.sub(r"[*`>\-]", "", val[1]).strip()
    return ""


def ingest_report(
    store: Dict[str, Any],
    report_md: str,
    *,
    today: Optional[str] = None,
    sent_log_emails: Optional[Dict[str, Any]] = None,
) -> Dict[str, int]:
    """Vuelca el reporte de leadhunter al store. Idempotente (dedup por key).

    Devuelve {nuevos, existentes, sin_identidad}.
    """
    today = _today_str(today)
    sent_log_emails = sent_log_emails or {}

    # Mergeamos por slug de empresa para no duplicar (tabla resumen + bloque detalle
    # de la misma empresa = UN registro). Cada lead tiene siempre una empresa.
    merged: Dict[str, Dict[str, str]] = {}

    def _slot(company: str) -> Optional[Dict[str, str]]:
        s = _slug(company)
        if not s:
            return None
        return merged.setdefault(
            s, {"company": company, "email": "", "phone": "",
                "decisor": "", "industria": "", "web": ""}
        )

    # 1) Filas de la tabla resumen (empresa + teléfono + email + industria).
    for company, phone, email, industria in _parse_contact_rows(report_md):
        d = _slot(company)
        if d is None:
            continue
        if phone and not d["phone"]:
            d["phone"] = phone
        if email and not d["email"]:
            d["email"] = email
        if industria and not d["industria"]:
            d["industria"] = industria

    # 2) Bloques de detalle por lead (email, decisor, web, y refuerzo de teléfono).
    for title, block in _split_lead_blocks(report_md):
        company = title or _extract_field(block, "empresa")
        d = _slot(company)
        if d is None:
            continue
        full = f"{title}\n{block}"
        for fld, val in (
            ("email", normalize_email(full)),
            ("phone", normalize_phone(full)),
            ("decisor", _extract_field(block, "decisor")),
            ("web", _extract_field(block, "web")),
            ("industria", _extract_field(block, "industria")),
        ):
            if val and not d[fld]:
                d[fld] = val

    new = existing_n = skipped = 0
    for d in merged.values():
        email, phone, company = d["email"], d["phone"], d["company"]
        if not (email or phone or company):
            skipped += 1
            continue
        key = lead_key(email, phone, company)
        existed = key in store.get("leads", {})
        seed = None
        if email and email in sent_log_emails and not existed:
            sl = sent_log_emails.get(email) or {}
            seed = (sl.get("date") if isinstance(sl, dict) else None) or today
        upsert_lead(
            store, company=company, email=email, phone=phone, decisor=d["decisor"],
            industria=d["industria"], web=d["web"], today=today, seed_touched_on=seed,
        )
        if existed:
            existing_n += 1
        else:
            new += 1
    return {"nuevos": new, "existentes": existing_n, "sin_identidad": skipped}
