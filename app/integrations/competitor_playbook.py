"""
competitor_playbook — el "estudio de competencia" PERSISTENTE que alimenta al
content_creator, tiktok_creator y creative_strategist.

Dos capas:
1. Un PLAYBOOK destilado (data/competitor-playbook.md) con lo que hoy funciona en
   contenido de agencias/servicios de IA (formatos, hooks, qué evitar). Se inyecta
   a los prompts SIEMPRE → el contenido se ancla en lo que rinde, no en supuestos.
2. Un REFRESCO (competitor_study.refresh) semanal que re-investiga con búsquedas
   reales (Tavily vía web_search) y reescribe este playbook → estudio "constante".

Si el archivo no existe todavía, se usa SEED_PLAYBOOK (sembrado con research real
del 2026-07-03). Best-effort: si algo falla, no rompe la generación de contenido.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ..log import get_logger

log = get_logger("competitor_playbook")

_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
_FILE = _DATA_DIR / "competitor-playbook.md"

# Sembrado con research real (WebSearch, 2026-07-03): qué funciona HOY en contenido
# de agencias/servicios de IA. Lo reescribe competitor_study.refresh() cada semana.
SEED_PLAYBOOK = """# Playbook de competencia — contenido que funciona (agencias/servicios de IA)
_Fuente: research 2026-07-03. Se refresca semanalmente._

## Regla de los primeros 2 segundos
- El gancho tiene que aterrizar en **≤2s** o el video muere. Los mejores creadores
  logran **>70% de retención de intro**; por debajo de 40% el algoritmo lo entierra.
- Entregá el hook con **20% más de energía** que una conversación normal.

## Hooks que más convierten (rankeados por data)
1. **Outcome/resultado PRIMERO** — mostrá el resultado o la transformación en los
   primeros 2s (≈2× views). Ej: mostrar el bot contestando solo ANTES de explicar.
2. **"¿Sabías que...?"** — abre curiosity gap (22M+ views acumuladas en el nicho).
3. **"3 errores que hacés con X"** — auto-identificación, duplica engagement.
4. **Pain-point + métrica sorpresa** — "¿Qué pasa si automatizás los pedidos?" →
   mostrás el número que mejora.
5. **Before/After** — tarea manual → automatizada, con el tiempo/plata ahorrado.
6. **"Lo estás haciendo mal"** — contrarian, frena el scroll.

## Formatos y duración
- **Reels IG: 7-15s** (sweet spot de alcance). **TikTok/Shorts: 15-30s**.
- El **completion rate** es EL factor de ranking → cortá todo lo que no sume.
- Formatos ganadores: "3 tips en 30s", "before/after", tool/outcome showcase,
  micro-caso ("le puse un agente 7 días, esto pasó"), construir en público.

## Video / Shorts (lo que hacen los que la rompen)
- **Mostrá el PRODUCTO funcionando en pantalla**: el bot contestando un WhatsApp real,
  el pedido cargándose solo. La demo EN VIVO es el hook más fuerte (outcome-first).
- **Cara a cámara + texto grande** simultáneos desde el frame 0 (doble anclaje).
- **1 a 3 shorts/día**, espaciados ≥3hs (evita canibalizar alcance y filtros de spam).
- Hashtags de NICHO, no `#fyp`/`#parati`: `#automatizacionIA`, `#crmwhatsapp`, `#pymesarg`.
- El contenido educativo de IA en español creció **387% interanual** (2.8 mil millones
  de views): hay demanda enorme y poca oferta buena en criollo → entrá con volumen.

## Qué hacen los competidores en español (Kommo, Zolutium y afines)
- **Zolutium**: hook "empleado virtual 24/7 que responde, agenda y cobra solo";
  3 pilares (+ventas / ahorro / optimización); MUCHA prueba social (Forbes/NBC, +20
  screenshots de testimonios reales, "14.000 clientes"); oferta con precio tachado
  ($250→$97) y garantía. Táctica a robar: **testimonios en screenshot** + **outcome
  numérico**. A evitar: su estética es genérica de SaaS → nosotros vamos más humano/local.
