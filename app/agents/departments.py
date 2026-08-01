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

# Niveles de autonomía (proactividad de bajo riesgo), definidos POR departamento.
# Los agentes leen su nivel y se autorregulan (ver autonomy_note). Los gates duros
# que ya existen (no_publish, cola 1/día, tope de outbound) siguen vigentes aparte.
AUTONOMY_LEVELS = {
    "sugiere": "SOLO SUGERÍS: no ejecutás ninguna acción por tu cuenta. Todo lo que "
               "propongas queda para que el dueño lo apruebe. Nunca mandás nada afuera "
               "ni gastás plata.",
    "reversible": "Podés EJECUTAR SOLO acciones internas y 100% reversibles (guardar "
                  "notas/memoria, mover un lead de etapa, encolar borradores, generar "
                  "análisis/propuestas internas, deploy de preview). Todo lo que salga a "
                  "un tercero o gaste plata → lo SUGERÍS, no lo hacés.",
    "publica": "Además de lo reversible, podés EJECUTAR acciones outward YA planificadas y "
               "de bajo riesgo (publicar una pieza que ya está en cola/aprobada, mandar un "
               "follow-up a un lead que ya está en secuencia). NUNCA a un cliente nuevo, "
               "NUNCA gastás plata, NUNCA mail en frío a alguien nuevo sin aprobación.",
}

# id -> {label, icon, color, desc, autonomy, agents:[name]}
DEPARTMENTS: Dict[str, dict] = {
    "direccion": {
        "label": "Dirección",
        "icon": "🎯",
        "color": "#2563eb",
        "desc": "Coordina el equipo, cierra el día y convierte datos en decisiones.",
        "agents": ["chief_of_staff", "data_analyst"],
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
                   "creative_strategist", "media_auditor", "community_manager"],
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


# Nivel de autonomía POR departamento (defaults; el dueño los ajusta).
# Honra los ejemplos dados: Marketing publica, Comercial sugiere, Finanzas nunca acciona.
DEPT_AUTONOMY: Dict[str, str] = {
    "direccion": "reversible",       # planifica/delega interno, no publica ni gasta
    "comercial": "sugiere",          # todo pasa por aprobación del dueño
    "marketing": "publica",          # ejecuta lo ya aprobado/en cola
    "growth": "reversible",          # propone y deploya previews que se aprueban
    "finanzas": "sugiere",           # nunca acciona
    "customer_success": "reversible",  # guarda seguimiento, encola; no manda a clientes solo
    "delivery": "reversible",        # actualiza estado interno de proyectos
}


def autonomy_of(agent_name: str) -> str:
    """Nivel de autonomía del departamento del agente ('sugiere' por defecto)."""
    return DEPT_AUTONOMY.get(department_of(agent_name), "sugiere")


def autonomy_note(agent_name: str) -> str:
    """Bloque para inyectar al agente: su departamento + qué puede hacer solo."""
    dept_id = department_of(agent_name)
    dept = DEPARTMENTS.get(dept_id, {})
    level = DEPT_AUTONOMY.get(dept_id, "sugiere")
    rule = AUTONOMY_LEVELS.get(level, AUTONOMY_LEVELS["sugiere"])
    label = dept.get("label", "sin departamento")
    return (f"## Tu lugar en la empresa\nDepartamento: **{label}**. "
            f"Nivel de autonomía: **{level}**.\n{rule}")


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
