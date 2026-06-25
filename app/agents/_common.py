"""
Common prompts y contexto compartido por todos los agentes de Automiq.

v3 (2026-06-12) — Actualizado con insights de:
- Claudio Conde (V1): "Especialización o muerte", "Prospección N3", "Empresa → Oferta → Tecnología"
- Visual Project (V2): "Big Domino de Russell Brunson", "Oferta call-friendly",
  "Ciberseguridad como diferenciador premium"

Cambios principales vs v2:
- Reglas de oro 1-5 reescritas con foco en resultado, no herramienta
- Nueva sección "Big Domino mindset" — todos los agentes piensan en términos
  de "ayudo a QUIÉN a LOGRAR QUÉ mediante CÓMO"
- Nueva sección "Prospección N3" — para outbound y lead gen
- Nueva sección "Empresa → Oferta → Tecnología" — el orden importa
- Sección de fallback "tools y datos" ampliada con el patrón [VERIFIED]/[LIKELY]/[NEEDS VERIFICATION]
"""

AGENCY_CONTEXT = """
# Automiq — Agencia de Automatización con IA

## Qué es
Automiq es una agencia de automatización con IA enfocada en:
- Empresas manufacturing, distribución, logística, inmobiliarias de LATAM y España
- PyMEs familiares (25-100 empleados) hispanohablantes que necesitan digitalizar procesos
- Mercados: Argentina (base/origen), México, Colombia, Chile, Perú, España, Uruguay y
  demás países hispanohablantes. Argentina es la casa matriz, pero NO el único mercado.
- Servicios: agentes de IA (WhatsApp/voice), automatizaciones n8n, landing pages, Meta Ads, CRM

## Web oficial
Sitio: https://automiq-landing-astro.vercel.app — es la referencia de marca, mensajes y
servicios. Usala como fuente y enlazala cuando un output necesite un link a Automiq.

## Big Domino (nuestra frase de oferta)
> *"Ayudo a [VERTICAL: distribuidoras/manufactureras/logísticas/inmobiliarias]
> argentinas de 25-100 empleados a [BENEFICIO MEDIBLE: recuperar cobranza /
> ahorrar horas / aumentar citas], mediante un agente de IA + automatizaciones
> conectadas a su WhatsApp/CRM/ERP."*

Detrás de este Big Domino hay un **mercado mínimo viable** (1 vertical) y un
**producto mínimo viable** (1 agente de IA que resuelve 1 problema concreto).
Cada agente que produces debe ayudar a vender / entregar / mejorar este Big Domino.

## Cliente target
PyMEs familiares argentinas, 25-100 empleados, dueñas de manufacturing / distribución
/ logística / inmobiliarias, que están digitalizadas parcialmente y necesitan escalar.

## Paquetes principales
1. **Esencial** (USD 300 setup + USD 100/mes) — 1 agente, 1 integración
2. **Profesional** (USD 500 setup + USD 200/mes) — 2-3 agentes, 2-3 integraciones, reporting
3. **Enterprise** (USD 800 setup + USD 300/mes) — 5+ agentes, integraciones custom,
   incluye auditoría de seguridad (diferenciador premium de Visual Project)

## Diferenciador
Combinamos implementación técnica (automatizaciones reales) con estrategia comercial
(copy, secuencias, contenido). No somos "la agencia de marketing" — somos "el brazo
técnico que ejecuta lo que otros recomiendan".

## Reglas de oro (v3)
1. SIEMPRE dar output concreto, no "voy a hacer" — entregar el resultado listo para usar
2. Pensá primero en el PROBLEMA del cliente, después en la solución, al final en la tecnología
   (orden: Empresa → Oferta → Tecnología)
3. Localización por país: WhatsApp es el canal primario en LATAM. Si la tarea apunta a
   un cliente, adaptá moneda, tratamiento (vos/tú/usted) y modismos al país de ESE cliente
   (se te inyecta un bloque "LOCALIZACIÓN" con los datos). Sin cliente, default Argentina
   (ARS, "vos"). Nunca asumas ARS/"vos" para clientes de otro país.
4. Si global_pause está activo, no ejecutar (sólo devolver mensaje de pausa)
5. Reportar errores inmediatamente, no simular éxito
6. IDIOMA: escribí TODO en español rioplatense. PROHIBIDO usar caracteres chinos,
   japoneses, coreanos o de cualquier alfabeto no latino. Si no sabés una palabra,
   usá la española (ej: "reciclaje", NO "回收"). Sólo se permiten letras latinas
   (con tildes/ñ), números, signos de puntuación y emojis.

## Sobre el uso de tools y datos
- Este entorno PUEDE tener estas tools registradas (según el agente): web_search,
  scrape_url, validate_site, notify_discord. Si las tenés disponibles, USALAS.
- Si una tool no responde o falla, marcalá como `[TOOL FAIL: <motivo>]` y seguí.
- Si NO tenés tool disponible para una tarea, NO devuelvas "no puedo" como output final.
  En cambio, generá el deliverable con **datos públicos de tu training** (empresas
  argentinas conocidas, rubros típicos, estructuras de costo razonables) y marcá
  explícitamente cada campo con su nivel de confianza:
    - `[VERIFIED: <fuente>]` si lo confirmaste con una tool
    - `[LIKELY: <razonamiento>]` si es inferencia razonable
    - `[NEEDS VERIFICATION: <qué chequear>]` si es placeholder/inventado
- 1 lead con [NEEDS VERIFICATION] > 0 leads. SIEMPRE entregá el deliverable completo.
- El MD/JSON de salida es lo que el equipo operativo va a usar. Tiene que ser
  accionable, aunque sea parcial.

## Prospección N3 (cuando generes outreach)
Cuando produzcas mensajes de outbound, propuestas o secuencias de venta, aplicá el
patrón de **nivel 3** (Claudio Conde):
- **N1 genérico** ("Hola, soy Pepito, podemos ayudarte con X") → NO USES
- **N2 scrape + personalización media** ("Vi tu negocio, podemos hacer X") → QUEMADO, no uses
- **N3 investigación profunda** (refiere a un post / video / comentario específico del
  prospecto, menciona un problema concreto de su negocio, incluí 3 números de ROI
  estimados) → USÁ ESTE

1 mensaje de N3 al día > 100 mensajes de N2.

## Empresa → Oferta → Tecnología (orden de pensamiento)
Para cualquier entregable:
1. **Empresa**: ¿qué problema de fondo tiene el cliente? (no "le falta IA", sí
   "pierde 2 horas/día respondiendo WhatsApp")
2. **Oferta**: ¿qué producto/servicio resuelve ese problema de forma medible?
   (agente WhatsApp + integración ERP)
3. **Tecnología**: solo al final, la herramienta concreta (n8n, MiniMax-M3, etc.)

El output debe priorizar el paso 1 y 2. La tecnología es opcional y al final.

## Ciberseguridad como diferenciador premium
(Inspirado en Visual Project V2)
Para clientes Enterprise o cuando se tocan datos sensibles (banca, salud, etc.),
incluí en el output consideraciones de:
- Encriptación de datos en tránsito y reposo
- Roles y permisos (RBAC)
- Auditoría de quién accedió a qué
- Compliance (Ley 25.326 de protección de datos personales en Argentina)

Esto nos separa de las 95% de agencias que no lo tienen.
""".strip()


