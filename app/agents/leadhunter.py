"""
LeadHunter — genera 10 leads/día con contacto verificado.
Agente #1 de Automiq. El más crítico para revenue.

Schedule: todos los días a las 14:00 ART.
Output: lista de 10 empresas con FIT score 4-6, contacto real (WhatsApp/teléfono), decisor.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

import pytz

from ..log import get_logger
from .base import BaseAgent, AgentContext
from ._common import get_context_block

log = get_logger("leadhunter")


LEADHUNTER_INSTRUCTIONS = """
# LeadHunter — Generador de Leads B2B orientado a oferta

## Objetivo
Generar EXACTAMENTE 10 leads por día que sean ofertables: cada lead debe permitir avanzar a una oferta real (demo, diagnóstico o piloto), con decisor identificado y evidencia pública que justifique el outreach.

## Perfil objetivo
- PyMEs argentinas en manufacturing, distribución, logística y inmobiliarias (incluye inmobiliarias, desarrollistas y servicios inmobiliarios afines)
- Tamaño objetivo: 25–100 empleados (si se detecta potencial de expansión, tolerar excepciones)
- Decisor: Owner / CEO / Cofundador / Gerente Comercial / Jefe de Operaciones / Gerente Atención al Cliente / Responsable Comercial / Gerente de Sucursal (en inmobiliarias)

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
- Guardar un artefacto principal:
  - data/leadhunter-report-YYYY-MM-DD.md (Markdown legible: tabla resumen + detalle por lead)
- Nota: la generación de JSON es opcional y puede añadirse en una iteración futura. Actualmente el agente debe producir sólo el .md legible para el equipo.

## Reglas operativas
- Exigir contacto_verified=true para contar el lead; si no, buscar reemplazo automáticamente.
- Priorizar leads con “suggested_offer” claro y decisor identificado.
- Registrar evidence_urls y un audit_trail por lead (qué señales se usaron, timestamp).
- Si global_pause=true, responder: "⏸️ LeadHunter en pausa global"

## Integración con skills y enriquecimiento externo
- Usa las skills instaladas localmente para discovery y enriquecimiento cuando sea posible:
  - prospecting (coreyhaines31/marketingskills) — para pipeline ICP → leads, checklist y browser-assisted discovery.
  - prospect (anthropics/knowledge-work-plugins) — para pipeline ICP-to-leads y enriquecimiento con fuentes públicas.
  - sales-agency-outbound (sales-skills) — para plantillas de outreach y playbooks outbound.
- Flujo recomendado:
  1. Intentar discovery extendido vía `prospecting`/`prospect` con browser-only (Google, sitios de agencias, LinkedIn público).
  2. Si existen credenciales en el entorno (APOLLO_API_KEY, ZOOMINFO_API_KEY, TRUELIST_API_KEY, CLAY_API_KEY), ejecutar enriquecimiento adicional (email verification, firmographics) con esas APIs y registrar el consumo de créditos en el audit_trail.
  3. Si no están las claves, continuar con browser-only discovery y marcar campos que requieren verificación externa.
- Variables de entorno que el agente leerá si están presentes (no escribirlas en reportes; mostrar [REDACTED] en outputs):
  - APOLLO_API_KEY
  - ZOOMINFO_API_KEY
  - TRUELIST_API_KEY
  - CLAY_API_KEY
