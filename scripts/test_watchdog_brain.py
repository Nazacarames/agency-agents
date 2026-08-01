"""Check del watchdog del Cerebro: alerta solo si la sync se atrasó.
Correr: python scripts/test_watchdog_brain.py"""
import json
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.integrations import watchdog

tmp = Path(tempfile.mkdtemp())
watchdog._DATA = tmp
f = tmp / "brain-graph.json"


def sync_hace(horas):
    ts = datetime.now(timezone.utc) - timedelta(hours=horas)
    f.write_text(json.dumps({"received_at": ts.isoformat()}), encoding="utf-8")


# 1. Al día → sin alerta
sync_hace(6)
assert watchdog._brain_stale() == 0.0

# 2. Justo en el borde → sin alerta todavía
sync_hace(47)
assert watchdog._brain_stale() == 0.0

# 3. Pasado el umbral → alerta con las horas reales
sync_hace(72)
stale = watchdog._brain_stale()
assert 71 < stale < 73, stale

# 4. Sin cerebro / archivo roto → NO alerta (no es una regresión, nunca hubo sync)
f.unlink()
assert watchdog._brain_stale() == 0.0
f.write_text("{no es json", encoding="utf-8")
assert watchdog._brain_stale() == 0.0

print("OK — watchdog del cerebro")
