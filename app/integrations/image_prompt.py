"""
image_prompt — refina el prompt de imagen ANTES de generarla, con el know-how del
subagente `image-prompt-engineer` (que no corre en completion directa / sin Claude Code).

El agente de contenido escribe una idea cruda de imagen; acá un LLM la convierte en un
prompt FOTOGRÁFICO estructurado (sujeto, entorno, luz, cámara/lente, estilo) para Imagen 4,
respetando las reglas de Automiq (escena real de distribuidora argentina, sin texto/UI en
la imagen, aire para el titular, paleta navy como acento). Best-effort: si falla, devuelve
el prompt crudo. Preferentemente GLM (NVIDIA); fallback MiniMax.
"""
from __future__ import annotations

import re

from ..config import get_settings
from ..log import get_logger

log = get_logger("image_prompt")

_SYSTEM = (
    "Sos un Image Prompt Engineer experto en fotografía para generación con IA (Google "
    "Imagen 4). Trabajás para Automiq, una agencia ARGENTINA de automatización con IA para "
    "distribuidoras y PyMEs. Recibís una idea de imagen CRUDA y la reescribís en UN prompt "
    "fotográfico profesional EN INGLÉS, estructurado por capas: sujeto (una persona o escena "
    "CONCRETA y real del rubro argentino), entorno, ILUMINACIÓN con terminología real "
    "(golden hour, soft window light, Rembrandt, f/1.8 shallow depth of field), cámara y "
    "lente (35/50/85mm, ángulo, DOF), estilo (editorial/documentary, film emulation tipo "
    "Kodak Portra 400, color grade) y mood.\n\n"
    "REGLAS DURAS:\n"
    "1. Escena FOTORREALISTA, ESPECÍFICA y CREÍBLE del mundo PyME argentino — pero VARIADA: "
    "respetá el lugar/sujeto/hora que trae la idea cruda (una calle de barrio, un mostrador, "
    "la casa del dueño a la noche, un bar, la camioneta, el depósito). NO conviertas todas "
    "las ideas en 'persona en un depósito': si la idea propone otra escena, otra luz u otro "
    "protagonista (un objeto, un lugar vacío, una situación con humor), ANDÁ AHÍ. Lo único "
    "prohibido es lo genérico: abstracciones ('businessman with laptop'), fondos de estudio, "
    "y clichés de IA (robots, cerebros con circuitos, hologramas, manos tocando pantallas "
    "flotantes, render 3D azul genérico).\n"
    "2. PROHIBIDO texto, letras, números, logos, UI, capturas de chat, dashboards, gráficos o "
    "carteles DENTRO de la imagen (el titular se compone aparte por encima).\n"
    "3. ESTRUCTURA DEL PROMPT: EMPEZÁ describiendo EL LUGAR (el galpón lleno de cajones, el "
    "depósito, la calle) y recién DESPUÉS meté a la persona INTEGRADA en él. Plano ENTERO o "
    "3/4 (full-body / three-quarter environmental shot): la persona NO ocupa todo el cuadro, "
    "se ve el entorno real alrededor y detrás. PROHIBIDO 'studio', 'seamless backdrop', "
    "'plain background', 'portrait', primer plano de cara, o fondo de estudio. La cara nunca "
    "en el centro exacto; dejá aire en el borde inferior (piso/cajones) para una banda de texto.\n"
    "4. La paleta navy + royal blue de Automiq va como ACENTO dentro de la escena real "
    "(una remera, un detalle, la luz), NO como fondo plano de color.\n"
    "5. Gente argentina real y creíble para el rubro (no modelos de stock genéricos), con "
    "ROPA DE TRABAJO LISA y SIN logos de marcas ajenas (nada de North Face, Nike, etc.). "
    "VARIÁ LAS PERSONAS entre piezas: dueñas mujeres, repartidores jóvenes, parejas de "
    "socios, un cliente en el mostrador — PROHIBIDO que el protagonista sea siempre 'hombre "
    "de mediana edad con barba mirando el celular'.\n"
    "6. LA PERSONA SIEMPRE HACIENDO UNA ACCIÓN FÍSICA concreta del trabajo (cargando cajones "
    "en la camioneta, apilando mercadería, manejando el autoelevador, revisando stock con una "
    "tablet entre las estanterías, empujando un carro). PROHIBIDAS las poses pasivas de retrato "
    "(sonreír a cámara, estar parado quieto, mirar el celular sin hacer nada): esas hacen que el "
    "modelo se vaya a un headshot de estudio. La acción es lo que mantiene el entorno real.\n\n"
    "ESTRUCTURÁ el prompt final EN INGLÉS siguiendo esta plantilla (sin los corchetes):\n"
    "[TIPO: editorial photo / lifestyle photo] of [SUJETO detallado], [ACCIÓN física concreta].\n"
    "Setting: [el lugar real del rubro, protagónico].\n"
    "Style: [estética + paleta; navy/royal blue como acento].\n"
    "Lighting: [luz real, ej. warm natural window light].\n"
    "Camera: [encuadre entero/3-4], shot on [35/50mm, DOF].\n"
    "Composition: negative space at the bottom for a text overlay, designed for [1:1 / 9:16].\n"
    "Mood: [sensación].\n"
    "No text, no watermarks, no logos.\n"
    "Devolvé SOLO ese prompt estructurado, sin comillas ni explicaciones ni la palabra 'Prompt:'."
)