def get_context_block() -> str:
    """Bloque de contexto que se prepende a todos los prompts de agentes."""
    from datetime import datetime
    import pytz

    tz = pytz.timezone("America/Buenos_Aires")
    now = datetime.now(tz).strftime("%Y-%m-%d %H:%M %Z")
    return f"{AGENCY_CONTEXT}\n\n---\nFecha actual: {now}\n---\n"


# Web oficial de Automiq — los agentes que producen copy/estrategia DEBEN basarse
# en el sitio real, no en supuestos. (web_auditor y seo_specialist ya la fetchean
# de forma explícita; este directive es para los demás de marketing.)
OFFICIAL_SITE_URL = "https://automiq-landing-astro.vercel.app"


def official_site_directive() -> str:
    """Instrucción para que el agente lea la web oficial antes de producir."""
    return (
        f"\n\nIMPORTANTE: ANTES de generar, hacé WebFetch de la web oficial de Automiq "
        f"({OFFICIAL_SITE_URL}) y basá tu output en la oferta, los servicios, los mensajes "
        f"y el tono REALES del sitio. No inventes el posicionamiento ni uses uno genérico. "
        f"Si la web no carga, decilo y seguí con el contexto de la agencia."
    )


def _ad_library_url(country_code: str = "AR", query: str = "") -> str:
    """URL de la Biblioteca de Anuncios de Meta para un país + término."""
    from urllib.parse import quote
    cc = (country_code or "AR").upper()
    q = quote(query or "")
    return (f"https://www.facebook.com/ads/library/?active_status=all&ad_type=all"
            f"&country={cc}&q={q}&media_type=all")


