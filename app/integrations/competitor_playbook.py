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


# Dossier de competidores (análisis manual profundo 2026-07-04, varios ángulos).
# Es contexto FIJO (no lo toca el refresh) que se inyecta junto al playbook.
COMPETITOR_DEEP_DIVE = """
=== DOSSIER DE COMPETIDORES (análisis profundo — imágenes y video) ===

## Zolutium (@zolutium.es · 37,5K en TikTok · España/LATAM)
- Ángulo: "app #1 de IA, empleado virtual 24/7 que vende, atiende y agenda solo".
  Números en el hero: **+50% ventas, +85% menos leads no calificados**.
- Prueba social AGRESIVA: logos Forbes/Yahoo/WSJ, "30.000 usuarios", "11.000 negocios",
  15+ testimonios (nombre + ubicación + antes/después).
- Ángulos emocionales: **tranquilidad/alivio** ("vas a estar tranquilo"), "trabajá
  mientras dormís", FOMO, garantía 100% sin contratos.
- VIDEO (TikTok): hook fijo "Descubrí cómo Zolutium revoluciona tu negocio → agendá
  una DEMO EN VIVO". IMÁGENES: screenshots de chats del bot, testimonios con avatar+
  ubicación, mapas geográficos, métricas grandes. Estética gradiente azul/púrpura.
- ROBAR: testimonio en screenshot con antes/después; número grande en el frame;
  ángulo "tranquilidad". EVITAR: su gradiente corporativo genérico → nosotros humano/local.

## Kommo (CRM de WhatsApp · YouTube fuerte)
- Ángulo: "el CRM #1 basado en mensajería". Su formato estrella es **click-to-WhatsApp ads**.
- Contenido educativo, partner de Meta, tutoriales del Salesbot paso a paso; free trial 2 semanas.
- ROBAR: la **demo del bot paso a paso**; el ángulo click-to-WhatsApp (nuestro producto ES eso).

## Landbot (no-code chatbot · rey del contenido)
- Formato **"case study modular"**: misma estructura fija (objetivo, disparador, qué
  pregunta, lógica, handoff, métrica) con rubro variado (gobierno, salud, energía, ONGs).
- VIDEO: **clips cortos SIN AUDIO mostrando el bot en tiempo real** (loop), visual dominante,
  poco texto. IMÁGENES: GIFs/loops del bot funcionando.
- ROBAR: los clips loop del bot en acción (ideales para reels) + el caso modular (mismo
  esqueleto, rubro distinto cada semana → escala de contenido).

## Aivo (IA conversacional enterprise · ARGENTINA, Córdoba)
- Ángulo: casos con **NÚMEROS DUROS**. Banco Comafi 98% resolución + $2M primer mes;
  Bancor 80.000 consultas/mes, 85% resolución 1ra interacción; Efecty 2,5M consultas,
  -48% llamadas; Banco Bolivariano 98% automatizado en WhatsApp.
- Formato: titular narrativo + resultado cuantitativo (cards "Load More").
- ROBAR: el formato "Empresa + número duro + resultado" (el más creíble) — nosotros con
  distribuidoras locales. Aivo es argentina y global → prueba de que el mercado local escala.

## Tácticas para NUESTRAS IMÁGENES (Imagen 4)
- Testimonio en screenshot (estilo Zolutium) pero con distribuidoras ARGENTINAS reales.
- Número grande como protagonista (lo compone el sistema con Pillow, no el modelo).
- Foto editorial de la ESCENA real (depósito, repartidor) — NO gradientes corporativos.
- Mockup de chat de WhatsApp del bot funcionando (no imagen generada de UI).

## Tácticas para NUESTROS VIDEOS/SHORTS (Veo + Nazareno)
- Clip corto del bot contestando EN VIVO (estilo Landbot, loop) intercalado con Nazareno.
- Hook "demo en vivo" (Zolutium) pero SIN ser anuncio: "mirá lo que hace este agente en
  una distribuidora" (enseñás, no vendés).
- Caso con número duro (Aivo): "le puse un agente a una distribuidora, esto pasó en 7 días".
- Formato modular (Landbot): mismo esqueleto, rubro distinto cada video → volumen.

## Rangos de referencia del sector (NO son promesas nuestras — marcarlos como referencia)
- Resolución 85-98% · reducción de llamadas 20-50% · +50% ventas · atención 24/7.

## La ventaja Automiq (lo que NINGUNO tiene)
Cara humana (Nazareno) + voz porteña + casos LOCALES reales (distribuidoras) + producción
superior (Veo/Imagen 4). El mercado argentino está MENOS desarrollado → entramos con una
calidad que la competencia local todavía no usa.
=== fin dossier ===
""".strip()


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
    return (
        "\n\n=== PLAYBOOK DE COMPETENCIA (lo que HOY funciona — respetalo) ===\n"
        + load_playbook().strip()
        + "\n=== fin playbook ===\n"
        + COMPETITOR_DEEP_DIVE
        + "\nAplicá esto a CADA pieza: gancho en 2s, outcome-first, formato/duración por "
        "plataforma, robá las tácticas del dossier adaptadas a distribuidoras argentinas, "
        "y evitá los clichés visuales listados."
    )