# Sistema alternativo para estilos GRÁFICOS (banner/tipográfico/ilustración/3D/minimal):
# acá NO se fuerza la escena fotorrealista de depósito — se pide una pieza de DISEÑO.
# Mantiene las reglas comunes: inglés, sin texto (lo compone Pillow), navy como acento,
# aire para el titular, especificidad del rubro (distribuidoras/PyMEs argentinas).
_SYSTEM_GRAPHIC = (
    "Sos un Art Director + Image Prompt Engineer experto en creativos de publicidad "
    "(generación con IA). Trabajás para Automiq, agencia ARGENTINA de automatización con "
    "IA para distribuidoras y PyMEs. Recibís una idea CRUDA y un ESTILO, y la reescribís "
    "en UN prompt EN INGLÉS para una pieza de DISEÑO/AD de ese estilo (no una foto "
    "documental), estructurado: sujeto/concepto, composición, paleta, estilo de render, "
    "mood.\n\n"
    "REGLAS DURAS:\n"
    "1. RESPETÁ el ESTILO pedido — es una pieza de diseño, no una foto de depósito.\n"
    "2. PROHIBIDO texto, letras, números, logos, UI, capturas, dashboards o carteles "
    "DENTRO de la imagen (el titular se compone aparte por encima). Pedí explícitamente "
    "'no text, no letters, no numbers, no UI'.\n"
    "3. Composición con NEGATIVE SPACE claro para un titular (bordes superior o inferior).\n"
    "4. Paleta ancla: navy (#0F1B33) + royal blue (#2563EB) — puede ser protagonista en "
    "estas piezas gráficas (a diferencia de las fotos), pero con UN acento cálido de "
    "contraste si suma.\n"
    "5. NADA de clichés de IA: robots, cerebros con circuitos, hologramas, manos tocando "
    "pantallas flotantes, 3D azul corporativo genérico.\n"
    "6. El concepto tiene que oler al RUBRO real (cajones, pallets, camioneta de reparto, "
    "mostrador, WhatsApp/chat como idea — nunca como UI legible), no a stock genérico.\n"
    "Devolvé SOLO el prompt final en inglés, sin comillas ni explicaciones."
)

