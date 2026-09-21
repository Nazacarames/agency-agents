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
    """El teléfono como se DISCA: +54XXXXXXXXXX, con el 9 de celular si venía.

    El 9 se conserva a propósito. `outbound._wa_link` arma `wa.me/{digitos}` con
    esto, y para un celular argentino wa.me necesita el 9: sin él, el link no abre
    el chat y falla en silencio. Para comparar dos leads NO se usa esta función
    sino `identidad_telefono`.

    ACEPTA EL FORMATO LOCAL, que es como escribe la gente. Antes se exigía `+54`
    literal y todo lo demás se tiraba EN SILENCIO. Nadie pone el código de país en
    un formulario: escribe `1153872152`, `11 5387-2152` o `011 15-5387-2152`.
    Resultado medido el 2026-09-21: **los 3 leads inbound de la web —Sumiagro, CBA
    y Exequiel— quedaron sin teléfono**, siendo los más valiosos que tuvimos y
    siendo WhatsApp el canal por el que se los contacta.

    Se asume celular (se agrega el 9) cuando no viene: el formulario pide el
    WhatsApp, y el 9 es lo que necesita wa.me. Si fuera una línea fija el link no
    abre, pero el número igual queda guardado y visible, que es lo que importaba.
    """
    if not s:
        return ""

    # 1) Con `+54` explícito: se EXTRAE del texto. Hace falta porque a esta función
    #    también le llega una fila entera de markdown del informe de leadhunter,
    #    con otros números al lado (el #, el fit 5/6). Juntar todos los dígitos de
    #    esa línea daría un teléfono inventado.
    m = _PHONE_RE.search(s)
    if m:
        digits = re.sub(r"[^\d]", "", m.group(0))
        if digits.startswith("54"):
            return "+" + digits

    # 2) Formato local: SÓLO si el texto es un teléfono y nada más. El `fullmatch`
    #    es el que distingue el campo de un formulario de una línea que lo contiene.
    crudo = s.strip()
    if not crudo or not re.fullmatch(r"[\d\s\-().+]+", crudo):
        return ""
    digits = re.sub(r"[^\d]", "", crudo)
    if not digits:
        return ""

    # 0 de larga distancia: 011..., 0351...
    if digits.startswith("0"):
        digits = digits[1:]
    # El 15 del celular: 11 15 5387-2152. Se saca sólo si al sacarlo queda un
    # número de largo válido, para no mutilar uno que tenga un 15 de verdad.
    for i in (2, 3, 4):
        if digits[i:i + 2] == "15" and len(digits) - 2 == 10:
            digits = digits[:i] + digits[i + 2:]
            break

    if len(digits) == 10:                       # 11 5387-2152 → celular
        return "+549" + digits
    if len(digits) == 11 and digits.startswith("9"):
        return "+54" + digits
    return ""


def identidad_telefono(s: str) -> str:
    """El mismo teléfono, sin el 9 de celular: sirve para saber si dos leads son uno.

    En Argentina el mismo número se escribe de las dos formas —+54 9 11 4440-0131 y
    +54 11 4440-0131— y comparándolos tal cual entraban como leads distintos: medido
    el 2026-09-18, 25 grupos duplicados y 27 registros de más sobre 536. Eso es
    contactar dos veces a la misma empresa y contar mal el embudo.

    Sacar el 9 es seguro para comparar: ningún código de área argentino empieza con
    9, así que un 9 pegado al 54 sólo puede ser el prefijo de móvil. Pero se usa
    SÓLO para comparar — lo que se guarda y se disca es `normalize_phone`.
    """
    p = normalize_phone(s)
    if not p:
        return ""
    resto = p[3:]                                   # después de "+54"
    return "+54" + (resto[1:] if resto.startswith("9") else resto)


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

def _mismo_lead(leads: Dict[str, Any], email: str, phone: str,
                company: str) -> Optional[Dict[str, Any]]:
    """El lead que YA existe para esta empresa, aunque haya entrado por otra puerta.

    `lead_key` prioriza email > teléfono > empresa, así que una misma empresa que
    aparece primero con teléfono y después con mail generaba DOS registros: medido
    el 2026-09-18, 33 grupos y 37 registros de más sobre 536. Zarcam Logística
    estaba dos veces, una de ellas con una respuesta real adentro.

    Se busca por identidad fuerte (teléfono o mail) y, como último recurso, por
    nombre de empresa normalizado. El nombre va último a propósito: es el más
    frágil —«S.A.» contra «SA»— y sólo se usa si no hay nada mejor.
    """
    if phone:
        for l in leads.values():
            if identidad_telefono(l.get("phone", "")) == identidad_telefono(phone):
                return l
    if email:
        for l in leads.values():
            if normalize_email(l.get("email", "")) == email:
                return l
    c = _nombre_empresa(company)
    if c:
        for l in leads.values():
            if _nombre_empresa(l.get("company", "")) == c:
                return l
    return None