- **Kommo**: educa sobre "CRM para WhatsApp" con carruseles y demos de Salesbot;
  contenido tutorial. Táctica a robar: **demo del bot paso a paso**.
- **Diferenciación Automiq**: somos argentinos, mostramos casos LOCALES reales
  (distribuidoras, no "negocios" abstractos), voz porteña, y la cara de Nazareno
  (marca personal) que ninguno de ellos tiene. El mercado AR está **menos desarrollado**
  → podemos usar mejor producción (Veo, Imagen 4) que la competencia local no usa.

## Meta Ads (paid)
- **Click-to-WhatsApp**: el formato estrella para nuestro servicio (fricción cero,
  el lead cae directo al chat). Alineado 1:1 con lo que vende Automiq.
- Rotar **15-25 variantes de creativo por semana** — la fatiga llega a las **72hs**.
- Lead-qualification en el chat (urgencia/interés) antes de escalar a humano.

## Estrategia de producción
- **1-to-10**: un asset madre autoritativo → 10 micro-piezas nativas por plataforma.
- **Document > Create**: mostrá lo que Automiq YA hace (un bot real, un lead que
  entró por una automatización). Real e inimitable > genérico.

## Clichés visuales a EVITAR (los repite toda la competencia)
- Render 3D azul genérico, robots sonrientes, "businessman con laptop", cerebros
  con circuitos, hologramas, manos tocando pantallas flotantes.
- En su lugar: **foto editorial realista** de la ESCENA concreta del vertical
  (la dueña en su depósito de distribución, el repartidor, el equipo en reunión),
  luz natural, profundidad de campo. La paleta navy + royal blue es solo el acento.
"""


# Dossier de referencia — MIRADO de verdad (video real bajado y visto frame por frame,
# 2026-07-05: yt-dlp + ffmpeg + lectura de frames). NO es de training/web: son notas de
# lo que efectivamente se vio. Contexto FIJO que se inyecta junto al playbook.
COMPETITOR_DEEP_DIVE = """
=== DOSSIER DE REFERENCIA (MIRADO frame por frame — video real, 2026-07-05) ===

## COMPETIDORES (mismo rubro: bot/CRM de mensajería)

### ManyChat  [MIRADO]
- Formato: talking-head enérgico (creador a cámara, luz cálida rim) + CARTEL en pill
  blanco con frase filosa ("The Harsh Truth is…") + secciones planas color-marca (violeta)
  con UI animándose (toggles, un checkmark marcando "EMAIL COLLECTION ✓") + íconos emoji
  como beats visuales (❤️ 🔗 💰) + screenshots del dashboard.
- Hooks: contrarian/curiosidad ("La verdad incómoda es…"), texto GRANDE desde el frame 0.
- ROBAR: el cartel-pill con una frase filosa; los íconos emoji como beats; mostrar la
  feature EN MOVIMIENTO (un toggle/checkmark animándose), no una captura estática.

### Kommo  [MIRADO]
- Formato: creador estilo streamer (silla gamer, micrófono grande, fondo con luces RGB y
  pantallas) + POP-INS de logos de plataforma (WhatsApp verde, Instagram) animando al lado
  suyo mientras habla + screen-share del CRM con él en PiP abajo-derecha + cutaway de
  reacción (inserto tipo meme para cortar el ritmo). Ángulo: click-to-WhatsApp, Salesbot paso a paso.
- ROBAR: los pop-ins de logos WhatsApp/IG entrando animados junto al presentador; el
  screen-share + PiP para el paso a paso; el cutaway de reacción.
- NUESTRA ventaja: Nazareno es cara HUMANA real y local (no set genérico de streamer),
  voz porteña, casos AR.

## MARCAS DE REFERENCIA — e-commerce con mucho ad (de acá robamos ESTÉTICA, no compiten)

### Tiendanube  [MIRADO] ← la más cercana a nuestro público
- Estética: emprendedores REALES en su espacio REAL y desordenado (taller textil con
  percheros de telas estampadas; cocina de casa de noche), luz cinematográfica mezclando
  cálido de interior + frío de ventana, DOF corto. El producto/UI aparece EN CONTEXTO en
  un notebook/celular real sostenido por manos reales ("Creá tu tienda online"), con
  overlays 3D lúdicos (etiqueta "10% OFF", ícono cute) como acento.