# Estilos GRÁFICOS (rotación anti-monotonía, estudio 2026-07-06: ugly ads, tipografía
# como héroe, estático minimal como pattern-interrupt, ilustración con carácter).
_GRAPHIC_MODES = {
    "banner": (
        "ESTILO BANNER DE AD: composición gráfica publicitaria premium — un producto/objeto "
        "del rubro como héroe (cajón de mercadería, celular, camioneta en miniatura) o un "
        "fondo potente, iluminación de estudio dramática o color block, gran espacio limpio "
        "para el titular. Bold, alto contraste, brand-forward."
    ),
    "tipografico": (
        "ESTILO TIPOGRÁFICO: el FONDO es la pieza — color block plano o gradiente audaz "
        "(navy→royal blue, o un color inesperado de contraste), quizás con una textura "
        "sutil (grano, papel) o UNA forma geométrica/objeto chico como acento. Composición "
        "casi vacía: el titular gigante (que se compone después) va a ser el héroe. "
        "Pattern-interrupt silencioso."
    ),
    "ilustracion": (
        "ESTILO ILUSTRACIÓN: ilustración con carácter y trazo humano. Dos sabores (elegí el "
        "que mejor le quede a la idea): (a) DOODLE editorial a mano — fondo papel crema, "
        "trazo de tinta negra suelto tipo sketch, acuarela/lápiz en 2-3 acentos de color "
        "(azul + amarillo), objetos y personajes simpáticos del rubro (la maraña de flechas "
        "del caos, la caja de herramientas, el celular sonando) — cálido e imperfecto, como "
        "dibujado en un cuaderno; o (b) editorial con textura de grano/risografía, escenas "
        "del rubro argentino con humor o calidez. NADA de vector corporativo chato ni clipart."
    ),
    "3d": (
        "ESTILO 3D CON GUSTO: render soft-3D / clay de UN objeto-metáfora del rubro (una "
        "caja, un carrito, un globo de chat esculpido, una camioneta toy) sobre fondo limpio "
        "de color, luz suave de estudio, sombras blandas, look táctil tipo juguete premium. "
        "NUNCA el 3D azul corporativo genérico ni robots."
    ),
    "minimal": (
        "ESTILO MINIMAL PATTERN-INTERRUPT: UN solo objeto real del rubro (un cajón, una "
        "cinta de embalar, un timbre, un celular boca abajo) centrado o en tercio, sobre "
        "fondo de color plano inesperado, muchísimo aire, luz dura con sombra marcada. "
        "Quieto y silencioso a propósito: frena el scroll entre reels ruidosos."
    ),
    "surreal": (
        "ESTILO SURREAL AI-NATIVO (para frenar el scroll): escena FOTORREALISTA pero "
        "IMPOSIBLE del rubro, tratada como si fuera un documental serio. Jugá con UNA "
        "sola idea de ESCALA o física rota, clara y legible en 1 segundo: una camioneta "
        "de reparto andando por una cordillera de cajas de cartón gigantes; un dueño de "
        "PyME en miniatura caminando sobre un teléfono del tamaño de una cancha; las "
        "estanterías del depósito convertidas en rascacielos al atardecer con autos "
        "abajo; un globo de chat verde como objeto FÍSICO gigante que dos empleados "
        "cargan como si fuera un mueble; una fila de cajones flotando en formación "
        "perfecta hacia la camioneta. Texturas hiperreales, luz cinematográfica real, "
        "cámara de cine (35mm, DOF). La gracia es que parezca una foto REAL de algo "
        "imposible — nada de look 3D/render plástico, y siempre con los objetos REALES "
        "del rubro (cajas, camioneta, mostrador, teléfono)."
    ),
    "comic": (
        "ESTILO CÓMIC (meme 2 paneles): tira cómica retro, papel crema, tinta negra a "
        "mano, colores planos cálidos. Panel 1 = el ANTES (el caos, exagerado y gracioso); "
        "panel 2 = el DESPUÉS (alivio). Un personaje simpático (puede ser un animal "
        "antropomórfico dueño de PyME). EXCEPCIÓN a la regla de no-texto: acá los GLOBOS "
        "DE DIÁLOGO SÍ llevan texto — cortito (3-6 palabras por globo), en español "
        "rioplatense, y el prompt tiene que pedir que se renderice EXACTO y bien escrito "
        "(copiá las frases de la idea cruda entre comillas). Nada de texto fuera de los "
        "globos. Paneles apilados vertical para 9:16, lado a lado para feed."
    ),
}