_SUFIJOS = re.compile(r"\b(s\.?a\.?s?|s\.?r\.?l\.?|srl|sa|sas|ltda|inc|cia)\b")


def _nombre_empresa(s: str) -> str:
    """El nombre sin sufijo societario ni puntuación: «Racer SRL» == «Racer S.R.L.»."""
    s = _SUFIJOS.sub("", (s or "").lower())
    return re.sub(r"[^a-z0-9]", "", s)


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
    existing = leads.get(key) or _mismo_lead(leads, e, p, company)
    if existing is not None:
        # Puede haberse encontrado por otra identidad (entró por teléfono y ahora
        # viene con mail): se usa SU key, no la nueva, para no partirlo en dos.
        key = existing.get("key") or key
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


def respondidos_sin_atender(store: Dict[str, Any], dias: int = 1) -> List[Dict[str, Any]]:
    """Leads que CONTESTARON y a los que nadie tocó desde entonces.

    `mark_replied` corta la secuencia a propósito —a alguien que contestó no se le
    sigue mandando el automático— pero al cortarla el lead deja de aparecer como
    «due» y se vuelve invisible. Data Trace Argentina contestó el 2026-09-16 con la
    secuencia ya agotada y estuvo dos días sin que nadie lo notara, siendo una de
    las dos únicas respuestas en mes y medio.

    Se considera atendido si hubo un toque DESPUÉS de la respuesta, o si ya avanzó
    a reunión/propuesta/cerrado.
    """
    hoy = datetime.now(timezone.utc)
    pendientes = []
    for l in store.get("leads", {}).values():
        resp = l.get("last_reply_at")
        if not resp or l.get("state") in ("reunión", "propuesta", "cerrado"):
            continue
        ultimo = max([str(t.get("date") or "") for t in (l.get("touches") or [])],
                     default="")
        if ultimo and ultimo >= str(resp)[:10]:
            continue                                   # se lo tocó después: atendido
        try:
            espera = (hoy - datetime.fromisoformat(str(resp))).days
        except ValueError:
            espera = 0
        if espera >= dias:
            pendientes.append({"key": l.get("key"), "empresa": l.get("company"),
                               "respondio": str(resp)[:10], "dias": espera,
                               "email": l.get("email"), "phone": l.get("phone")})
    pendientes.sort(key=lambda x: -x["dias"])
    return pendientes


def _progreso(lead: Dict[str, Any]) -> tuple:
    """Cuánto avanzó un lead. El que más avanzó es el que sobrevive a una fusión."""
    return (1 if lead.get("last_reply_at") else 0,
            {"cerrado": 5, "propuesta": 4, "reunión": 3, "respondió": 2}.get(
                lead.get("state") or "", 0),
            len(lead.get("touches") or []),
            -len(str(lead.get("first_seen") or "9999")))     # el más viejo desempata


def fusionar_duplicados(store: Dict[str, Any]) -> Dict[str, Any]:
    """Junta los leads que son la MISMA empresa entrada por puertas distintas.

    El daño que repara: la misma empresa con dos registros se contacta dos veces
    —queda mal con el prospecto— y parte su historia, así que la respuesta puede
    quedar en un registro mientras la secuencia sigue corriendo en el otro. Es lo
    que pasó con Zarcam Logística.

    Sobrevive el que más avanzó (ver `_progreso`), y nunca se pierde nada: los
    campos vacíos se completan desde los otros y los toques se unen. Devuelve el
    detalle de lo fusionado para poder mirarlo antes de guardar.
    """
    leads = store.setdefault("leads", {})
    por_id: Dict[str, List[Dict[str, Any]]] = {}
    for l in leads.values():
        ident = (identidad_telefono(l.get("phone", ""))
                 or normalize_email(l.get("email", ""))
                 or _nombre_empresa(l.get("company", "")))
        if ident:
            por_id.setdefault(ident, []).append(l)

    # Un lead puede caer en dos grupos (teléfono y nombre). Se fusiona una sola vez.
    ya = set()
    fusiones = []
    for ident, grupo in por_id.items():
        grupo = [l for l in grupo if l.get("key") not in ya]
        if len(grupo) < 2:
            continue
        grupo.sort(key=_progreso, reverse=True)
        gana, pierden = grupo[0], grupo[1:]
        for p in pierden:
            for campo in ("company", "email", "phone", "decisor", "industria", "web"):
                if p.get(campo) and not gana.get(campo):
                    gana[campo] = p[campo]
            gana.setdefault("touches", []).extend(p.get("touches") or [])
            if p.get("last_reply_at") and not gana.get("last_reply_at"):
                gana["last_reply_at"] = p["last_reply_at"]
                gana["state"] = "respondió"
            ya.add(p.get("key"))
            leads.pop(p.get("key"), None)
        gana["touches"].sort(key=lambda t: str(t.get("date") or ""))
        ya.add(gana.get("key"))
        fusiones.append({"queda": gana.get("key"), "empresa": gana.get("company"),
                         "absorbidos": [p.get("key") for p in pierden]})

    log.info("leads_fusionados", grupos=len(fusiones),
             borrados=sum(len(f["absorbidos"]) for f in fusiones))
    return {"grupos": len(fusiones),
            "borrados": sum(len(f["absorbidos"]) for f in fusiones),
            "detalle": fusiones}