def competitor_visual_directive(vertical: str = "", country: str = "", country_code: str = "AR") -> str:
    """Hace que el agente estudie la competencia ANTES de diseñar las imágenes —usando
    la Biblioteca de Anuncios de Meta como fuente principal— para que la dirección de
    arte sea diferenciada, VARIADA y basada en lo que la competencia realmente corre."""
    foco = []
    if vertical:
        foco.append(f"vertical «{vertical}»")
    if country:
        foco.append(f"país «{country}»")
    foco_txt = (" (foco: " + ", ".join(foco) + ")") if foco else ""
    ad_url = _ad_library_url(country_code, vertical or "automatizacion IA marketing")
    return (
        "\n\nESTUDIO DE COMPETENCIA EN LA BIBLIOTECA DE ANUNCIOS (obligatorio, ANTES de las imágenes)"
        + foco_txt + ":\n"
        "FUENTE PRINCIPAL — la **Biblioteca de Anuncios de Meta** (Meta Ad Library), que muestra los "
        "anuncios REALES que la competencia está corriendo ahora en IG/FB. Abrila con WebFetch/WebSearch:\n"
        f"  {ad_url}\n"
        "Cambiá el `q=` por 2-3 competidores reales o términos del rubro/país. Si la página no renderiza, "
        "buscá igual con WebSearch (\"<competidor> meta ad library\", \"<rubro> ads instagram <país>\") y "
        "mirá sus perfiles de IG/landing. Analizá los CREATIVOS de esos anuncios y anotá en la sección "
        "«Estudio de competencia» de tu output (4-6 líneas):\n"
        "- El RANGO de formatos/estilos que usan (foto UGC, testimonio con screenshot, before/after, "
        "tipográfico audaz, 3D producto, captura de chat, data-viz, carrusel, etc.).\n"
        "- Los CLICHÉS que repiten todos y hay que EVITAR (stock 3D azul genérico, robots sonrientes, "
        "'businessman con laptop', cerebros con circuitos).\n"
        "- La dirección de arte diferenciada de Automiq que se despega de eso.\n"
        "VARIEDAD OBLIGATORIA: NO todas las imágenes pueden ser del mismo tipo. Asigná a CADA pieza un "
        "formato/estilo DISTINTO de los que viste funcionando en la biblioteca (rotá entre foto editorial, "
        "tipográfico, UGC/testimonio, captura de chat de WhatsApp, before/after, 3D, ilustración con "
        "textura…). Esa decisión por-pieza tiene que reflejarse en cada prompt `IMAGEN:` de abajo."
    )


def competitor_visual_directive_for(ctx) -> str:
    """Igual que competitor_visual_directive pero toma vertical/país del cliente
    objetivo (si la tarea apunta a uno) para enfocar la investigación y la Ad Library."""
    vertical = country = ""
    country_code = "AR"
    try:
        args = getattr(ctx, "args", None) or {}
        cid = args.get("client_id") if isinstance(args, dict) else None
        if cid:
            from ..integrations import clients_store as cs, localization as loc
            c = cs.get_client(cid)
            if c:
                vertical = c.get("vertical") or ""
                country = loc.label(c.get("country"))
                country_code = loc.normalize(c.get("country"))
    except Exception:
        pass
    return competitor_visual_directive(vertical, country, country_code)


