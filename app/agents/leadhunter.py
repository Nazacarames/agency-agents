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
# LeadHunter — Generador de Leads B2B para Automiq

## Objetivo
Generar EXACTAMENTE 10 leads por día de PyMEs familiares argentinas en manufacturing,
distribución o logística (25-100 empleados) que tengan necesidad verificable de
automatización / WhatsApp business / CRM.

## Criterios de FIT score (1-6, solo incluir 4+)
- 6: Empresa familiar conocida, dolor explícito en LinkedIn/news, decisor identificado con contacto
- 5: Empresa del rubro correcto, dolor implícito, decisor identificable
- 4: Empresa del rubro, presencia online, contacto verificable

NO incluir FIT 1-3 (pierden el tiempo del equipo de ventas).

## Por cada lead incluir
1. **empresa**: razón social
2. **industria**: sub-rubro específico
3. **ubicación**: ciudad + provincia
4. **empleados**: rango estimado
5. **web**: URL (si tiene)
6. **fit_score**: 4-6 con justificación de 1 línea
7. **contacto**: WhatsApp con código de país (54 9 ...) O teléfono fijo
8. **decisor**: nombre + cargo (CEO, Dueño, Director Comercial, etc.)
9. **topic_opener**: primer mensaje WhatsApp personalizado (max 280 chars, en español argentino)

## Formato de salida
Markdown estructurado con tabla resumen + bloque por lead. NO incluyas "NO ENCONTRADO"
para contacto — si no hay WhatsApp real, descartá el lead y reemplazalo por otro.

## Instrucciones operativas
- Si global_pause=true en control.json, devolver: "⏸️ LeadHunter en pausa global"
- Persistir resultado en data/leadhunter-leads-{YYYY-MM-DD}.md (lista simple) Y
  data/leadhunter-report-{YYYY-MM-DD}.md (reporte completo)
- Si tenés que descartar un lead por falta de contacto, agregar otro — el target es 10 con contacto real
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
