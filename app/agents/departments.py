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
    "publica": "Además de lo reversible, podés EJECUTAR acciones outward que ya están "
               "dentro de un PROGRAMA APROBADO Y CORRIENDO (publicar una pieza de la cola, "
               "mandar un toque de la secuencia de cold-email dentro del tope diario, "
               "responder a alguien que ya te escribió). El programa es la aprobación: no "
               "pidas permiso pieza por pieza. Fuera del programa —un canal nuevo, un "
               "mensaje a un cliente activo, cualquier cosa que gaste plata— lo SUGERÍS.",
}

# id -> {label, icon, color, desc, autonomy, agents:[name]}
DEPARTMENTS: Dict[str, dict] = {
    "direccion": {
        "label": "Dirección",
        "icon": "🎯",
        "color": "#ff4d6d",
        "desc": "Coordina el equipo, cierra el día y convierte datos en decisiones.",
        "agents": ["chief_of_staff", "data_analyst"],
    },
    "comercial": {
        "label": "Comercial / Ventas",
        "icon": "💼",
        "color": "#ffb020",
        "desc": "Consigue y convierte clientes: prospección, outbound, respuestas, reuniones.",
        "agents": ["leadhunter", "outbound", "inbox_assistant", "meeting_prep"],
    },
    "marketing": {
        "label": "Marketing / Contenido",
        "icon": "📣",
        "color": "#b15cff",
        "desc": "Marca y contenido: piezas, redes, shorts, dirección creativa y QA.",
        "agents": ["content_creator", "social_media", "tiktok_creator",
                   "creative_strategist", "media_auditor", "community_manager"],
    },
    "growth": {
        "label": "Growth / Web",
        "icon": "🚀",
        "color": "#21d07a",
        "desc": "Adquisición y web: growth, SEO/GEO, optimización y auditoría de sitios.",
        "agents": ["growth_hacker", "seo_specialist", "web_optimizer", "web_auditor"],
    },
    "finanzas": {
        "label": "Finanzas / Admin",
        "icon": "💰",
        "color": "#16d6c9",
        "desc": "Cuida la plata: gastos, MRR, cobranzas y decisiones financieras.",
        "agents": ["finance_officer"],
    },
    "customer_success": {
        "label": "Customer Success",
        "icon": "🤝",
        "color": "#4d96ff",
        "desc": "Postventa y retención: onboarding, seguimiento y churn de clientes.",
        "agents": ["customer_success"],
    },
    "delivery": {
        "label": "Producto / Delivery",
        "icon": "🛠️",
        "color": "#ff7847",
        "desc": "Entrega el trabajo a clientes: etapas, bloqueos e hitos de cada proyecto.",
        "agents": ["delivery_pm"],
    },
}


# Conexiones REALES de cada agente (feeds/servicios/MCPs que usa en sus corridas).
# Para el panel OS: fila superior del árbol del depto + sección TOOLS del detalle.
AGENT_CONNECTIONS: Dict[str, List[str]] = {
    "leadhunter": ["WebFetch", "Discovery AR"],
    "outbound": ["Gmail Ventas@", "Leads Store"],
    "inbox_assistant": ["Gmail Ventas@", "Google Calendar"],
    "meeting_prep": ["Memoria Supabase", "Google Calendar"],
    "content_creator": ["Vertex Imagen", "Meta IG/FB"],
    "social_media": ["Publish Queue", "Meta IG/FB"],
    "tiktok_creator": ["Veo 3.1 Vertex", "Montage Svc", "YouTube", "TikTok"],
    "creative_strategist": ["Vertex Imagen", "Playbooks"],
    "media_auditor": ["Benchmarks Ads"],
    "community_manager": ["Meta Comments", "Auto-DM Gate"],
    "growth_hacker": ["Metrics Store"],
    "seo_specialist": ["Landing Astro"],
    "web_optimizer": ["Search Console", "Vercel"],
    "web_auditor": ["WebFetch"],
    "chief_of_staff": ["Reportes data/", "Misiones", "Buzón Agentes"],
    "data_analyst": ["Metrics Store", "Finanzas Store"],
    "finance_officer": ["Finanzas Store", "Clientes Store"],
    "customer_success": ["Clientes Store", "Memoria Clientes"],
    "delivery_pm": ["Clientes Store", "Misiones"],
}


# Nivel de autonomía POR departamento (defaults; el dueño los ajusta).
# Honra los ejemplos dados: Marketing publica, Comercial sugiere, Finanzas nunca acciona.
DEPT_AUTONOMY: Dict[str, str] = {
    "direccion": "reversible",       # planifica/delega interno, no publica ni gasta
    # 'sugiere' era FALSO y se contradecía con el código: OUTBOUND_AUTO_SEND e
    # INBOX_AUTO_SEND están en true, o sea que outbound manda cold-email solo (con
    # tope diario) e inbox_assistant contesta solo. Decirle a esos agentes "nunca
    # mandás nada afuera" mientras el sistema manda por ellos los hacía trabajar
    # contra su propia realidad: escribían como si fuera un borrador a aprobar.
    # El programa de cold-email ES la aprobación (directiva del dueño 2026-07-11:
    # los canales que corren nunca se frenan).
    "comercial": "publica",
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


def teammates_of(agent_name: str) -> List[str]:
    """Compañeros del MISMO departamento (sin incluirlo a él).

    Base de la colaboración departamental: cada agente sabe con quién comparte
    sector, ve lo que produjeron y puede dejarle una nota a todo el equipo."""
    dept = DEPARTMENTS.get(department_of(agent_name))
    return [a for a in dept["agents"] if a != agent_name] if dept else []


def all_department_agents() -> List[str]:
    """Todos los agentes mapeados a algún departamento."""
    out: List[str] = []
    for dept in DEPARTMENTS.values():
        out.extend(dept["agents"])
    return out
