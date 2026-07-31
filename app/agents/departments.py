"""
Departamentos — organigrama de Automiq como "empresa de agentes".

Fuente ÚNICA de verdad de la estructura por sectores: cada departamento agrupa a
los agentes que lo componen. Lo consume el panel "OS" (grafo por departamentos) y
cualquier vista que necesite la organización. Los `agents` son los `name` reales
del registry (app/agents/*.py); si un agente no está acá, cae en "sin_departamento".

Colores = paleta de marca navy/azul (mismos del panel).
"""
from __future__ import annotations

from typing import Dict, List

# id -> {label, icon, color, desc, agents:[name]}
DEPARTMENTS: Dict[str, dict] = {
    "direccion": {
        "label": "Dirección",
        "icon": "🎯",
        "color": "#2563eb",
        "desc": "Coordina el equipo, cierra el día y convierte datos en decisiones.",
        "agents": ["chief_of_staff"],
    },
    "comercial": {
        "label": "Comercial / Ventas",
        "icon": "💼",
        "color": "#0ea5e9",
        "desc": "Consigue y convierte clientes: prospección, outbound, respuestas, reuniones.",
        "agents": ["leadhunter", "outbound", "inbox_assistant", "meeting_prep"],
    },
    "marketing": {
        "label": "Marketing / Contenido",
        "icon": "📣",
        "color": "#6366f1",
        "desc": "Marca y contenido: piezas, redes, shorts, dirección creativa y QA.",
        "agents": ["content_creator", "social_media", "tiktok_creator",
                   "creative_strategist", "media_auditor"],
    },
    "growth": {
        "label": "Growth / Web",
        "icon": "🚀",
        "color": "#0f766e",
        "desc": "Adquisición y web: growth, SEO/GEO, optimización y auditoría de sitios.",
        "agents": ["growth_hacker", "seo_specialist", "web_optimizer", "web_auditor"],
    },
    "finanzas": {
        "label": "Finanzas / Admin",
        "icon": "💰",
        "color": "#ca8a04",
        "desc": "Cuida la plata: gastos, MRR, cobranzas y decisiones financieras.",
        "agents": ["finance_officer"],
    },
    "customer_success": {
        "label": "Customer Success",
        "icon": "🤝",
        "color": "#16a34a",
        "desc": "Postventa y retención: onboarding, seguimiento y churn de clientes.",
        "agents": ["customer_success"],
    },
    "delivery": {
        "label": "Producto / Delivery",
        "icon": "🛠️",
        "color": "#9333ea",
        "desc": "Entrega el trabajo a clientes: etapas, bloqueos e hitos de cada proyecto.",
        "agents": ["delivery_pm"],
    },
}


def department_of(agent_name: str) -> str:
    """Departamento (id) al que pertenece un agente, o 'sin_departamento'."""
    for dept_id, dept in DEPARTMENTS.items():
        if agent_name in dept["agents"]:
            return dept_id
    return "sin_departamento"


def all_department_agents() -> List[str]:
    """Todos los agentes mapeados a algún departamento."""
    out: List[str] = []
    for dept in DEPARTMENTS.values():
        out.extend(dept["agents"])
    return out
