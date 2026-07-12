"""
creative_direction — la DIRECCIÓN DE ARTE viva de Automiq (formatos/estilos de imagen
y ad que convierten HOY). Complementa al competitor-playbook (que es video/hook-céntrico)
con la capa que faltaba: QUÉ TIPO de imagen hacer y cómo variar.

Dos capas (mismo patrón que competitor_playbook):
1. SEED_DIRECTION — estudio real 2026-07-06 (WebSearch: SaaS Hero, Favoured, Superside,
   Balistro, Versa Creative + cuentas verificadas con Business Discovery).
2. refresh() — re-estudio MENSUAL hecho por el sistema (web_search + destilado LLM)
   que reescribe data/creative-direction.md. Los agentes siempre leen la versión viva.

block() se inyecta a los agentes de contenido vía competitor_playbook.playbook_block().
Best-effort: si algo falla, queda el seed / la versión anterior.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from ..log import get_logger

log = get_logger("creative_direction")

_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
_FILE = _DATA_DIR / "creative-direction.md"

# Patrones minados de 14 ads REALES de la competencia directa (Kommo, Ropofy, Zolutium,
# Siete AI — Ad Library, curados por el usuario 2026-07-08). Es verdad de campo, no
# estudio automático → block() los inyecta SIEMPRE, aunque el re-estudio mensual haya
# reescrito data/creative-direction.md.
AD_LIBRARY_PATTERNS = """## Lo que hacen TODOS los ads ganadores del rubro (14 ads reales de Kommo/Ropofy/Zolutium/Siete AI, Ad Library 2026-07-08)
- **Muestran el producto FUNCIONANDO**: un chat de WhatsApp legible con una conversación
  real (cliente pide → bot resuelve) es LA prueba en todos los ads que escalan. Nosotros
  lo tenemos nativo: estilo `demo` (chat pixel-perfect renderizado por código).
- **Piezas POR VERTICAL**: Kommo corre el MISMO ad adaptado ("broadcast para clínicas" /
  "para inmobiliarias"). Hablarle a UN rubro convierte más que el mensaje genérico.
- **Antes/Después en una pieza**: Zolutium parte la imagen (caos con cables vs calma con
  IA). El contraste visual cuenta la historia sin leer.