def reprogramar_sin_agenda(store: Dict[str, Any], today: Optional[str] = None) -> int:
    """Agenda para hoy los leads que tienen email pero quedaron sin fecha de toque.

    `add_lead` solo agenda si el lead nace CON email; si nace sin uno,
    `next_touch_at` queda en None. Cuando después aparece un email —el
    enriquecimiento busca uno publicado en el sitio y lo setea— nadie vuelve a
    agendarlo, y como `_is_due(None)` es False el lead nunca entra al lote: queda
    invisible para siempre. El 2026-08-10 había 13 así, con email verificado.

    Se repara acá y no en el enriquecimiento a propósito: sirve para un email que
    llegue por cualquier vía (scraping, edición a mano, re-ingesta del reporte).
    Solo toca los `nuevo` sin tocar: un `sin_respuesta` agotó su secuencia y
    reprogramarlo sería volver a empezar sin que nadie lo pida.
    """
    today = _today_str(today)
    n = 0
    for lead in store.get("leads", {}).values():
        if (lead.get("email") and lead.get("state") == "nuevo"
                and not lead.get("next_touch_at") and not lead.get("touches")):
            lead["next_touch_at"] = today
            n += 1
    return n


def marcar_email_muerto(store: Dict[str, Any], key: str, motivo: str,
                        today: Optional[str] = None) -> Optional[str]:
    """Saca de la secuencia por email a un lead cuya casilla rebota seguro.

    La barrera de entregabilidad frenaba el envío y seguía de largo sin tocar el
    lead: quedaba `nuevo` con `next_touch_at` vencido, así que volvía a entrar al
    lote AL DÍA SIGUIENTE, volvía a fallar, y así para siempre. El 2026-08-10
    `Cuyana Repuestos` seguía en step 0 con fecha del 21/07 — un dominio sin MX
    ocupando un cupo de primer-toque todos los días.

    Si hay teléfono el lead NO se pierde: se le limpia el mail y cae en la cola de
    WhatsApp para contacto a mano. Sin teléfono no queda canal, así que se cierra.
    Devuelve a dónde fue a parar ("whatsapp" | "cerrado"), o None si no existe.
    """
    lead = store.get("leads", {}).get(key)
    if not lead:
        return None
    today = _today_str(today)
    lead["email"] = ""
    lead["next_touch_at"] = None          # fuera de due_for_touch
    lead.setdefault("notes", []).append(
        {"date": today, "note": f"email dado de baja: {motivo}"})
    if lead.get("phone"):
        lead["channel"] = "whatsapp"
        lead["state"] = "nuevo"           # whatsapp_queue pide estado 'nuevo'
        lead["next_step"] = 0
        return "whatsapp"
    lead["state"] = "sin_respuesta"
    return "cerrado"


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
            (l for l in leads.values()
             if identidad_telefono(l.get("phone", "")) == identidad_telefono(p)), None
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
                  # next_touch_at editable: sin esto un toque MANUAL a un lead caliente
                  # no se puede reconciliar con la secuencia (queda sin follow-ups o
                  # recibe uno automático encima).
                  "next_touch_at", "reengaged_at",
                  # outbound asistido por LinkedIn (perfil del decisor + nota/DM + estado)
                  "linkedin", "li_headline", "li_note", "li_dm", "li_state", "li_at"):
            if k in fields and fields[k] is not None:
                lead[k] = fields[k]
        # El teléfono editado a mano pasa por el normalizador igual que el que
        # entra por el formulario. Sin esto se guardaba crudo —`1153872152`— y
        # `_wa_link` armaba `wa.me/1153872152`, que no abre ningún chat. Si no se
        # puede normalizar se conserva lo tipeado: peor es perderlo.
        if fields.get("phone"):
            lead["phone"] = normalize_phone(fields["phone"]) or fields["phone"]
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
        # De dónde salió. Un lead que llenó el formulario de la web vale distinto
        # que uno que buscamos nosotros: nos escribió él. Sin este campo quedaba
        # indistinguible entre 350 leads de prospección y el panel no lo mostraba.
        "origen": lead.get("origen") or "prospeccion",
        "mensaje": (lead.get("mensaje") or "")[:300],
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