# Presets de dominio (know-how minado del skill banana-claude: una RECETA por tipo de
# toma en vez de forzar siempre "persona en acción", que volvía todo el feed monótono).
# El _SYSTEM sigue mandando las reglas duras; el modo sólo enfoca la escena.
_MODES = {
    "producto": (
        "MODO PRODUCTO (bodegón): esta toma es de MERCADERÍA/producto, SIN persona. "
        "Ignorá la regla de 'persona en acción'. Producto real de distribuidora "
        "(cajas, botellas, bolsas, insumos) sobre una superficie real del rubro "
        "(mostrador de madera, pallet, mesada de acero). Product / still-life "
        "photography, macro o plano medio, luz de ventana suave, foco nítido, el "
        "depósito desenfocado detrás. Acento navy/royal como detalle del packaging."
    ),
    "lugar": (
        "MODO LUGAR (establishing): el PROTAGONISTA es el espacio, no una persona. "
        "Plano ABIERTO del depósito/galpón/local con estanterías, pasillos de pallets "
        "y mercadería apilada. Puede haber una persona chica al fondo dando escala, o "
        "ninguna. Wide 24-35mm, profundidad, luz natural entrando por los portones. "
        "Documental, real, argentino."
    ),
    "calle": (
        "MODO CALLE (reparto): repartidor o camioneta de reparto EN LA CALLE argentina "
        "haciendo una entrega (bajando cajones, cargando el vehículo, tocando timbre). "
        "Vereda, comercio de barrio, luz de día real. Documental urbano, plano entero."
    ),
    # default "persona": lo maneja el _SYSTEM tal cual (persona en acción en el entorno).
}

_MODE_HINTS = {
    "producto": ("producto", "bodeg", "packaging", "cajón de", "botell",
                 "bolsa de", "insumo", "primer plano de", "close up de", "close-up de"),
    "lugar": ("deposito", "depósito", "galpon", "galpón", "estanter", "pasillo",
              "almacen", "almacén", "vista del", "plano abierto", "interior del local"),
    "calle": ("calle", "reparto", "repartidor", "camioneta", "entrega", "vereda",
              "delivery", "en moto"),
}


# Rotación DETERMINÍSTICA de escenas para el modo "persona" (anti-monotonía real:
# pedirle variedad al LLM no alcanza — regresa al arquetipo 'hombre con barba en el
# depósito mirando el celular'. Acá la escena base cambia SÍ o SÍ en cada pieza,
# con el índice persistido en data/art-rotation.json).
_SCENES = [
    "una DUEÑA de distribuidora (mujer, 35-50) atendiendo el mostrador de su local, "
    "mañana luminosa, clientes esperando detrás",
    "un repartidor JOVEN en moto con caja de reparto, calle de barrio argentina con "
    "comercios, media tarde, movimiento urbano real",
    "SOLO MANOS (sin cara) cargando cajones apilados en la caja de una camioneta "
    "utilitaria en la vereda, luz dura de mediodía",
    "un almacenero detrás de un mostrador DESBORDADO de mercadería variada, luz cálida "
    "de local de barrio, hora pico",
    "el galpón vacío y ordenado DE NOCHE con las últimas luces prendidas, nadie en "
    "cuadro, mood cinematográfico de cierre de jornada",
    "DOS SOCIOS (hombre y mujer) haciendo inventario juntos entre estanterías, uno "
    "dicta y el otro anota, luz natural de tarde, complicidad",
    "un chofer subiendo a la camioneta de reparto al AMANECER, primera luz naranja, "
    "la persiana del depósito a medio abrir detrás",
    "un corralón/ferretería: la dueña mostrándole un producto pesado a un cliente en "
    "el mostrador de madera, luz de ventana lateral",
    "la mesa de un BAR: el dueño de la PyME desayunando con el cuaderno de pedidos "
    "abierto, café y medialunas, luz de mañana por la vidriera",
    "un mercado mayorista bullicioso: gente con carros, torres de cajones de "
    "mercadería, gran angular con profundidad y movimiento",
]

_ROTATION_FILE = None  # lazy: Path al lado de data/