- **Humor/meme con personaje**: el cómic del perro ("Mi agenda es un caos" → "Conecté mi
  agenda a WhatsApp") es pattern-interrupt puro y no parece ad → estilo `comic`.
- **Checklist de beneficios**: Ropofy/iOBOT listan features como filas con íconos. Para
  nosotros va como CARRUSEL (una placa por beneficio), no apretado en una imagen.
- **Ancla de precio + CTA visible** (solo para ADS pagos, NO para el feed orgánico):
  "PLANES DESDE $97 USD" + botón. El orgánico nuestro sigue la regla no-anuncio.

## El patrón @ai._kid / Claura (competidor directo, medido con datos reales 2026-07-12)
Cuenta 100% IA de nuestro MISMO nicho (27k followers). Sus 4 posts top son TODOS
carruseles; sus reels flopean (0-130 likes) — copiar la máquina de carruseles, no el
spam de reels. La fórmula del carrusel que les explota (top: 4.900 likes y 10.554
comentarios):
- **Hook en 1ª persona con NÚMERO concreto y contraste**: "Publico 600 reels al mes y
  grabo cero", "Armé toda mi agencia adentro de Claude Code: 220 skills".
- **El cuerpo es EL SISTEMA paso a paso** (flujo numerado, herramientas con nombre),
  no teoría ni tips genéricos: el lector se lleva algo replicable.
- **CTA comment-gate**: "Comentá X y te mando [el prompt/la guía/el calendario]" →
  los comentarios superan a los likes (10.554💬 vs 4.900❤) y el algoritmo lo premia
  distribuyéndolo. En nuestros carruseles: pedir UNA palabra concreta y prometer un
  entregable real (checklist, demo, guía).
"""

SEED_DIRECTION = """# Dirección de arte — formatos de imagen/ad que convierten (estudio 2026-07-06)

## Los datos que mandan
- El CREATIVO explica ~56% de la varianza de performance en Meta (subió desde 47% en 2023).
  Rotar formato mueve más la aguja que tocar pujas o audiencias.
- **Carruseles**: el formato estático que MÁS rinde (+30-50% engagement vs imagen única;
  6,6% de engagement en LinkedIn). Estructura ganadora: problema → solución → prueba.
- **"Ugly ads" / anti-pulido**: el creativo que parece contenido de un amigo o un meme
  le gana al ad pulido en lead gen. El algoritmo premia engagement, no producción.
- **Estático simple como pattern-interrupt**: con el feed lleno de reels ruidosos, una
  imagen QUIETA, mínima y de color fuerte frena el pulgar justamente porque es silenciosa.
- **Tipografía como imagen**: en 2026 el titular ENORME es el héroe (apilado, escalado,
  alineación inesperada), no decoración sobre una foto.
- **Platform-native**: lo que parece contenido orgánico del feed convierte más que lo
  que "parece un ad". Social proof concreto (número de clientes, métrica dura) suma.

## Mix de formatos OBLIGATORIO (nunca dos piezas seguidas del mismo estilo)
1. **FOTO editorial del rubro** (maker real en su depósito, reparto, mostrador) — la base
   de autenticidad, pero YA NO la única carta.
2. **DEMO (prueba de producto)** — card con un chat de WhatsApp REAL del bot resolviendo
   un caso del vertical. Lo que más usan los ads ganadores; nuestro chat es pixel-perfect.
3. **EDITORIAL (placa blanca)** — titular negro gigante + frase clave con resaltador
   amarillo. Para verdades incómodas y datos duros. Nítida, distinta a todo el feed.
4. **CÓMIC meme 2 paneles** — antes(caos)/después(alivio) con personaje y humor; los
   globos llevan el chiste. No parece ad; frena el pulgar.
5. **BANNER de ad** — producto/objeto/ícono fuerte o fondo potente + aire limpio para el
   titular. Para ads y anuncios de features.
6. **TIPOGRÁFICO** — fondo plano o gradiente audaz; el TITULAR es la imagen. Ideal para
   frases filosas, datos duros, contrarian takes.
7. **ILUSTRACIÓN con carácter** — doodle a mano sobre papel crema o editorial con
   textura/grano. Para conceptos (caos→orden, tiempo recuperado).
8. **3D con gusto** — objeto clay/soft-3D sobre fondo limpio de color. Para features y
   metáforas de producto. NUNCA el 3D azul corporativo genérico.
9. **MINIMAL pattern-interrupt** — UN solo objeto, muchísimo aire, color inesperado.
   Para frenar el scroll entre reels ruidosos.

## Texto sobre la imagen: NO siempre
- ~1 de cada 3 piezas va SIN titular compuesto: la foto documental fuerte o la
  ilustración conceptual hablan solas (el copy va en el caption).
- El TIPOGRÁFICO es lo inverso: ahí el texto ES la pieza (obligatorio y corto).

## Marcas y cuentas referentes (verificadas 2026-07-06, Business Discovery)
- **Hooks (mirar y robar estructura)**: @steven (Steven Bartlett, ~104k likes/pieza),
  @hormozi, @codiesanchez, @garyvee — los mejores hooks de negocio en inglés.
- **Español**: @neuromodernos (IA, 498k), @romualdfons (marketing, hooks agresivos),
  @euge.oller (negocios, storytelling visual).
- **Formatos B2B**: @hubspot (memes + skits + carruseles educativos, 3,6k likes/pieza
  siendo marca), @manychat (nicho directo: carteles-pill, UI animada).
- Anti-referencia: Notion/Zapier/ClickUp casi no tienen engagement en IG → no copiar
  su approach de feed corporativo.

## Clichés a EVITAR (los repite toda la competencia)
- Render 3D azul genérico, robots sonrientes, "businessman con laptop", cerebros con
  circuitos, hologramas, manos tocando pantallas flotantes.
- Y el cliché NUESTRO a matar: TODAS las piezas iguales de "persona trabajando en un
  depósito, foto realista, con titular encima". Era la regla; ahora es 1 de 6 estilos.
"""

_QUERIES = [
    "best performing static ad creative formats 2026 B2B SaaS what works",
    "social media design trends 2026 typography illustration 3D static ads",
    "ugly ads meme ads platform native creative performance 2026",
    "tendencias diseño creativos redes sociales 2026 formatos que convierten español",
]

_DISTILL_SYSTEM = (
    "Sos el director de arte de una agencia argentina de automatización con IA "
    "(contenido para IG/FB/TikTok, cliente PyME distribuidora). Te paso resultados de "
    "búsqueda REALES sobre qué formatos de imagen/ad rinden HOY. Destilalos en un "
    "documento de dirección de arte en español rioplatense con EXACTAMENTE estas "
    "secciones markdown: '## Los datos que mandan', "
    "'## Mix de formatos OBLIGATORIO (nunca dos piezas seguidas del mismo estilo)', "
    "'## Texto sobre la imagen: NO siempre', '## Marcas y cuentas referentes', "
    "'## Clichés a EVITAR'. El mix tiene que mantener estos 6 estilos (podés ajustar "
    "el cuándo-usarlos con lo nuevo): FOTO editorial del rubro, DEMO (chat real del "
    "producto), EDITORIAL (placa blanca con resaltador), CÓMIC meme 2 paneles, BANNER "
    "de ad, TIPOGRÁFICO, ILUSTRACIÓN con carácter, 3D con gusto, MINIMAL "
    "pattern-interrupt. "
    "Sé concreto y cuantitativo. NADA de relleno. Empezá con "
    "'# Dirección de arte — formatos de imagen/ad que convierten' y la fecha."
)


def load() -> str:
    try:
        t = _FILE.read_text(encoding="utf-8")
        if t.strip():
            return t
    except FileNotFoundError:
        pass
    except Exception as e:
        log.warning("direction_load_failed", error=str(e)[:150])
    return SEED_DIRECTION


def block() -> str:
    """Bloque para inyectar a los agentes de contenido. Los patrones de la Ad Library
    (curados por el usuario) van SIEMPRE, por encima del estudio vivo/override."""
    try:
        return ("\n\n=== DIRECCIÓN DE ARTE (formatos de imagen/ad — estudio vivo) ===\n"
                + AD_LIBRARY_PATTERNS.strip() + "\n\n"
                + load().strip() + "\n=== fin dirección de arte ===\n")
    except Exception:
        return ""


def refresh() -> Dict[str, Any]:
    """Re-estudia el mercado de creativos (mensual) y reescribe la dirección de arte."""
    from ..config import get_settings
    s = get_settings()
    try:
        from packs.automiq.tools.web_search import web_search
    except Exception as e:
        log.warning("direction_refresh_no_search", error=str(e)[:150])
        return {"ok": False, "reason": "web_search no disponible"}

    blocks: List[str] = []
    for q in _QUERIES:
        try:
            for r in (web_search(q, 5) or [])[:5]:
                t = (r.get("title") or "").strip()
                sn = (r.get("snippet") or "").strip()
                if t or sn:
                    blocks.append(f"- {t}: {sn}")
        except Exception as e:
            log.warning("direction_search_failed", q=q, error=str(e)[:120])
    if len(blocks) < 4:
        return {"ok": False, "reason": f"búsqueda devolvió poco ({len(blocks)})"}

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    user = (f"Fecha: {today}. Material real:\n\n" + "\n".join(blocks[:40])
            + "\n\nDestilá la dirección de arte con las secciones pedidas.")
    try:
        from ..clients.minimax import MiniMaxClient
        with MiniMaxClient(s) as mc:
            resp = mc.complete(_DISTILL_SYSTEM, [{"role": "user", "content": user}],
                               max_tokens=1800, temperature=0.4)
        text = (resp.text or "").strip()
    except Exception as e:
        log.warning("direction_distill_failed", error=str(e)[:150])
        return {"ok": False, "reason": "distill falló"}

    if len(text) < 400 or "Mix de formatos" not in text:
        return {"ok": False, "reason": "destilado pobre"}
    try:
        _DATA_DIR.mkdir(exist_ok=True)
        _FILE.write_text(text + f"\n\n_Refrescado el {today} (estudio mensual automático)._\n",
                         encoding="utf-8")
    except Exception as e:
        log.error("direction_save_failed", error=str(e)[:150])
        return {"ok": False, "reason": "no se pudo guardar"}
    log.info("direction_refresh_ok", chars=len(text))
    return {"ok": True, "chars": len(text)}
