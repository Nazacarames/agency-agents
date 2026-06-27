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
from typing import Any, Dict, List

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
- Tamaño objetivo: **25–100 empleados** (REGLA DURA, ver abajo). Tolerar hasta ~150 sólo si el resto del fit es excelente.
- Decisor: Owner / CEO / Cofundador / Gerente Comercial / Jefe de Operaciones / Gerente Atención al Cliente / Responsable Comercial / Gerente de Sucursal (en inmobiliarias)

## ⛔ FILTRO DE TAMAÑO — el más importante (leer dos veces)
El objetivo es la PyME chica/mediana DESCONOCIDA, NO la empresa grande famosa. El error
más común es listar marcas conocidas porque son fáciles de recordar — eso ARRUINA el lote.

**Heurística "si la conocés, descartala":** si vos (o un argentino promedio) reconocés la
marca, o es de capital nacional grande / multinacional / cotiza en bolsa / tiene >150
empleados / factura cientos de millones → **RECHAZAR y reemplazar**. No importa qué tan
buen contacto tenga.

**Ejemplos de lo que NUNCA debe aparecer** (grandes/famosas — sólo de muestra, NO es una
lista exhaustiva): Fate, Coto, Bagó, Andreani, Quilmes/CCU, Newsan, RE/MAX, Mercado Libre,
Arcor, Techint, Ledesma, Molinos, La Anónima, Galicia, YPF, Aluar, Loma Negra, Paladini,
Sancor, Mastellone/La Serenísima, Cervepar, Grupo Clarín, etc. Si dudás del tamaño, asumí
que es DEMASIADO grande y descartá.

**Cómo encontrar las correctas:** empresas regionales/locales poco conocidas, de un parque
industrial específico, de una cámara sectorial de una provincia, proveedores B2B de nicho,
distribuidores zonales, inmobiliarias de barrio/ciudad intermedia. Si el nombre no te suena
de nada, vas por buen camino.

## Señales que aumentan prioridad (buscar activamente)
- Publicaciones o posteos recientes en LinkedIn que indiquen problema/crecimiento
- Puestos abiertos relacionados a ventas, operaciones, atención al cliente
- Página de contacto con teléfono móvil o enlace wa.me / WhatsApp Business
- Uso público de herramientas CRM/WhatsApp/Shopify/Odoo/ERP
- Noticias/reviews que indiquen fricción operacional

## Exclusiones automáticas
- **Empresas grandes/conocidas** (ver FILTRO DE TAMAÑO arriba) → rechazo automático.
- Contactos exclusivos de RRHH o roles de selección sin responsabilidad comercial
- **Buzones de soporte masivo como ÚNICO contacto**: `sac@`, `atencion@`,
  `atencionalcliente@`, `clientes@`, `reclamos@`, `0800...`, formularios genéricos. Estos
  van a una mesa de soporte enorme, no a un decisor → NO sirven para vender. Un email así
  es señal de empresa grande (motivo extra para descartar). Si es el único contacto, BAJÁ
  el fit_score a ≤3 (no cuenta como lead) salvo que también consigas un contacto de decisor.
- Empresas sin presencia mínima online (web o LinkedIn) salvo excepciones justificadas

## Calidad de contacto (qué cuenta como bueno)
- IDEAL: nombre del decisor + su email directo o WhatsApp/celular.
- ACEPTABLE: email comercial chico tipo `ventas@`/`info@`/`comercial@` de una PyME real
  (no de una corporación) + teléfono verificado.
- NO ACEPTABLE como único contacto: buzón de soporte masivo (ver exclusiones).

## ⭐ RÚBRICA DE fit_score (dura — sólo entran los mejores)
Puntuá cada lead sumando (máx 6). **Sólo cuenta el lead si fit_score ≥ 4 Y contacto verificado.**
Si no llega a 4 → DESCARTALO y buscá reemplazo. Mejor 6 leads de 5/6 que 10 mediocres.
- **+2 Contactabilidad real:** decisor identificado + email directo o WhatsApp del decisor
  (NO un buzón masivo). Sin un canal a un decisor, el lead no sirve.
- **+2 Dolor concreto + evidencia:** hay un problema específico que Automiq resuelve
  (cotización lenta, no contestan WhatsApp a tiempo, seguimiento manual, cobranza…) y una
  señal pública que lo prueba. Dolor genérico = 0.
- **+1 Fit de tamaño/perfil:** PyME 25–100 empleados, regional/desconocida (no grande).
- **+1 Momento (timing):** posteo reciente, vacante de ventas/operaciones, stack
  (Tokko/Odoo/Shopify), o crecimiento que indique que AHORA es buen momento.

