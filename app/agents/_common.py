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
- Empresas manufacturing, distribución, logística, inmobiliarias en Argentina
- PyMEs familiares (25-100 empleados) que necesitan digitalizar procesos
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
3. Datos argentinos: WhatsApp como canal primario, ARS como moneda, "vos" como tratamiento
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


def image_prompt_directive() -> str:
    """Pide al agente de contenido que incluya prompts de imagen + el texto del cartel."""
    return (
        "\n\nIMÁGENES (obligatorio): la cantidad de imágenes la decidís VOS según tu "
        "planificación — generá UNA imagen por cada pieza que planifiques (1 por idea, o "
        "1 por cada post/día clave del calendario). No te limites a un número fijo: si el "
        "plan tiene 5 posts con visual, son 5 imágenes; si tiene 2, son 2. "
        "Por cada pieza, agregá una línea que empiece EXACTO "
        "con `IMAGEN:` con este formato:\n"
        "`IMAGEN: <prompt EN INGLÉS del fondo> | TEXTO: <titular corto en español> | SUBTEXTO: <bajada opcional>`\n"
        "El <prompt> describe el FONDO/ilustración (estilo, escena, paleta navy + royal blue de "
        "Automiq, SIN texto dentro). El <TEXTO> es el titular que se compone encima con tipografía "
        "real (máx ~5 palabras, contundente). SUBTEXTO es opcional (una línea). "
        "Ej: `IMAGEN: flat vector illustration of a WhatsApp chatbot for an Argentine distributor, "
        "navy and royal blue palette, clean modern, no text | TEXTO: Cobrá sin perseguir a nadie | "
        "SUBTEXTO: WhatsApp + IA 24/7`. El sistema genera la imagen y le pone el texto exacto."
    )


# ── Auto-generación de imágenes para contenido ───────────────────────────────
def _parse_image_line(line: str):
    """`<prompt> | TEXTO: <titular> | SUBTEXTO: <bajada>` → (prompt, texto, subtexto)."""
    import re
    prompt, texto, sub = line, None, None
    m = re.search(r"\|\s*SUBTEXTO\s*:\s*(.+)$", prompt, re.IGNORECASE)
    if m:
        sub = m.group(1).strip(); prompt = prompt[:m.start()]
    m = re.search(r"\|\s*TEXTO\s*:\s*(.+)$", prompt, re.IGNORECASE)
    if m:
        texto = m.group(1).strip(); prompt = prompt[:m.start()]
    return prompt.strip(" |"), texto, sub


def augment_with_images(text: str, max_images: int = 2) -> str:
    """Busca líneas `IMAGEN: <prompt> | TEXTO: <titular> | SUBTEXTO: <bajada>`, genera
    las imágenes (fondo MiniMax + texto compuesto con Pillow) y anexa la sección.
    Best-effort."""
    import re
    pat = re.compile(r"^\s*(?:IMAGEN|PROMPT DE IMAGEN|VISUAL SUGERIDO)\s*:\s*(.+)$",
                     re.IGNORECASE | re.MULTILINE)
    try:
        from ..integrations import image_gen
        if not text or not image_gen.enabled():
            return text
        raw_lines = pat.findall(text)[:max_images]
        if not raw_lines:
            return text
        blocks = []
        for i, line in enumerate(raw_lines, 1):
            prompt, texto, sub = _parse_image_line(line.strip())
            urls = image_gen.generate_image(prompt, aspect_ratio="1:1", n=1, text=texto, subtitle=sub)
            if urls:
                cap = texto or prompt[:90]
                blocks.append(f"**Imagen {i}** — _{cap}_\n\n![imagen {i}]({urls[0]})")
        if not blocks:
            return text
        return text.rstrip() + "\n\n---\n\n## 🎨 Imágenes generadas\n\n" + "\n\n".join(blocks) + "\n"
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
