"""
localization — soporte multi-país para clientes hispanohablantes.

Automiq atiende PyMEs de habla hispana de varios países, no solo Argentina.
Cada cliente tiene un `country` (ISO-2). Este módulo mapea el país a su moneda,
tratamiento (vos/tú/usted), regulación de datos y notas locales, y arma un bloque
de directiva que se inyecta en el prompt de los agentes cuando trabajan sobre ese
cliente — así el copy, los ejemplos y los números salen localizados, no
AR-hardcodeados.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

DEFAULT_COUNTRY = "AR"

# code ISO-2 → datos locales. `treatment` = tratamiento dominante para copy.
COUNTRIES: Dict[str, Dict[str, str]] = {
    "AR": {"name": "Argentina",            "currency": "ARS", "treatment": "vos",        "data_law": "Ley 25.326"},
    "MX": {"name": "México",               "currency": "MXN", "treatment": "tú",         "data_law": "LFPDPPP"},
    "CO": {"name": "Colombia",             "currency": "COP", "treatment": "usted/tú",   "data_law": "Ley 1581 de 2012"},
    "CL": {"name": "Chile",                "currency": "CLP", "treatment": "tú/usted",   "data_law": "Ley 19.628"},
    "PE": {"name": "Perú",                 "currency": "PEN", "treatment": "tú/usted",   "data_law": "Ley 29733"},
    "ES": {"name": "España",               "currency": "EUR", "treatment": "tú",         "data_law": "RGPD / LOPDGDD"},
    "UY": {"name": "Uruguay",              "currency": "UYU", "treatment": "tú/vos",     "data_law": "Ley 18.331"},
    "EC": {"name": "Ecuador",              "currency": "USD", "treatment": "usted/tú",   "data_law": "LOPDP"},
    "PY": {"name": "Paraguay",             "currency": "PYG", "treatment": "vos/usted",  "data_law": "Ley 6534"},
    "BO": {"name": "Bolivia",              "currency": "BOB", "treatment": "usted/tú",   "data_law": "—"},
    "VE": {"name": "Venezuela",            "currency": "VES", "treatment": "tú/usted",   "data_law": "—"},
    "CR": {"name": "Costa Rica",           "currency": "CRC", "treatment": "usted",      "data_law": "Ley 8968"},
    "PA": {"name": "Panamá",               "currency": "USD", "treatment": "tú/usted",   "data_law": "Ley 81 de 2019"},
    "DO": {"name": "República Dominicana", "currency": "DOP", "treatment": "tú/usted",   "data_law": "Ley 172-13"},
    "GT": {"name": "Guatemala",            "currency": "GTQ", "treatment": "usted/vos",  "data_law": "—"},
    "SV": {"name": "El Salvador",          "currency": "USD", "treatment": "usted/vos",  "data_law": "—"},
    "HN": {"name": "Honduras",             "currency": "HNL", "treatment": "usted/vos",  "data_law": "—"},
    "NI": {"name": "Nicaragua",            "currency": "NIO", "treatment": "vos/usted",  "data_law": "—"},
    "PR": {"name": "Puerto Rico",          "currency": "USD", "treatment": "tú",         "data_law": "—"},
}


def normalize(code: Optional[str]) -> str:
    """Devuelve un código de país válido (default AR). Acepta code o nombre."""
    if not code:
        return DEFAULT_COUNTRY
    c = str(code).strip()
    up = c.upper()
    if up in COUNTRIES:
        return up
    # acepta el nombre ("México", "espana"...)
    low = c.lower()
    for k, v in COUNTRIES.items():
        if v["name"].lower() == low or v["name"].lower().replace("é", "e").replace("ú", "u") == low:
            return k
    return DEFAULT_COUNTRY


def get(code: Optional[str]) -> Dict[str, str]:
    return COUNTRIES[normalize(code)]


def label(code: Optional[str]) -> str:
    return get(code)["name"]


def list_countries() -> List[Dict[str, str]]:
    """Para poblar el <select> del dashboard. Argentina primero."""
    order = ["AR", "MX", "CO", "CL", "PE", "ES", "UY", "EC", "PY",
             "BO", "VE", "CR", "PA", "DO", "GT", "SV", "HN", "NI", "PR"]
    return [{"code": k, "name": COUNTRIES[k]["name"], "currency": COUNTRIES[k]["currency"]} for k in order]


def locale_block(code: Optional[str]) -> str:
    """Directiva de localización para inyectar en el prompt del agente."""
    info = get(code)
    return (
        f"## LOCALIZACIÓN — {info['name']}\n"
        f"Este cliente es de **{info['name']}**. Adaptá TODO a ese país, no a Argentina:\n"
        f"- **Moneda:** {info['currency']} (montos y pricing en {info['currency']}; "
        f"no uses ARS salvo que el país sea Argentina).\n"
        f"- **Tratamiento:** usá «{info['treatment']}» en el copy (no «vos» por defecto).\n"
        f"- **Modismos y referencias:** usá expresiones, ejemplos y empresas locales de "
        f"{info['name']}, no argentinas.\n"
        f"- **Regulación de datos:** {info['data_law']}.\n"
        f"- WhatsApp sigue siendo el canal primario en LATAM; en España sumá email/LinkedIn.\n"
    )
