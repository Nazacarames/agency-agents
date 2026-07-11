"""
lead_demo — demo PERSONALIZADA por lead: el activo N3 que sube la conversión.

Evidencia (research 2026-07-11): los cold emails que muestran al prospecto SU
problema resuelto convierten 5x más que los genéricos; una demo/video
personalizado sube reuniones +40-50% (Sendspark/Martal/Belkins). Esto genera,
por lead, un mockup de WhatsApp REAL (Pillow, texto exacto) donde un agente de
IA atiende a un cliente de SU negocio, servido en una página con marca:

  GET /d/{demo_key}  →  página "Así respondería un agente de IA en <empresa>"
                        (pública, sin secret) + CTA a WhatsApp.

La VISTA de la página es una señal de compra: se loguea, se anota en el lead y
avisa por Discord al canal de ventas (speed-to-lead: el benchmark LATAM es
responder en <5 min).

Conversación por vertical: plantillas determinísticas (sin LLM: instantáneo,
gratis, texto siempre correcto) con el nombre del negocio inyectado.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..log import get_logger
from .jsonstore import write_json_atomic

log = get_logger("lead_demo")

_FILE = Path(__file__).resolve().parent.parent.parent / "data" / "lead-demos.json"

# Conversaciones por vertical: (cliente, bot) — el bot SIEMPRE resuelve rápido,
# con número/detalle creíble y cierre suave (así se ve el producto funcionando).
_CONVOS: Dict[str, List[Dict[str, str]]] = {
    "distribucion": [
        {"from": "them", "time": "21:47", "text": "Hola, ¿tienen stock del jabón líquido 5L? Necesito 40 para el jueves"},
        {"from": "bot", "time": "21:47", "text": "¡Hola! Sí, tenemos 120 unidades del 5L. Para 40 te queda $8.900 c/u con entrega el jueves a la mañana. ¿Te armo el pedido?"},
        {"from": "them", "time": "21:48", "text": "Dale. ¿Aceptan cuenta corriente?"},
        {"from": "bot", "time": "21:48", "text": "Sí, a 30 días como siempre. Pedido armado, te llega la confirmación con el remito. ¡Gracias!"},
    ],
    "manufactura": [
        {"from": "them", "time": "18:32", "text": "Buenas, ¿hacen piezas a medida? Necesito cotizar 200 soportes según plano"},
        {"from": "bot", "time": "18:32", "text": "¡Hola! Sí, trabajamos a plano. Pasame el archivo o las medidas y te cotizo en el día. Para 200 unidades el plazo típico es 10 días hábiles."},
        {"from": "them", "time": "18:34", "text": "Te mando el PDF mañana. ¿Atienden los sábados?"},
        {"from": "bot", "time": "18:34", "text": "Respondemos 24/7 por acá. Apenas mandes el plano te confirmo precio y fecha. Quedo atento."},
    ],
    "inmobiliaria": [
        {"from": "them", "time": "22:15", "text": "Hola! Vi el depto de 2 amb en Belgrano. ¿Sigue disponible? ¿Acepta mascotas?"},
        {"from": "bot", "time": "22:15", "text": "¡Hola! Sí, está disponible y acepta mascotas chicas. Son $650.000 + expensas. ¿Querés coordinar una visita? Tengo mañana 11:00 o 16:30."},
        {"from": "them", "time": "22:16", "text": "Mañana 16:30 perfecto"},
        {"from": "bot", "time": "22:16", "text": "¡Agendado! Mañana 16:30. Te mando la ubicación y el recordatorio. Cualquier cosa me escribís."},
    ],
    "logistica": [
        {"from": "them", "time": "20:05", "text": "Necesito enviar 3 pallets a Rosario el viernes, ¿tienen disponibilidad?"},
        {"from": "bot", "time": "20:05", "text": "¡Hola! Sí, tenemos salida a Rosario viernes 7 AM. 3 pallets te queda $95.000 con seguro incluido. ¿Confirmo la reserva?"},
        {"from": "them", "time": "20:07", "text": "Confirmá. ¿Me pasás el tracking?"},
        {"from": "bot", "time": "20:07", "text": "Reservado. El viernes a primera hora te llega el link de seguimiento en vivo. ¡Gracias!"},
    ],
}
_DEFAULT = "distribucion"

_ALIASES = {
    "distribución": "distribucion", "distribucion": "distribucion", "mayorista": "distribucion",
    "manufactura": "manufactura", "metalúrgica": "manufactura", "metalurgica": "manufactura",
    "industria": "manufactura", "fábrica": "manufactura", "fabrica": "manufactura",
    "inmobiliaria": "inmobiliaria", "propiedades": "inmobiliaria",
    "logística": "logistica", "logistica": "logistica", "transporte": "logistica",
}


def _vertical_for(industria: str) -> str:
    low = (industria or "").lower()
    for k, v in _ALIASES.items():
        if k in low:
            return v
    return _DEFAULT


def _load() -> Dict[str, Any]:
    try:
        data = json.loads(_FILE.read_text(encoding="utf-8"))
        data.setdefault("demos", {})
        return data
    except Exception:
        return {"demos": {}}


def _save(data: Dict[str, Any]) -> None:
    write_json_atomic(_FILE, data, indent=1)


def ensure_demo(lead: Dict[str, Any]) -> Optional[str]:
    """Genera (o reusa) la demo del lead. Devuelve la URL pública /d/<key> o None."""
    company = (lead.get("company") or "").strip()
    if not company:
        return None
    lead_key = lead.get("key") or company.lower()
    data = _load()
    for key, d in data["demos"].items():
        if d.get("lead_key") == lead_key and d.get("image"):
            return f"/d/{key}"
    try:
        from . import chat_mockup
        convo = _CONVOS[_vertical_for(lead.get("industria", ""))]
        image_url = chat_mockup.render_whatsapp(company[:34], convo)
        if not image_url:
            return None
    except Exception as e:
        log.warning("lead_demo_render_failed", company=company, error=str(e)[:150])
        return None
    key = uuid.uuid4().hex[:10]
    data["demos"][key] = {
        "lead_key": lead_key, "company": company,
        "industria": lead.get("industria", ""), "image": image_url,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "views": 0, "last_view": None,
    }
    _save(data)
    log.info("lead_demo_created", company=company, key=key)
    return f"/d/{key}"


def get_demo(key: str) -> Optional[Dict[str, Any]]:
    return _load()["demos"].get(key)


def record_view(key: str) -> Optional[Dict[str, Any]]:
    """Marca una vista (señal de compra): contador + nota en el lead + True si es la 1ª."""
    data = _load()
    d = data["demos"].get(key)
    if not d:
        return None
    d["views"] = int(d.get("views", 0)) + 1
    first = d["views"] == 1
    d["last_view"] = datetime.now(timezone.utc).isoformat()
    _save(data)
    # dejar rastro en el lead (best-effort)
    try:
        from . import leads_store as ls
        store = ls.load_store()
        lead = store.get("leads", {}).get(d.get("lead_key"))
        if lead is not None:
            lead.setdefault("notes", []).append(
                f"[auto] 🔥 Abrió su demo personalizada ({d['views']}ª vista).")
            ls.save_store(store)
    except Exception:
        pass
    return {**d, "first_view": first}


def render_page(d: Dict[str, Any], wa_number: str = "5491127713231") -> str:
    """HTML de la página pública de demo (marca Automiq, mobile-first)."""
    company = d.get("company", "tu negocio")
    img = d.get("image", "")
    wa_text = f"Hola! Vi la demo del agente de IA para {company} y quiero saber más"
    wa_link = f"https://wa.me/{wa_number}?text=" + wa_text.replace(" ", "%20")
    return f"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex">
<title>Así atendería un agente de IA en {company} — Automiq</title>
<style>
body{{margin:0;background:#0b1526;color:#eef2f7;font-family:-apple-system,Segoe UI,Roboto,sans-serif}}
.wrap{{max-width:520px;margin:0 auto;padding:28px 18px 60px;text-align:center}}
.logo{{font-weight:800;letter-spacing:.06em;color:#7dd3fc;font-size:14px;margin-bottom:18px}}
h1{{font-size:24px;line-height:1.25;margin:0 0 6px}}
.sub{{color:#9db2c8;font-size:15px;margin-bottom:22px}}
img{{width:100%;border-radius:18px;box-shadow:0 12px 40px rgba(0,0,0,.45)}}
.cta{{display:block;margin:26px auto 10px;background:#22c55e;color:#04140a;font-weight:700;
font-size:17px;padding:15px 22px;border-radius:14px;text-decoration:none}}
.mini{{color:#7b8ea6;font-size:12px;margin-top:16px}}
</style></head><body><div class="wrap">
<div class="logo">AUTOMIQ</div>
<h1>Así atendería un agente de IA en {company}</h1>
<div class="sub">Responde al toque, 24/7, arma el pedido y lo carga al sistema — mientras vos dormís.</div>
<img src="{img}" alt="Demo del agente de IA respondiendo por WhatsApp en {company}">
<a class="cta" href="{wa_link}">Quiero esto en {company} → WhatsApp</a>
<div class="mini">Demo ilustrativa generada para {company} · automiq.agency</div>
</div></body></html>"""
