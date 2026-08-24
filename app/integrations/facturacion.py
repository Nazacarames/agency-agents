"""
Facturación electrónica ARCA (ex AFIP) vía AfipSDK — para el panel de la agencia.

Emite Factura C (monotributo) a los clientes y guarda cada comprobante en
data/invoices.json. Config en app.config.Settings (arca_*). AfipSDK
(https://app.afipsdk.com) resuelve WSAA + WSFEv1: se le pasa CUIT + access_token
y devuelve el CAE; el certificado (producción) vive en el dashboard de AfipSDK.

Sin token/cuit -> is_configured() False y emit_invoice() devuelve status 'skipped'.
"""
from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from ..config import Settings
from ..log import get_logger

log = get_logger("facturacion")
_LOCK = threading.Lock()


def _settings() -> Settings:
    return Settings()


def _data_dir() -> Path:
    return Path(__file__).resolve().parent.parent.parent / "data"


def _store_path() -> Path:
    return _data_dir() / "invoices.json"


def is_configured() -> bool:
    s = _settings()
    return bool(s.arca_access_token and s.arca_cuit)


def _client():
    from afip import Afip
    s = _settings()
    return Afip({
        "CUIT": int(str(s.arca_cuit).replace("-", "").strip()),
        "access_token": s.arca_access_token,
        "production": bool(s.arca_production),
    })


def load_invoices() -> List[Dict[str, Any]]:
    p = _store_path()
    if not p.exists():
        return []
    try:
        with p.open("r", encoding="utf-8") as f:
            return json.load(f).get("invoices", [])
    except Exception:
        return []


def _save(items: List[Dict[str, Any]]) -> None:
    p = _store_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump({"invoices": items}, f, ensure_ascii=False, indent=2)
    os.replace(tmp, p)


def list_invoices(limit: int = 200) -> List[Dict[str, Any]]:
    items = sorted(load_invoices(), key=lambda i: i.get("created_at", ""), reverse=True)
    return items[:limit]


def emit_invoice(amount: float, description: str = "", cliente: str = "",
                 doc_tipo: int = 99, doc_nro: int = 0, cond_iva_receptor: int = 5) -> Dict[str, Any]:
    """Emite una Factura C por `amount` ARS (Concepto 2, servicios). doc_tipo/doc_nro
    identifican al receptor cuando corresponde (80 = CUIT, 96 = DNI). Registra el
    resultado siempre y lo devuelve."""
    inv: Dict[str, Any] = {
        "id": uuid.uuid4().hex[:12],
        "cliente": (cliente or "").strip(),
        "description": (description or "").strip()[:255],
        "amount": round(float(amount or 0), 2),
        "currency": "ARS",
        "cbte_tipo": None, "pto_vta": None, "cbte_nro": None,
        "cae": None, "cae_vto": None,
        "status": "pending", "error": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    if not is_configured():
        inv["status"] = "skipped"
        inv["error"] = "ARCA no configurado"
        with _LOCK:
            items = load_invoices()
            items.insert(0, inv)
            _save(items)
        return inv

    try:
        s = _settings()
        pto_vta = int(s.arca_pto_vta or 1)
        cbte_tipo = int(s.arca_cbte_tipo or 11)
        eb = _client().ElectronicBilling
        nro = eb.getLastVoucher(pto_vta, cbte_tipo) + 1
        hoy = int(datetime.now(timezone.utc).strftime("%Y%m%d"))
        amt = inv["amount"]

        # Factura C: neto = total, sin IVA discriminado.
        data = {
            "CantReg": 1, "PtoVta": pto_vta, "CbteTipo": cbte_tipo,
            "Concepto": 2, "DocTipo": doc_tipo, "DocNro": doc_nro,
            "CbteDesde": nro, "CbteHasta": nro, "CbteFch": hoy,
            "ImpTotal": amt, "ImpTotConc": 0, "ImpNeto": amt,
            "ImpOpEx": 0, "ImpIVA": 0, "ImpTrib": 0,
            "FchServDesde": hoy, "FchServHasta": hoy, "FchVtoPago": hoy,
            "MonId": "PES", "MonCotiz": 1,
            "CondicionIVAReceptorId": cond_iva_receptor,
        }
        res = eb.createVoucher(data)
        cae = res.get("CAE")
        if not cae:
            raise RuntimeError(f"CAE rechazado: {res}")
        vto = str(res.get("CAEFchVto") or "")
        inv.update({
            "status": "issued", "cbte_tipo": cbte_tipo, "pto_vta": pto_vta,
            "cbte_nro": nro, "cae": cae,
            "cae_vto": vto if "-" in vto else (
                f"{vto[:4]}-{vto[4:6]}-{vto[6:]}" if len(vto) == 8 else None),
        })
        log.info("factura emitida cae=%s nro=%s cliente=%s", cae, nro, inv["cliente"])
    except Exception as e:
        inv["status"] = "error"
        inv["error"] = str(e)[:300]
        log.error("factura error: %s", e)

    with _LOCK:
        items = load_invoices()
        items.insert(0, inv)
        _save(items)
    return inv