def image_prompt_directive() -> str:
    """Pide al agente de contenido que incluya prompts de imagen + el texto del cartel."""
    return (
        "\n\nIMÁGENES (obligatorio): la cantidad la decidís VOS según tu planificación "
        "(1 por idea / 1 por post clave). No te limites a un número fijo. "
        "Por cada pieza agregá una línea que empiece EXACTO con `IMAGEN:` así:\n"
        "`IMAGEN: <prompt EN INGLÉS del fondo> | TEXTO: <titular corto en español> | SUBTEXTO: <bajada opcional> | CAPTION: <caption COMPLETO del post, en español, con hook + cuerpo + CTA + hashtags>`\n"
        "El CAPTION es lo que se PUBLICA de verdad en Instagram/Facebook, así que tiene que ser el "
        "copy final listo para postear (no un resumen). Si no ponés CAPTION, se publica con el TEXTO + SUBTEXTO.\n"
        "ARTE (clave para que NO salgan genéricas): el <prompt> tiene que ser ESPECÍFICO y basado "
        "en tu estudio de competencia. Describí un SUJETO y una ESCENA concreta del vertical/país real "
        "(no abstracciones tipo 'businessman with laptop'), con estilo, composición, luz y mood "
        "definidos. VARIÁ el estilo entre piezas (foto editorial, 3D render, ilustración con textura, "
        "collage, isométrico…) — NO repitas el mismo 'flat vector, navy and royal blue, clean modern' "
        "en todas. La paleta navy + royal blue de Automiq es el ancla de marca (usala como acento), "
        "pero la dirección de arte tiene que diferenciarse de los clichés que viste. SIN texto dentro "
        "de la imagen (el sistema compone el <TEXTO> con tipografía real, máx ~5 palabras). "
        "Ej específico: `IMAGEN: editorial photo, close-up of a warehouse manager in Monterrey checking "
        "a phone with WhatsApp order confirmations, warm morning light, shallow depth of field, navy and "
        "royal blue accents on signage, cinematic | TEXTO: Pedidos que se cierran solos | SUBTEXTO: "
        "WhatsApp + IA`. El sistema genera la imagen y le compone el texto exacto."
    )


# ── Auto-generación de imágenes para contenido ───────────────────────────────
def _clean_fragment(s: str):
    """Saca backticks/asteriscos/comillas/espacios que el modelo deja alrededor."""
    return (s or "").strip().strip("`*\"' |").strip()


def _parse_image_line(line: str):
    """`<prompt> | TEXTO: <titular> | SUBTEXTO: <bajada> | CAPTION: <post>` →
    (prompt, texto, subtexto, caption). Los campos labelados pueden venir en
    cualquier orden; el prompt es todo lo que va antes del primer `|`.
    Tolera que el modelo envuelva la línea en backticks/asteriscos de markdown."""
    import re

    def _grab(label: str):
        # captura el valor del campo hasta el próximo campo conocido o el fin de línea
        m = re.search(
            rf"\|\s*{label}\s*[:：]\s*(.+?)(?=\s*\|\s*(?:TEXTO|SUBTEXTO|CAPTION)\s*[:：]|$)",
            line, re.IGNORECASE | re.DOTALL)
        return _clean_fragment(m.group(1)) or None if m else None

    texto = _grab("TEXTO")
    sub = _grab("SUBTEXTO")
    caption = _grab("CAPTION")
    prompt = line.split("|", 1)[0]
    return _clean_fragment(prompt), texto, sub, caption


def _publish_summary(res: dict) -> str:
    """Formatea el resultado de social_publish.publish para anexar al reporte."""
    parts = []
    for net, r in (res.get("results") or {}).items():
        label = "Instagram" if net == "instagram" else "Facebook"
        if r.get("ok"):
            pid = r.get("id") or ""
            if net == "facebook" and pid:
                parts.append(f"✅ {label} → https://www.facebook.com/{pid}")
            else:
                parts.append(f"✅ {label} (id `{pid}`)")
        else:
            parts.append(f"❌ {label}: {str(r.get('error',''))[:140]}")
    return ("> **📤 Publicado:** " + " · ".join(parts)) if parts else ""


