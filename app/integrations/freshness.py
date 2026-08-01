"""
freshness — cuán viejo es cada bloque que se le inyecta a un agente.

Varios bloques se presentan como si fueran de hoy ("TENDENCIAS AHORA", "RADAR DE
HOY") pero salen de archivos que se refrescan por cron: el 2026-08-01 el prompt
de social_media traía tendencias relevadas el 2026-07-26 rotuladas como "AHORA".
El agente no tiene cómo saberlo y decide sobre datos vencidos creyéndolos frescos.

Acá se resuelve en un solo lugar: `sello()` declara la antigüedad real y `vigente()`
deja caer el material que ya no se puede presentar como actual.
"""
from __future__ import annotations

import time
from pathlib import Path


def edad_dias(path: Path) -> float | None:
    """Días desde la última escritura del archivo, o None si no existe."""
    try:
        return (time.time() - Path(path).stat().st_mtime) / 86400
    except Exception:
        return None


def sello(path: Path) -> str:
    """Sufijo para el encabezado del bloque: ' · relevado hace 6 días'."""
    d = edad_dias(path)
    if d is None:
        return ""
    if d < 1:
        return " · relevado hoy"
    if d < 2:
        return " · relevado ayer"
    return f" · relevado hace {int(d)} días"


def vigente(path: Path, ttl_dias: float) -> bool:
    """¿El material todavía se puede presentar como actual? Si el archivo no
    existe devuelve False: mejor no inyectar nada que inyectar algo sin fecha."""
    d = edad_dias(path)
    return d is not None and d <= ttl_dias