## 🧠 USÁ LO APRENDIDO (te lo paso en el mensaje del día)
- Si te paso **rubros que más convierten** (datos reales del pipeline): traé MÁS empresas de
  esos rubros — es donde mejor responde el mercado.
- Si te paso una lista de **empresas YA contactadas**: NO las repitas. El valor está en
  leads NETOS NUEVOS; repetir una empresa del pipeline es un lead desperdiciado.
- Aplicá las "Lecciones aprendidas" del contexto: son patrones que ya funcionaron o fallaron.

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
10b. email — email REAL de la empresa/decisor sacado del sitio oficial (página /contacto,
     pie de página, /quienes-somos). Es CLAVE: habilita el outbound automático por email.
     Si tras buscar en el sitio no hay ninguno, poné "(sin email público)" — pero buscalo
     siempre primero (la mayoría de las PyMEs publican un info@/ventas@/contacto@).
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
- Priorizar leads con "suggested_offer" claro y decisor identificado.
- Registrar evidence_urls y un audit_trail por lead (qué señales se usaron, timestamp).
- Si global_pause=true, responder: "⏸️ LeadHunter en pausa global"

## Prospección N3 (NUEVO — 2026-06-12, inspirado en Claudio Conde V1)
Cada lead generado tiene que estar en NIVEL 3 de prospección. NO generes mensajes
genéricos ni "personalización media". Para cada lead, incluir:

1. **Investigación profunda** del negocio:
   - Web oficial + al menos 2 URLs de evidencia (LinkedIn, IG, Google Maps, reviews)
   - Stack tech detectado (Tokko, Tango, Odoo, WooCommerce, Shopify, etc.)
   - Tamaño estimado (rango de empleados) con fuente
   - 1 dolor específico que el agente de IA podría resolver (cotización lenta, seguimiento
     de pedidos, cobranza, calificación de leads, etc.)
2. **3 números estimados de ROI** específicos para ese negocio:
   - Ejemplo: "2hs/día ahorradas = 50hs/mes = USD 600/mes de costo laboral recuperado"
   - Ejemplo: "30% más leads calificados = 15 leads extra/mes = USD 7500/mes en ventas"
   - Cada número tiene que tener un cálculo visible
3. **Outreach WhatsApp de 4 líneas** (estructura del pitch de Automiq):
   - Quién sos + para quién trabajás
   - Dolor específico de ESE negocio (no genérico)
   - Resultado + plazo + vehículo
   - CTA con horario concreto ("martes 10am o jueves 16pm, ¿cuándo te sirve?")
4. **discovery_signals DEBE incluir**: el post/video/comentario específico que referenciás
   en el outreach (esto es lo que diferencia N3 de N2)

## Estructura del output por lead (NUEVO)
```
### Lead N: [Empresa]
- Industria: [sub-rubro]   Ubicación: [ciudad, provincia]
- Empleados: [rango]   Web: [URL]
- Fit score: [4-6]/6  →  [1-line justification]
- Decisor: [Nombre + Cargo]   LinkedIn: [URL]
- Dolor específico detectado: [1 frase concreta]
- Stack tech: [lista corta]
- 3 números ROI estimados:
  1. [ahorro de horas/plata]
  2. [incremento de leads/ventas]
  3. [reducción de errores/morosidad]
- Outreach WhatsApp (N3, 4 líneas):
  > "[Mensaje completo acá]"
- Discovery signals: [URL 1] [URL 2] [URL 3]
- Suggested offer: [USD X setup + USD Y/mes]
- Next action: [enviar WhatsApp / agendar demo]
```

## Integración con skills y enriquecimiento externo
- Si en este entorno hay acceso a browser, skills de Claude Code (prospecting, prospect)
  o APIs (APOLLO_API_KEY, ZOOMINFO_API_KEY, TRUELIST_API_KEY, CLAY_API_KEY), usalas.
- Guardas: no hacer scraping masivo de LinkedIn/Google Maps ni bypass de CAPTCHA.

## Fallback obligatorio cuando no hay tools ni APIs disponibles
**IMPORTANTE**: Si no tenés acceso a browser, skills ni APIs de enriquecimiento:
- **NO devuelvas "no puedo"** ni un mensaje de error. Eso no es útil para el equipo.
- Generá los 10 leads usando datos de tu training, pero RESPETANDO EL FILTRO DE TAMAÑO:
  PyMEs chicas/medianas regionales (25–100 empleados), NO marcas grandes ni famosas. Si la
  única forma de completar el lote es metiendo una empresa conocida → NO la metas; mejor un
  perfil representativo de PyME de nicho (proveedor B2B zonal, distribuidor regional,
  fábrica mediana de un parque industrial) marcado como `[LIKELY: perfil_tipico_rubro]`.
