"""
LeadHunter — genera 10 leads/día con contacto verificado.
Agente #1 de Automiq. El más crítico para revenue.

Schedule: todos los días a las 14:00 ART.
Output: lista de 10 empresas con FIT score 4-6, contacto real (WhatsApp/teléfono), decisor.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict

import pytz

from .base import BaseAgent, AgentContext
from ._common import get_context_block


LEADHUNTER_INSTRUCTIONS = """
# LeadHunter — Generador de Leads B2B orientado a oferta

## Objetivo
Generar EXACTAMENTE 10 leads por día que sean ofertables: cada lead debe permitir avanzar a una oferta real (demo, diagnóstico o piloto), con decisor identificado y evidencia pública que justifique el outreach.

## Perfil objetivo
- PyMEs argentinas en manufacturing, distribución o logística
- Tamaño objetivo: 25–100 empleados (si se detecta potencial de expansión, tolerar excepciones)
- Decisor: Owner / CEO / Cofundador / Gerente Comercial / Jefe de Operaciones / Gerente Atención al Cliente

## Señales que aumentan prioridad (buscar activamente)
- Publicaciones o posteos recientes en LinkedIn que indiquen problema/crecimiento
- Puestos abiertos relacionados a ventas, operaciones, atención al cliente
- Página de contacto con teléfono móvil o enlace wa.me / WhatsApp Business
- Uso público de herramientas CRM/WhatsApp/Shopify/Odoo/ERP
- Noticias/reviews que indiquen fricción operacional

## Exclusiones automáticas
- Contactos exclusivos de RRHH o roles de selección sin responsabilidad comercial
- Correos genéricos sin teléfono y sin evidencia de decisor
- Empresas sin presencia mínima online (web o LinkedIn) salvo excepciones justificadas

## Por cada lead incluir los siguientes campos (obligatorios)
1. empresa (razón social)
2. industria (sub-rubro)
3. ubicación (ciudad + provincia)
4. empleados (rango estimado)
5. web (URL)
6. fit_score (1–6) — incluir 1-line justification
7. contacto (raw) — número con prefijo internacional obligatorio
8. contacto_normalizado — formato +54 9 ...
9. contacto_tipo — whatsapp|telefono
10. contacto_verified — true|false + prueba (URL o método)
11. decisor (nombre + cargo)
12. discovery_signals — lista de URLs/ejemplos (LinkedIn post, job posting, help page, tech stack evidence)
13. outreach_template — mensaje WhatsApp personalizado (máx 280 chars, español argentino). Terminar con CTA que ofrezca demo de 15’ o piloto corto.
14. suggested_offer — propuesta mínima para presentar (ej. diagnóstico gratuito 30’, piloto 7 días)
15. next_action — accion recomendada (e.g. enviar WhatsApp, agendar demo)

## Formato de salida
- Guardar dos artefactos:
  - data/leadhunter-report-YYYY-MM-DD.md (Markdown legible: tabla resumen + detalle por lead)
  - data/leadhunter-report-YYYY-MM-DD.json (estructura con los campos arriba)

## Reglas operativas
- Exigir contacto_verified=true para contar el lead; si no, buscar reemplazo automáticamente.
- Priorizar leads con “suggested_offer” claro y decisor identificado.
- Registrar evidence_urls y un audit_trail por lead (qué señales se usaron, timestamp).
- Si global_pause=true, responder: "⏸️ LeadHunter en pausa global"
""".strip()


class LeadHunterAgent(BaseAgent):
    name = "leadhunter"
    description = "Genera 10 leads/día con contacto verificado (FIT 4-6)"
    schedule = "0 14 * * *"  # 14:00 ART diario
    timezone = "America/Buenos_Aires"
    max_tokens = 8000

    @property
    def system_prompt(self) -> str:
        return f"{get_context_block()}\n\n{LEADHUNTER_INSTRUCTIONS}"

    def build_user_message(self, ctx: AgentContext) -> str:
        tz = pytz.timezone("America/Buenos_Aires")
        today = datetime.now(tz).strftime("%Y-%m-%d")
        return (
            f"Fecha objetivo: {today}\n\n"
            "Generá los 10 leads de hoy siguiendo las instrucciones al pie de la letra. "
            "Empezá con la tabla resumen (empresa | fit | contacto) y después el detalle por lead. "
            "Recordá: el objetivo NO es velocidad, es CALIDAD de contacto."
        )

    def post_process(self, response_text: str, ctx: AgentContext) -> str:
        # Persistir en disco
        tz = pytz.timezone("America/Buenos_Aires")
        today = datetime.now(tz).strftime("%Y-%m-%d")
        data_dir = Path(__file__).resolve().parent.parent.parent / "data"
        data_dir.mkdir(exist_ok=True)

        leads_file = data_dir / f"leadhunter-leads-{today}.md"
        report_file = data_dir / f"leadhunter-report-{today}.md"

        # Extraer tabla simple (primeras líneas con |) si existe
        lines = response_text.splitlines()
        simple_lines = [ln for ln in lines if ln.strip().startswith("|") and "---" not in ln]
        simple = "\n".join(simple_lines[:15]) if simple_lines else response_text[:1500]

        leads_file.write_text(simple + "\n", encoding="utf-8")
        report_file.write_text(response_text, encoding="utf-8")
        return response_text