def augment_with_images(text: str, max_images: int = 2, publish: bool = False) -> str:
    """Busca líneas `IMAGEN: <prompt> | TEXTO: <titular> | SUBTEXTO: <bajada> | CAPTION: <post>`,
    genera las imágenes (fondo MiniMax + texto compuesto con Pillow), anexa la sección y
    —si `publish` y hay tokens Meta— ENCOLA cada imagen para publicarse en IG/FB.
    NO publica inline: encola en publish_queue y un job diario drena 1 sola por día
    (regla del usuario: como mucho 1 publicación por día). Best-effort."""
    import re
    # Tolera que el modelo escriba la línea envuelta en markdown:
    # `` `IMAGEN: ...` ``, ``- IMAGEN: ...``, ``**IMAGEN:** ...`` o ``> IMAGEN: ...``.
    pat = re.compile(r"^[\s>*`\-]*(?:IMAGEN|PROMPT DE IMAGEN|VISUAL SUGERIDO)\s*[:：]\s*(.+)$",
                     re.IGNORECASE | re.MULTILINE)
    try:
        from ..integrations import image_gen
        if not text or not image_gen.enabled():
            return text
        # Parsear todas y descartar las vacías (p.ej. el label suelto `**IMAGEN:**`)
        parsed = []
        for raw in pat.findall(text):
            prompt, texto, sub, caption = _parse_image_line(raw.strip())
            if len(prompt) >= 8:           # un prompt real, no un label vacío
                parsed.append((prompt, texto, sub, caption))
        parsed = parsed[:max_images]
        if not parsed:
            return text
        # ¿Encolamos para publicar? Sólo si nos lo piden Y hay tokens configurados.
        pq = None
        targets = []
        source = ""
        if publish:
            try:
                from ..integrations import social_publish as sp_mod, publish_queue as pq_mod
                from ..config import get_settings
                if sp_mod.enabled():
                    pq = pq_mod
                    targets = get_settings().social_targets_list() or ["instagram", "facebook"]
            except Exception:
                pq = None
        blocks = []
        for i, (prompt, texto, sub, caption) in enumerate(parsed, 1):
            urls = image_gen.generate_image(prompt, aspect_ratio="1:1", n=1, text=texto, subtitle=sub)
            if not urls:
                continue
            cap = texto or prompt[:90]
            block = f"**Imagen {i}** — _{cap}_\n\n![imagen {i}]({urls[0]})"
            if pq:
                post_caption = caption or "\n\n".join(x for x in (texto, sub) if x) or ""
                try:
                    item = pq.enqueue(urls[0], post_caption, targets, source="content")
                    if item:
                        block += "\n\n> 🗓️ Encolado para publicación (se publica máx 1 por día)."
                    else:
                        block += "\n\n> ⚠️ Cola de publicación llena: no se encoló (revisá el panel)."
                except Exception as e:
                    block += f"\n\n> ⚠️ No se pudo encolar: {str(e)[:140]}"
            blocks.append(block)
        if not blocks:
            return text
        titulo = "## 🎨 Imágenes generadas" + (" (encoladas para publicar 1/día)" if pq else "")
        return text.rstrip() + "\n\n---\n\n" + titulo + "\n\n" + "\n\n".join(blocks) + "\n"
    except Exception:
        return text


# ── Sanitización de output del modelo ────────────────────────────────────────
# MiniMax (backend de los agentes) a veces "code-switchea" e inyecta caracteres
# CJK (chino/japonés/coreano) en medio del texto español, p.ej. "Logística de回收".
# Esto puede terminar en un cold-email real. Los limpiamos en un solo lugar
# (base.run, sobre el texto final) para que cubra reportes y emails de todos los
# agentes. Los emojis viven en planos altos (fuera de estos rangos) → se preservan.
import re as _re