- PROHIBIDO en fallback: listar empresas grandes/famosas para "rellenar" (Fate, Coto, Bagó,
  Andreani, Quilmes, Newsan, Arcor, etc.). Un perfil-tipo de PyME desconocida > una marca grande.
- Marcá cada campo con nivel de confianza:
  - `[VERIFIED: training_data]` si el dato figura en tu training con alta certeza
  - `[LIKELY: perfil_tipico_rubro]` si es inferencia razonable del sector
  - `[NEEDS VERIFICATION: buscar_en_sitio]` si necesita confirmación externa
- 1 lead con [NEEDS VERIFICATION] > 0 leads. SIEMPRE entregá el deliverable completo.
- Al inicio del reporte agregar: `⚠️ Run en modo offline (sin tools ni APIs externas)`

""".strip()


# Tools (formato Anthropic) que el agente puede invocar para correr ONLINE.
# Los ejecutores reales viven en packs/automiq/tools/.
LEADHUNTER_TOOLS = [
    {
        "name": "web_search",
        "description": (
            "Busca en la web (Google vía Serper, o DuckDuckGo como fallback). "
            "Usalo para DESCUBRIR PyMEs argentinas (manufacturing, distribución, "
            "logística, inmobiliarias), encontrar decisores, noticias, vacantes, "
            "y páginas de contacto. Devuelve [{title, url, snippet}]."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Consulta en español argentino"},
                "n": {"type": "integer", "description": "Cantidad de resultados (default 5)"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "scrape_url",
        "description": (
            "Descarga una URL y devuelve {title, text, links}. Usalo para LEER el "
            "sitio de una empresa, su página de contacto, o resultados de búsqueda, "
            "y confirmar rubro, tamaño, decisor y datos de contacto."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL completa con http(s)://"},
            },
            "required": ["url"],
        },
    },
    {
        "name": "validate_site",
        "description": (
            "Recorre home + páginas de contacto de un dominio y extrae email y "
            "teléfono argentino real (+54). Usalo para VERIFICAR el contacto de cada "
            "lead. Devuelve {telefono, email, source_url} o {error}."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "domain_or_url": {"type": "string", "description": "Dominio o URL de la empresa"},
            },
            "required": ["domain_or_url"],
        },
    },
]


class LeadHunterAgent(BaseAgent):
    name = "leadhunter"
    description = "Genera leads con contacto verificado (FIT 4-6) — Nivel N3"
    schedule = "0 14 * * *"  # 14:00 ART diario
    timezone = "America/Buenos_Aires"
    max_tokens = 8000
    max_tool_iterations = 8

    # Target de leads por corrida. Default 10 (pedido del usuario 2026-06-13:
    # reportes de 10 leads DIARIOS). Cada run de 10 vía Claude Code ≈ 20 min /
    # USD ~17 / quota-pesado. Bajable por corrida con args.target_leads.
    DEFAULT_TARGET_LEADS = 10

    # ── Claude Code (harness real con MiniMax) ──
    # Corre vía `claude -p` headless: usa la skill `prospecting` + WebFetch/Bash
    # para descubrir empresas en directorios y verificar contacto en cada sitio.
    # WebSearch NO se incluye: no funciona con backend MiniMax (400 server-side).
    use_claude_code = True
    claude_code_tools = ["WebFetch", "Bash", "Read", "Write", "Glob", "Grep", "Skill"]
    claude_code_timeout = 1800  # 30 min: Railway no hiberna, dejamos correr la prospección real
    # (vía Claude Code + WebFetch). El 720 viejo era para la ventana del free de Render.

    @property
    def tools(self):
        return LEADHUNTER_TOOLS

    @property
    def tool_executors(self):
        from packs.automiq.tools import web_search, scrape_url, validate_site
        return {
            "web_search": web_search,
            "scrape_url": scrape_url,
            "validate_site": validate_site,
        }

    @property
    def system_prompt(self) -> str:
        return f"{get_context_block()}\n\n{LEADHUNTER_INSTRUCTIONS}"

    def _learning_block(self, ctx: AgentContext) -> str:
        """Inyecta lo aprendido del pipeline: empresas YA contactadas (no repetir) +
        rubros que mejor convierten (priorizar). Hace al leadhunter mejor con el tiempo."""
        parts: List[str] = []  # type: ignore[name-defined]
        try:
            from ..integrations import leads_store as ls
            store = ls.load_store()
            known = ls.known_companies(store, limit=120)
            if known:
                parts.append(
                    "## ⛔ YA ESTÁN EN NUESTRO PIPELINE — NO LAS REPITAS (traé empresas NUEVAS)\n"
                    + ", ".join(known)
                )
            agg = ls.outcomes_by_industry(store)
            hot = sorted(
                ((i, a) for i, a in agg.items()
                 if i != "(sin rubro)" and a["contacted"] >= 3 and a["replied"] >= 1),
                key=lambda x: x[1]["replied"] / max(x[1]["contacted"], 1), reverse=True,
            )[:5]
            if hot:
                lines = [f"- {i}: respondió {a['replied']}/{a['contacted']}" for i, a in hot]
                parts.append(
                    "## 🔥 RUBROS QUE MÁS CONVIERTEN (datos reales — buscá MÁS de estos)\n"
                    + "\n".join(lines)
                )
        except Exception:
            pass
        return ("\n\n" + "\n\n".join(parts)) if parts else ""

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
        # Target configurable por corrida (default bajo para ahorrar cuota/tiempo).
        try:
            target = int(ctx.args.get("target_leads", self.DEFAULT_TARGET_LEADS))
        except Exception:
            target = self.DEFAULT_TARGET_LEADS
        target = max(1, min(target, 10))
        return (
            f"Fecha objetivo: {today}\n\n"
            f"{override}"
            f"⚠️ TARGET DE HOY: generá EXACTAMENTE {target} leads (esto OVERRIDE el "
            f"'EXACTAMENTE 10' del system prompt). Priorizá calidad de contacto verificable "
            f"sobre cantidad; con {target} leads sólidos alcanza."
            f"{self._learning_block(ctx)}\n\n"
            "Sos un agente de prospecting B2B corriendo en Claude Code. Cargá y seguí la "
            "skill `prospecting` (usá la tool Skill si está disponible).\n\n"
            "⚠️ NO tenés WebSearch (no funciona en este entorno). Descubrí empresas así:\n"
            "1. DESCUBRIMIENTO por directorios: usá WebFetch sobre directorios y guías "
            "sectoriales argentinas para listar empresas reales del rubro objetivo "
            "(manufactura, distribución, logística, inmobiliarias). Ejemplos de fuentes a "
            "fetchear: cámaras industriales por provincia, guías de parques industriales, "
            "Páginas Amarillas/Doradas AR por rubro+ciudad, asociaciones sectoriales, "
            "listados de proveedores. Extraé nombres de empresa + su web oficial.\n"
            "2. CALIFICACIÓN: con WebFetch abrí el sitio de cada candidata y confirmá rubro, "
            "tamaño aproximado (25–100 empleados) y decisor.\n"
            "3. VERIFICACIÓN de contacto: buscá en el sitio (home, /contacto, /quienes-somos, "
            "pie de página) DOS cosas: el teléfono argentino (+54) Y el email REAL de la empresa "
            "(info@/ventas@/contacto@…). El EMAIL es clave: habilita el envío automático del "
            "outbound — buscalo siempre. Si no encontrás NINGÚN contacto verificable, descartá la "
            "empresa y buscá otra. Podés usar Bash (curl) si WebFetch falla en un sitio.\n"
            f"4. Iterá hasta juntar {target} leads con contacto verificado en una fuente pública. "
            "Aplicá la rúbrica de fit de la skill (fit_score 4-6).\n"
            "⛔ FILTRO DE TAMAÑO (lo más importante): NADA de empresas grandes/famosas. Si "
            "reconocés la marca o tiene >150 empleados o cotiza en bolsa → DESCARTALA y buscá "
            "otra. El objetivo es la PyME chica/mediana DESCONOCIDA (25–100 emp). Antes de "
            "cerrar el lote, revisá cada empresa y sacá cualquiera que sea un nombre conocido "
            "(tipo Fate, Coto, Bagó, Andreani, Quilmes, Newsan, RE/MAX): esas son run fallido.\n\n"
            "⚠️ ENTREGABLE FINAL — REGLA DURA: tu respuesta final (lo que IMPRIMÍS) DEBE ser el "
            "reporte COMPLETO en Markdown. Prohibido responder sólo con un resumen de pocas líneas "
            "tipo 'Resumen final: 10 leads...': eso NO sirve y se considera run fallido. NO dejes el "
            "reporte únicamente en archivos de disco — IMPRIMILO entero como respuesta.\n"
            "El reporte impreso debe incluir, en este orden:\n"
            "1) tabla resumen con estas columnas EXACTAS: "
            "empresa | industria | fit | contacto +54 | email\n"
            "   (la columna email es OBLIGATORIA: poné el email real o '(sin email público)')\n"
            f"2) el detalle de los {target} leads, cada uno con TODOS los campos obligatorios del "
            "system prompt (estructura '### Lead N'), incluyendo la URL fuente de cada dato de "
            "contacto.\n"
            "El objetivo es CALIDAD de contacto verificable, no velocidad."
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
