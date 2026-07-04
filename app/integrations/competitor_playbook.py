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
    """Bloque para inyectar en los prompts de los agentes de contenido."""
    return (
        "\n\n=== PLAYBOOK DE COMPETENCIA (lo que HOY funciona — respetalo) ===\n"
        + load_playbook().strip()
        + "\n=== fin playbook ===\n"
        "Aplicá esto a CADA pieza: gancho en 2s, outcome-first, formato/duración por "
        "plataforma, y evitá los clichés visuales listados."
    )
