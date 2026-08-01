"""Check de freshness: sello de antigüedad y caída de material vencido.
Correr: python scripts/test_freshness.py"""
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.integrations.freshness import edad_dias, sello, vigente

tmp = Path(tempfile.mkdtemp())
hoy = tmp / "hoy.md"
hoy.write_text("x", encoding="utf-8")
viejo = tmp / "viejo.md"
viejo.write_text("x", encoding="utf-8")
os.utime(viejo, (time.time() - 6 * 86400, time.time() - 6 * 86400))

# 1. Antigüedad declarada, no inventada
assert sello(hoy) == " · relevado hoy", sello(hoy)
assert sello(viejo) == " · relevado hace 6 días", sello(viejo)
assert 5.9 < edad_dias(viejo) < 6.1

# 2. Vigencia: lo de hoy pasa, lo de 6 días no pasa un TTL de 3
assert vigente(hoy, 3) and not vigente(viejo, 3)
assert vigente(viejo, 14)     # con TTL largo sigue sirviendo

# 3. Un archivo que no existe NO es vigente y no lleva sello: mejor no inyectar
#    nada que inyectar material sin fecha.
falta = tmp / "no-existe.md"
assert edad_dias(falta) is None and sello(falta) == "" and not vigente(falta, 999)

# 4. El bloque de tendencias se cae solo cuando vence (era el caso real: decía
#    "AHORA" con datos de 6 días)
from app.integrations import trends
trends._FILE = viejo
trends.TTL_DIAS = 3
assert trends.load_block() == ""
trends.TTL_DIAS = 14
viejo.write_text("=== TENDENCIAS AHORA (datos reales, 2026-07-26) ===\nsube ia\n", encoding="utf-8")
os.utime(viejo, (time.time() - 6 * 86400, time.time() - 6 * 86400))
out = trends.load_block()
assert "relevado hace 6 días" in out, out

print("OK — freshness")