_CJK_RE = _re.compile(
    "["
    "　-〿"   # puntuación/símbolos CJK
    "぀-ヿ"   # Hiragana + Katakana (japonés)
    "㐀-䶿"   # CJK Ext. A
    "一-鿿"   # CJK unificado (chino)
    "가-힯"   # Hangul (coreano)
    "豈-﫿"   # ideogramas de compatibilidad CJK
    "＀-￯"   # formas fullwidth/halfwidth
    "]+"
)


def sanitize_model_text(text: str) -> tuple:
    """Quita caracteres CJK que el modelo a veces inyecta y limpia el hueco.

    Devuelve (texto_limpio, cantidad_de_chars_removidos). Preserva emojis,
    tildes/ñ y la estructura markdown (sólo colapsa espacios sobrantes que deja
    el char removido; NO toca saltos de línea).
    """
    if not text:
        return text, 0
    removed = sum(len(m) for m in _CJK_RE.findall(text))
    if not removed:
        return text, 0
    cleaned = _CJK_RE.sub("", text)
    # El char removido suele dejar " X /" → "  /" o " ," → limpiamos artefactos
    # conservadores: 2+ espacios/tabs a uno, y espacio antes de puntuación.
    cleaned = _re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = _re.sub(r" +([,.;:!?])", r"\1", cleaned)
    return cleaned, removed


# ── Handoff entre agentes (sinergia / pipeline) ──────────────────────────────
# Cada agente persiste su entregable en data/<agent>-<kind>-YYYY-MM-DD.{md,json}
# (post_process en base.py). Estos helpers permiten que un agente downstream lea
# el output más reciente de un agente upstream y lo use como insumo. Así los
# agentes "se potencian entre sí": web_auditor detecta dolores → outbound los
# usa para personalizar los cold-emails; etc.

def _data_dir():
    from pathlib import Path
    return Path(__file__).resolve().parent.parent.parent / "data"


def read_latest_artifact(*agent_names: str, max_chars: int = 6000):
    """Devuelve (agent, path, texto) del artefacto .md más reciente que matchee
    alguno de los `agent_names` (busca `data/<agent>-*.md`, p.ej.
    `web-auditor-report-2026-06-12.md`). Devuelve (None, None, "") si no hay
    ninguno (disco efímero / todavía no corrió). El texto se trunca a max_chars
    para no inflar el prompt — el agente downstream sólo necesita los dolores
    /señales clave, no el informe entero."""
    data = _data_dir()
    best = None  # (mtime, agent, path)
    try:
        if not data.exists():
            return (None, None, "")
        for name in agent_names:
            slug = name.replace("_", "-")
            for p in data.glob(f"{slug}-*.md"):
                mt = p.stat().st_mtime
                if best is None or mt > best[0]:
                    best = (mt, name, p)
    except Exception:
        return (None, None, "")
    if best is None:
        return (None, None, "")
    try:
        txt = best[2].read_text(encoding="utf-8", errors="replace")
    except Exception:
        return (None, None, "")
    if len(txt) > max_chars:
        txt = txt[:max_chars] + "\n…[truncado]"
    return (best[1], str(best[2]), txt)


def upstream_handoff_block(*agent_names: str, titulo: str = "Insumo de un agente upstream",
                           max_chars: int = 6000) -> str:
    """Bloque listo para pegar en build_user_message: si hay output reciente de
    algún agente upstream, lo devuelve formateado; si no, devuelve "" (el agente
    downstream sigue funcionando solo, con su fallback). Robusto a disco efímero."""
    agent, path, txt = read_latest_artifact(*agent_names, max_chars=max_chars)
    if not txt:
        return ""
    return (
        f"\n\n---\n## {titulo} (`{agent}`)\n"
        f"_Fuente: {path}_\n\n"
        f"{txt}\n---\n"
        "USÁ este material como insumo real: anclá tu entregable en los datos/dolores "
        "concretos de arriba (personalización N3), no en generalidades.\n"
    )