def daily_batch(due: List[Dict[str, Any]], cap: int) -> List[Dict[str, Any]]:
    """Reparte el cupo diario entre primer-toque y follow-ups para que ninguno mate al otro.

    `due_for_touch` ordena por vencimiento, y ahí está la trampa: un lead nuevo vence HOY
    mientras los follow-ups arrastran semanas de atraso. Con un corte plano `due[:cap]` los
    nuevos quedaban SIEMPRE debajo de la línea — al 2026-08-07 había 165 leads sin un solo
    contacto mientras el leadhunter sumaba 10 por día.

    Se reparte el MISMO cupo, no uno nuevo por carril: dos topes independientes duplican los
    envíos del día y queman la reputación del dominio (ya se unificaron por eso una vez).
    El carril que no llena su parte le cede el margen al otro, así no se desperdicia cupo.
    """
    if cap <= 0:
        return []
    nuevos = [l for l in due if not l.get("next_step")]
    followups = [l for l in due if l.get("next_step")]
    piso = max(1, cap // 2)
    lote = nuevos[:piso] + followups[:cap - piso]
    if len(lote) < cap:
        elegidos = {l.get("key") for l in lote}
        lote += [l for l in due if l.get("key") not in elegidos][:cap - len(lote)]
    return lote


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
    """Leads sin email y con teléfono → cola para contactar a mano, ROTANDO.

    Antes devolvía siempre los mismos en el mismo orden, así que el reporte diario
    mostraba las mismas 15 empresas un día tras otro. Medido el 2026-09-08: 116 leads
    en la cola y sólo 2 contactados en meses. Una lista que nunca cambia se vuelve
    invisible: el dueño aprende que ya la vio y saltea la sección entera.

    Ahora se ordena por "hace cuánto que no lo muestro" (`_wa_visto`), así cada día
    aparecen caras nuevas y toda la cola rota. Marcarlo lo hace `marcar_wa_mostrados`
    DESPUÉS de renderizar el reporte, no acá: si se marcara al leer, una corrida que
    falla igual quemaría el turno de esos leads.
    """
    cola = [
        l for l in store.get("leads", {}).values()
        if l.get("state") == "nuevo" and l.get("phone") and not l.get("email")
    ]
    # Los nunca mostrados primero (""), después los más viejos.
    cola.sort(key=lambda l: str(l.get("_wa_visto") or ""))
    return cola


def marcar_wa_mostrados(store: Dict[str, Any], leads: List[Dict[str, Any]],
                        hoy: str) -> None:
    """Deja constancia de que estos leads ya salieron en el reporte de hoy."""
    porclave = {l.get("key"): l for l in store.get("leads", {}).values()}
    for l in leads:
        real = porclave.get(l.get("key"))
        if real is not None:
            real["_wa_visto"] = hoy


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
    """Valor de `Label:` dentro del bloque, esté al principio de la línea o no.

    Antes alcanzaba con que la label apareciera en CUALQUIER parte de la línea y
    después se partía en el primer `:`. Dos formas de fallar, las dos vistas en
    reportes reales:
      - `- Empleados: 25-50   Web: https://x` con label "web" devolvía
        "25-50   Web: https://x" (partía por el `:` de Empleados, no por el suyo).
      - `- Discovery signals: (1) web con App Google Play` matcheaba "web" en
        prosa y devolvía la frase entera como si fuera el sitio.
    Ahora se exige la label seguida de `:` o `|`, y el valor se corta si en la
    misma línea arranca otro campo etiquetado.
    """
    for line in block.splitlines():
        for lab in labels:
            m = re.search(rf"(?i)(?:^|[\s*`>|-]){re.escape(lab)}\s*[:|]\s*(.+)", line)
            if not m:
                continue
            val = re.split(r"\s{2,}[A-Za-zÁÉÍÓÚÑáéíóúñ ]{3,20}\s*:", m.group(1))[0]
            val = re.sub(r"[*`>]", "", val).strip()
            if val:
                return val
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