- ROBAR (clave): el MAKER en su taller real (NO estudio); la mezcla de luz cálido+frío;
  el producto en un device real sostenido; el overlay 3D jugado como acento.

### Shopify  [MIRADO]
- Estética: premium cinematográfico, gente REAL haciendo oficio (un viejo en su puesto con
  verduras y tablero ajedrezado, un vivero, un barista, manos en primerísimo plano), luz
  natural cálida, DOF muy corto, moody. El HÉROE es el que labura; el producto se implica.
- ROBAR: dignificar al que trabaja (primeros planos de manos haciendo el oficio) y la
  VARIEDAD DE PLANOS (wide establishing, macro de manos, over-shoulder, close-up de cara).

### Mercado Libre  [MIRADO]
- Estética (brand film "Somos millones"): cine emocional épico — cosmos/nebulosas oscuras,
  NOSTALGIA ("Internet · Año 1999", un tipo en una compu vieja), macro de lente, escala
  épica, logo amarillo POP sobre fondo oscuro, carteles de texto centrados.
- ROBAR: el ángulo NOSTALGIA/origen ("¿te acordás cuando…?") y la escala emocional para
  UNA pieza de marca cada tanto (no todo el tiempo); el color de marca pop sobre fondo oscuro.

## LA LECCIÓN VISUAL #1 (por qué nuestras imágenes salían parecidas)
Ninguna hace retrato de estudio ni 3D azul genérico. Y sobre todo: TODAS ROTAN EL TIPO DE
PLANO. Nosotros repetíamos "persona centrada en la escena" siempre. Hay que rotar: wide
establishing / macro de manos trabajando / over-shoulder / POV / close-up de cara /
low-angle. Mismo sujeto, plano distinto = feed que no aburre. (Ya cableado en image_gen:
rotación de plano al azar por imagen.)

## Tácticas NUESTRAS
- IMÁGENES: maker argentino real en su depósito/taller (Tiendanube+Shopify), luz cálido+frío,
  plano rotado; el número/etiqueta lo compone Pillow encima. NADA de estudio ni 3D azul.
- VIDEOS/SHORTS: talking-head Nazareno + cartel-pill con frase filosa (ManyChat) + pop-ins
  de logos WhatsApp/IG (Kommo) + demo del bot en PiP; 1 pieza de marca emocional estilo
  MeLi de vez en cuando. Caso con número duro: "le puse un agente a una distribuidora 7 días".
- Rangos del sector como REFERENCIA (no promesa): resolución 85-98% · -20/50% llamadas · 24/7.

## La ventaja Automiq (lo que NINGUNO tiene)
Cara humana (Nazareno) + voz porteña + casos LOCALES reales (distribuidoras) + producción
superior (Veo/Imagen 4). El mercado AR está MENOS desarrollado → entramos con calidad que
la competencia local todavía no usa.
=== fin dossier ===
""".strip()


# SEED del visual scout (playbook de EDICIÓN/hooks/formato, foco VIDEO = 90% de leads).
# Destilado de mirar video real con scripts/scout_watch.py. El archivo
# data/visual-scout.md (si existe) lo overridea; si no, va este seed.
SEED_VISUAL_SCOUT = """=== VISUAL SCOUT — playbook de EDICIÓN / hooks / formato (mirado de verdad) ===
_Foco: VIDEO, que es el 90% de los leads. Refrescable con scripts/scout_watch.py._

## Regla madre: VARIAR el formato, NADA de plantilla fija (que se sienta ORGÁNICO)
1. **Split-card** — presentador LLENA el cuadro + demo del bot como card sobrepuesta abajo (borde de marca). NUNCA el bot pelado a pantalla completa.
2. **Full orgánico** — presentador solo a cámara; la demo entra como cutaway corto (1-2s) intercalado, no fija todo el tiempo.
3. **Screen-share + PiP** (Kommo) — pantalla del CRM/WhatsApp + presentador en recuadro chico abajo-derecha.
4. **Talking-head + carteles-pill** (ManyChat) — frase filosa en pill blanco, texto GRANDE desde el frame 0, emojis como beats.
5. **B-roll de maker** (Tiendanube/Shopify) — SIN presentador: el dueño real en su depósito/taller, manos trabajando, luz cálido+frío.

