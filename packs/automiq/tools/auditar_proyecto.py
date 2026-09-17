"""
auditar_proyecto — le da a un agente el estado real de un sistema que operamos.

Los chequeos son deterministas y viven en `integrations/proyectos.py`. Esta tool
no decide si algo está mal: trae los hallazgos ya detectados para que el agente
haga lo que un chequeo no puede — priorizar, conectar dos síntomas, redactar el
aviso al dueño. Dejarle al modelo la detección es como se fabrican hallazgos
falsos, y ya nos comimos uno que estuvo 22 días siendo mentira.
"""
from __future__ import annotations

from typing import Any, Dict

AUDITAR_PROYECTO_SCHEMA = {
    "name": "auditar_proyecto",
    "description": (
        "Estado y hallazgos de un sistema que la agencia opera: 'clamevet' "
        "(la plataforma del cliente), 'crm' (el CRM multi-empresa y sus "
        "tenants), 'agentes' (este equipo) o 'landing' (la web). Sin id, "
        "audita todos. Devuelve salud, números propios de cada sistema y "
        "hallazgos ya verificados, ordenados por gravedad."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "id": {
                "type": "string",
                "enum": ["clamevet", "crm", "agentes", "landing"],
                "description": "Cuál auditar. Vacío = todos.",
            }
        },
        "required": [],
    },
}


def auditar_proyecto(id: str = "") -> Dict[str, Any]:
    from app.integrations import proyectos

    if id and id not in {p["id"] for p in proyectos.PROYECTOS}:
        return {"error": f"No existe el proyecto «{id}».",
                "disponibles": [p["id"] for p in proyectos.PROYECTOS]}
    return proyectos.auditar(id or None)