def _scene_block() -> str:
    """Devuelve la escena base de esta pieza y avanza el índice persistido."""
    global _ROTATION_FILE
    import json
    from pathlib import Path
    if _ROTATION_FILE is None:
        _ROTATION_FILE = Path(__file__).resolve().parent.parent.parent / "data" / "art-rotation.json"
    idx = 0
    try:
        idx = int(json.loads(_ROTATION_FILE.read_text()).get("persona", 0))
    except Exception:
        pass
    scene = _SCENES[idx % len(_SCENES)]
    try:
        from .jsonstore import write_json_atomic
        write_json_atomic(_ROTATION_FILE, {"persona": (idx + 1) % len(_SCENES)})
    except Exception:
        pass
    return (
        "ROTACIÓN ANTI-MONOTONÍA (OBLIGATORIA): ambientá esta pieza en LA SIGUIENTE "
        f"escena: {scene}. Mantené el CONCEPTO/mensaje de la idea cruda, pero el "
        "lugar, el sujeto y la luz son LOS DE ESTA ESCENA — salvo que la idea cruda "
        "exija un lugar/sujeto específico distinto del típico depósito (si la idea "
        "cruda es 'otra persona en un depósito con el celular', ignorála y usá la "
        "escena de acá)."
    )


def _detect_mode(raw: str) -> str:
    low = (raw or "").lower()
    for mode, hints in _MODE_HINTS.items():
        if any(h in low for h in hints):
            return mode
    return "persona"


def _clean(t: str) -> str:
    t = (t or "").strip()
    # sacar prefijos tipo "Prompt:" / markdown / comillas envolventes
    t = re.sub(r"^\s*(prompt|final prompt|imagen)\s*[:：]\s*", "", t, flags=re.IGNORECASE)
    t = t.strip().strip('"').strip("`").strip()
    # conservar la estructura de la plantilla (colapsar solo líneas en blanco de más)
    t = re.sub(r"\n{2,}", "\n", t)
    return t.strip()[:2000]


def refine(raw_prompt: str, formato: str = "post", estilo: str = "") -> str:
    """Devuelve un prompt mejorado (o el crudo si el refinamiento falla).
    `estilo` explícito manda: gráfico (banner/tipografico/ilustracion/3d/minimal) usa
    el sistema de diseño; foto (o vacío) usa el fotográfico con detección de modo."""
    raw = (raw_prompt or "").strip()
    s = get_settings()
    if len(raw) < 8 or not getattr(s, "image_prompt_refine", True):
        return raw_prompt
    estilo = (estilo or "").lower()
    if estilo in _GRAPHIC_MODES:
        system = _SYSTEM_GRAPHIC
        mode = estilo
        user = (f"Idea cruda ({formato}) para una pieza de Automiq:\n{raw}\n\n"
                + _GRAPHIC_MODES[estilo] + "\n\n"
                + "Devolvé el prompt final en inglés (un párrafo).")
    else:
        system = _SYSTEM
        mode = _detect_mode(raw)
        mode_block = _MODES.get(mode, "") or _scene_block()
        user = (f"Idea cruda ({formato}) para una imagen de Automiq:\n{raw}\n\n"
                + (mode_block + "\n\n" if mode_block else "")
                + "Devolvé el prompt fotográfico final en inglés (un párrafo).")

    # 1) GLM vía NVIDIA (mejor redactor, gratis)
    if getattr(s, "nvidia_api_key", ""):
        try:
            from ..clients.nvidia import NvidiaClient
            with NvidiaClient(s) as c:
                r = c.complete(system, [{"role": "user", "content": user}],
                               provider="glm", max_tokens=400, temperature=0.7)
            out = _clean(r.text)
            if len(out) >= 40:
                log.info("image_prompt_refined", provider="glm", mode=mode, chars=len(out))
                return out
        except Exception as e:
            log.warning("refine_glm_failed", error=str(e)[:150])

    # 2) Fallback MiniMax
    try:
        from ..clients.minimax import MiniMaxClient
        with MiniMaxClient(s) as mc:
            r = mc.complete(system, [{"role": "user", "content": user}],
                            max_tokens=400, temperature=0.7)
        out = _clean(r.text)
        if len(out) >= 40:
            log.info("image_prompt_refined", provider="minimax", mode=mode, chars=len(out))
            return out
    except Exception as e:
        log.warning("refine_minimax_failed", error=str(e)[:150])

    return raw_prompt