## Dónde va la demo del bot (clave)
NUNCA sola y pelada. Va sobrepuesta abajo (card), al costado (inset) o como cutaway mientras la persona habla; la palabra referencia lo que se ve ("mirá lo que contesta acá abajo").

## Hooks REALES mirados (robar la estructura)
- **Kommo (pain-question):** "¿Alguna vez tuviste la sensación de que los chats de clientes son un torbellino imposible de controlar?"
- **ManyChat (contrarian):** "La verdad incómoda es…"
- Patrón: dolor concreto del dueño de PyME + promesa de orden en la 1ª frase, hablado natural (no leído).

## Edición orgánica (no plantilla)
Texto grande desde el frame 0; cortes que respiran; pop-ins de logos WhatsApp/IG al nombrarlos; un cutaway de reacción para romper ritmo; porteño, una idea por video. Evitá el look template (paneles fijos, transiciones genéricas).

## Imágenes / banners para ads (no siempre una persona)
Además del maker en su entorno: banners con producto / un ícono fuerte / fondo potente + espacio limpio para el titular (lo compone Pillow). Navy + azul. Usar image_gen.generate_image(..., kind="banner").

## Redes cubiertas
YouTube ✅ + TikTok ✅ (por búsqueda). Instagram y Meta/FB Ads: pendientes de credenciales (cookies IG + token Ad Library).
=== fin visual scout ==="""


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def load_playbook() -> str:
    try:
        t = _FILE.read_text(encoding="utf-8")
        if t.strip():
            return t
    except FileNotFoundError:
        pass
    except Exception as e:
        log.warning("playbook_load_failed", error=str(e)[:150])
    return SEED_PLAYBOOK


def save_playbook(text: str) -> None:
    try:
        _DATA_DIR.mkdir(exist_ok=True)
        _FILE.write_text(text, encoding="utf-8")
        log.info("playbook_saved", chars=len(text))
    except Exception as e:
        log.error("playbook_save_failed", error=str(e)[:150])


def playbook_block() -> str:
    """Bloque para inyectar en los prompts de los agentes de contenido: el playbook
    dinámico (se refresca solo) + el dossier de competidores (contexto fijo profundo)."""
    trends = ""
    try:
        from . import trends as _t
        tb = _t.load_block()
        if tb:
            trends = "\n\n" + tb
    except Exception:
        trends = ""
    # Playbook de EDICIÓN/hooks/visual del "visual scout" (destilado de mirar video real).
    # Igual que el playbook: SEED en código (llega seguro a prod) + override opcional del
    # archivo data/visual-scout.md que escribe scripts/scout_watch.py + curación humana.
    scout_txt = SEED_VISUAL_SCOUT
    try:
        t = (_DATA_DIR / "visual-scout.md").read_text(encoding="utf-8").strip()
        if t:
            scout_txt = t
    except Exception:
        pass
    scout = "\n\n" + scout_txt
    # Autopsy de NUESTRO contenido (datos reales de IG): qué funcionó de lo propio.
    # Best-effort y silencioso hasta que haya engagement real.
    autopsy = ""
    try:
        from . import content_autopsy
        autopsy = content_autopsy.block()
    except Exception:
        autopsy = ""
    return (
        "\n\n=== PLAYBOOK DE COMPETENCIA (lo que HOY funciona — respetalo) ===\n"
        + load_playbook().strip()
        + "\n=== fin playbook ===\n"
        + COMPETITOR_DEEP_DIVE
        + scout
        + autopsy
        + trends
        + "\nAplicá esto a CADA pieza: gancho en 2s, outcome-first, formato/duración por "
        "plataforma, robá las tácticas del dossier adaptadas a distribuidoras argentinas, "
        "surfeá las tendencias que están subiendo, y evitá los clichés visuales listados."
    )
