"""
seed_memory_from_obsidian — siembra la memoria general de la agencia (company_memory
+ growth_objectives) con el contexto curado del vault de Obsidian.

Obsidian es local (no lo ve Railway), así que este script corre en la máquina del
operador con DATABASE_URL apuntando a Supabase y empuja el contexto al schema
`agency`. Es idempotente (upsert por section+title), se puede re-correr cuando el
vault cambie.

Uso:
    DATABASE_URL="postgresql://…"  python scripts/seed_memory_from_obsidian.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.integrations import memory_store as ms  # noqa: E402
from app.integrations import db  # noqa: E402

SRC = "obsidian:00-Agency/Agency-MOC.md"
SRC_V = "obsidian:01-Strategy/Verticales.md"

COMPANY = [
    ("identidad", "Qué es Automiq",
     "Agencia de automatización con IA para PyMEs de Argentina (manufactura, distribución, "
     "logística, inmobiliarias). Vendemos agentes de IA que atienden y venden por WhatsApp 24/7, "
     "automatizaciones a medida y un CRM propio. Zona horaria America/Buenos_Aires.", SRC),
    ("identidad", "Posicionamiento",
     "Especialización o muerte (insight Claudio Conde): apuntar a UN vertical y volverse LA agencia "
     "de referencia de ese nicho. Vertical prioritario candidato: Distribución. Marco de venta: "
     "Empresa → Oferta → Tecnología (Visual Project).", SRC),
    ("servicios", "Catálogo de servicios",
     "1) Agentes de IA (leads, contenido, outbound). 2) Automatizaciones a medida (n8n, WhatsApp "
     "Cloud API, integraciones CRM). 3) Landing pages (Astro/Vercel). 4) CRM propio (pipeline de "
     "leads y tareas). 5) Meta Ads (setup + gestión). 6) Auditorías de medios + competitivo.", SRC),
    ("producto", "CRM Automiq (white-label)",
     "CRM propio (base 'Atiendechat') rebrandeado a Automiq: WhatsApp Cloud + multicanal (IG/"
     "Messenger), agente IA por empresa, KB/RAG, Meta Lead Ads, agenda, reportes, billing. Modelo: "
     "una instancia amoldada por cliente, hosteada por el cliente en su Hostinger.", "obsidian:CRM/CRM MOC.md"),
    ("pricing", "Tickets por vertical",
     "Setup desde USD 500. Mensual USD 200–800 según vertical. Ticket anual estimado: distribución "
     "USD 4.5K–9.2K, logística USD 6K–12K, manufactura USD 3K–7.5K, inmobiliarias USD 3K–6K. "
     "Criterio de fit: poder cobrar USD 500+ de setup.", SRC_V),
    ("verticales", "Distribución (fit 5/5)",
     "Mayoristas/distribuidoras (alimentos, bebidas, repuestos, insumos), 25–100 empleados. Dolor "
     "caro: cobranza atrasada (~30% cartera), toma de pedidos manual, follow-ups que se escapan. "
     "Solución: WhatsApp outbound de cobranza, voice inbound de pedidos, bot de re-compra. Canal: "
     "asociaciones por rubro, LinkedIn, rondas de negocio. EL VERTICAL PRIORITARIO.", SRC_V),
    ("verticales", "Logística (fit 4/5)",
     "Transporte/flotas/última milla. Dolor: '¿dónde está mi envío?' 50+/día, ruteo manual, "
     "coordinación con choferes. Solución: bot de tracking por guía, notificaciones de estado, "
     "voice agent para choferes. Canal: CATAC/APROCAM, ferias, LinkedIn.", SRC_V),
    ("verticales", "Manufactura (fit 4/5)",
     "PyMEs familiares 25–100 empleados (alimentos, metalmecánica, plásticos, muebles, textiles). "
     "Dolor: '¿en qué anda mi pedido?' 2–4h/día, cotizaciones lentas, atención B2B fuera de hora. "
     "Solución: agente WhatsApp conectado al ERP, voice para pedidos, bot de cotización.", SRC_V),
    ("verticales", "Inmobiliarias (fit 3/5)",
     "Inmobiliarias residenciales/comerciales 5–30 empleados (Tokko/Wasi). Dolor: 80% consultas no "
     "calificadas, sin nurturing, agendar visitas. Solución: bot de calificación, secuencia de "
     "nurturing, agendamiento automático. Buena presencia en IG. Ticket más bajo.", SRC_V),
    ("canales", "Canales de prospección",
     "Cámaras (UIA, CAME, CATAC, CUCICBA, Colegio de Martilleros), ferias del rubro, LinkedIn "
     "(grupos por nicho), Google Maps (búsquedas locales), Instagram (inmobiliarias).", SRC_V),
    ("ventas", "Máquina de ventas (pipeline en vivo)",
     "LeadHunter (10 leads/día, PyMEs + email) → Web Auditor (audita el sitio del prospecto → "
     "dolores) → Outbound (secuencia día 0/+2/+4/+7, frena sola al recibir respuesta) → Inbox "
     "(marca 'respondió' y avisa 🔥). leads_store es la fuente de verdad.", SRC),
]

GROWTH = [
    ("distribución", "Cerrar 3 ventas reales antes de invertir en ads", "ventas cerradas", "3"),
    ("distribución", "Validar distribución como vertical prioritario", "decisión", "confirmado"),
    ("distribución", "Llegar a 3 reuniones agendadas con distribuidoras", "reuniones", "3"),
    ("general", "Armar 4 pitches de 4 líneas (uno por vertical)", "pitches", "4"),
    ("general", "Documentar 1 proyecto real en IG/LinkedIn", "casos publicados", "1"),
]


def main() -> None:
    if not db.enabled():
        print("[err] DATABASE_URL no configurada — exportá la URL de Supabase y reintentá.")
        sys.exit(1)
    print("DB:", db.healthcheck())
    for section, title, content, source in COMPANY:
        ms.upsert_company_memory(section, title, content, source=source)
    print(f"[ok] company_memory: {len(COMPANY)} entradas sembradas/actualizadas")

    existing = {(o["sector"], o["objective"]) for o in ms.list_growth()}
    added = 0
    for sector, objective, metric, target in GROWTH:
        if (sector, objective) not in existing:
            ms.add_growth(sector, objective, metric=metric, target=target)
            added += 1
    print(f"[ok] growth_objectives: {added} nuevos (de {len(GROWTH)})")
    print("Total en company_memory:", len(ms.list_company_memory()))


if __name__ == "__main__":
    main()