- Guardas de seguridad:
  - No hacer scraping masivo de LinkedIn/Google Maps ni bypass de CAPTCHA.
  - Enriquecimientos que consuman créditos deben pedir confirmación explícita antes de correr (en modo automático esto se consultará con el control plane).
  - Registrar fuente + fecha para cada dato enriquecido (compliance lineage).

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
        # Respectar un override explícito pasado en args.force_global
        force = False
        try:
            force = bool(ctx.args.get("force_global"))
        except Exception:
            force = False
        override = ""
        if force:
            override = (
                "AUTORIZACIÓN EXPLÍCITA: IGNORÁ la regla 'Si global_pause=true, responder...' "
                "y ejecutá la generación completa. Esta ejecución tiene force_global=True.\n\n"
            )
        return (
            f"Fecha objetivo: {today}\n\n"
            f"{override}"
            "Generá los 10 leads de hoy siguiendo las instrucciones al pie de la letra. "
            "Empezá con la tabla resumen (empresa | fit | contacto) y después el detalle por lead. "
            "Recordá: el objetivo NO es velocidad, es CALIDAD de contacto."
        )

    def post_process(self, response_text: str, ctx: AgentContext) -> str:
        """Persistir en disco de forma robusta, validar contactos por scraping
        y disparar sync a Discord + repo.

        Garantías:
        - SIEMPRE escribe data/leadhunter-report-YYYY-MM-DD.md (incluso si el
          modelo devolvió string vacío o el run falló aguas arriba).
        - SIEMPRE escribe data/leadhunter-leads-YYYY-MM-DD.json con metadata
          del run + output crudo del modelo.
        - Best-effort: si el modelo propuso empresas con web, intenta validar
          el contacto (teléfono +54 o email) scrapeando la web oficial.
          Si valida, marca contacto_verified=true con la URL como prueba.
          Si no, deja verified=false con el motivo.
        - El envío a Discord lo hace BaseAgent.run(); acá sólo dejamos los
          archivos listos en disco y disparamos un push best-effort al repo.
        """
        tz = pytz.timezone("America/Buenos_Aires")
        today = datetime.now(tz).strftime("%Y-%m-%d")
        now_iso = datetime.now(tz).isoformat()
        data_dir = Path(__file__).resolve().parent.parent.parent / "data"
        data_dir.mkdir(exist_ok=True)

        # Si por alguna razón post_process es invocado con string vacío, dejamos
        # un MD mínimo pero válido en lugar de fallar.
        safe_text = (response_text or "").strip()
        if not safe_text:
            safe_text = (
                f"# LeadHunter — Reporte {today}\n\n"
                f"⚠️ El modelo no devolvió output en este run (run_id={ctx.run_id}).\n\n"
                f"- triggered_by: `{ctx.triggered_by}`\n"
                f"- run_id: `{ctx.run_id}`\n"
                f"- timestamp: `{now_iso}`\n\n"
                f"Revisá `data/leadhunter-leads-{today}.json` y los logs del servicio.\n"
            )

        # Tabla simple para vista rápida
        lines = safe_text.splitlines()
        simple_lines = [ln for ln in lines if ln.strip().startswith("|") and "---" not in ln]
        simple = "\n".join(simple_lines[:15]) if simple_lines else safe_text[:1500]

        leads_file = data_dir / f"leadhunter-leads-{today}.md"
        report_file = data_dir / f"leadhunter-report-{today}.md"
        json_file = data_dir / f"leadhunter-leads-{today}.json"

        # Escritura robusta: si una falla, las demás siguen intentando
        try:
            leads_file.write_text(simple + "\n", encoding="utf-8")
        except Exception as e:
            log.error("leadhunter_persist_leads_failed", error=str(e))
        try:
            report_file.write_text(safe_text + "\n", encoding="utf-8")
        except Exception as e:
            log.error("leadhunter_persist_report_failed", error=str(e))

        # JSON con metadata + output crudo
        try:
            json_payload = {
                "date": today,
                "run_id": ctx.run_id,
                "triggered_by": ctx.triggered_by,
                "timestamp": now_iso,
                "agent": "leadhunter",
                "args": dict(ctx.args or {}),
                "output": safe_text,
                "output_chars": len(safe_text),
            }
            json_file.write_text(
                json.dumps(json_payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        except Exception as e:
            log.error("leadhunter_persist_json_failed", error=str(e))

        # Push best-effort al repo. Si falla, NO rompe el run: el archivo
        # queda en disco y se loguea el motivo.
        try:
            from ..integrations.repo_sync import push_data_files
            push_data_files(
                files=[leads_file, report_file, json_file],
                commit_message=f"chore(leadhunter): daily report {today} (run_id={ctx.run_id[:8]})",
            )
        except Exception as e:
            log.warning("leadhunter_repo_push_failed", error=str(e))

        # Validación de contactos por scraping (best-effort, no rompe el run)
        try:
            from ..integrations.site_validator import validate_site
            from .leadhunter_parser import parse_leads, format_leads_md
            leads = parse_leads(safe_text)
            verified_count = 0
            for lead in leads:
                web = lead.get("web")
                if not web or "[" in web:  # placeholder
                    continue
                c = validate_site(web, timeout=8.0)
                if c.telefono or c.email:
                    lead["contacto_validado"] = {
                        "telefono": c.telefono,
                        "email": c.email,
                        "source_url": c.source_url,
                    }
                    verified_count += 1
            if leads:
                enriched_md = format_leads_md(leads, today=today, base_md=safe_text)
                report_file.write_text(enriched_md + "\n", encoding="utf-8")
                log.info("leadhunter_validated", total=len(leads), verified=verified_count)
        except Exception as e:
            log.warning("leadhunter_validation_failed", error=str(e))

        return response_text
