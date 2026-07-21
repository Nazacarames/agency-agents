"""
seo_progress — la bitácora del web_optimizer: lo único que hace que las corridas
sean un proceso y no 26 intentos sueltos por año.

Vive en el VOLUMEN (`data/seo-progress.md`), no en el repo de la landing: la
landing se deploya por CLI sin git y su fuente se baja a un temp que se borra al
terminar. Ahí la bitácora duraría lo que dura la corrida.

Ciclo: se inyecta entera al prompt → el agente decide mirando qué movió la aguja
la vez pasada → al terminar reescribe la bitácora completa dentro de un bloque
```bitacora ... ``` → acá se extrae y se persiste.

Que la reescriba ENTERA (en vez de appendear) es a propósito: así puede borrar
hipótesis que se demostraron falsas y consolidar, en vez de arrastrar un archivo
que crece sin fin hasta no entrar en el contexto. El tope de tamaño es la red de
seguridad por si igual se va de mambo.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from ..log import get_logger

log = get_logger("seo_progress")

_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "seo-progress.md"
_MAX_CHARS = 24_000

_SEMILLA = """# Bitácora SEO/GEO — automiq.agency

_(Todavía no corrió ninguna iteración: esta es la primera. No hay historial que
leer — arrancá midiendo el estado actual y dejá la línea de base escrita acá.)_

## Estado
Sin datos previos.

## Qué funcionó
Nada medido todavía.

## Qué NO funcionó
Nada descartado todavía.

## Acciones para la próxima iteración
1. Establecer la línea de base con los datos de Search Console.
2. Identificar las consultas a tiro de página 1 y priorizarlas.
"""


def read() -> str:
    """La bitácora actual, o la semilla si es la primera corrida."""
    try:
        txt = _PATH.read_text(encoding="utf-8").strip()
        if txt:
            return txt
    except FileNotFoundError:
        pass
    except Exception as e:
        log.warning("seo_progress_read_failed", error=str(e)[:120])
    return _SEMILLA


_BLOQUE_RE = re.compile(r"```bitacora\s*\n(.*?)```", re.S | re.I)


def extract(texto: str) -> Optional[str]:
    """Saca la bitácora nueva del output del agente. None si no la escribió."""
    m = _BLOQUE_RE.search(texto or "")
    if not m:
        return None
    nueva = m.group(1).strip()
    return nueva or None


def write(contenido: str) -> bool:
    try:
        _PATH.parent.mkdir(parents=True, exist_ok=True)
        _PATH.write_text(contenido[:_MAX_CHARS].strip() + "\n", encoding="utf-8")
        log.info("seo_progress_escrita", chars=len(contenido))
        return True
    except Exception as e:
        log.warning("seo_progress_write_failed", error=str(e)[:120])
        return False


def strip_bloque(texto: str) -> str:
    """Saca el bloque ```bitacora``` del texto que se entrega por Discord: ya
    quedó persistido, y en el reporte es ruido."""
    return _BLOQUE_RE.sub("", texto or "").strip()
