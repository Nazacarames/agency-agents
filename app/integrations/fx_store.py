"""
fx_store — tipos de cambio para convertir monedas nativas de clientes/gastos a USD.

Los clientes facturan en su moneda (ARS, MXN, …) y las finanzas se totalizan en USD.
Las tasas son `1 unidad de <moneda> = X USD` y se editan desde el panel (Finanzas).
Persistencia: JSON en el volume (data/fx-store.json), igual que el resto de stores.
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any, Dict

_LOCK = threading.Lock()  # serializa leer→modificar→guardar

# Defaults aproximados (el usuario los ajusta en el panel). 1 unidad = X USD.
DEFAULT_RATES: Dict[str, float] = {
    "USD": 1.0,
    "ARS": 0.00083,   # peso argentino
    "MXN": 0.055,     # peso mexicano
    "CLP": 0.00105,   # peso chileno
    "COP": 0.00025,   # peso colombiano
    "PEN": 0.27,      # sol peruano
    "UYU": 0.025,     # peso uruguayo
    "BOB": 0.144,     # boliviano
    "PYG": 0.00013,   # guaraní
    "EUR": 1.08,      # euro (España)
    "BRL": 0.18,      # real
}


def _data_dir() -> Path:
    return Path(__file__).resolve().parent.parent.parent / "data"


def _store_path() -> Path:
    return _data_dir() / "fx-store.json"


def get_rates() -> Dict[str, float]:
    """Tasas actuales (defaults + lo que el usuario haya editado)."""
    rates = dict(DEFAULT_RATES)
    p = _store_path()
    if p.exists():
        try:
            with p.open("r", encoding="utf-8") as f:
                saved = json.load(f).get("rates", {})
            for k, v in saved.items():
                try:
                    rates[str(k).upper()] = float(v)
                except (TypeError, ValueError):
                    continue
        except Exception:
            pass
    return rates


def _save(rates: Dict[str, float]) -> None:
    p = _store_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump({"rates": rates}, f, ensure_ascii=False, indent=2)
    os.replace(tmp, p)


def set_rate(currency: str, usd_rate: float) -> Dict[str, float]:
    cur = (currency or "").upper().strip()
    if not cur:
        return get_rates()
    with _LOCK:
        rates = get_rates()
        try:
            rates[cur] = float(usd_rate)
        except (TypeError, ValueError):
            return rates
        _save(rates)
    return rates


def set_rates(updates: Dict[str, Any]) -> Dict[str, float]:
    with _LOCK:
        rates = get_rates()
        for k, v in (updates or {}).items():
            try:
                rates[str(k).upper().strip()] = float(v)
            except (TypeError, ValueError):
                continue
        _save(rates)
    return rates


def to_usd(amount: Any, currency: str) -> float:
    """Convierte `amount` en `currency` a USD. Moneda desconocida → asume USD."""
    try:
        amt = float(amount or 0)
    except (TypeError, ValueError):
        return 0.0
    rate = get_rates().get((currency or "USD").upper(), 1.0)
    return round(amt * rate, 2)
