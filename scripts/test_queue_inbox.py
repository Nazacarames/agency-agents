"""Check de los arreglos del 2026-08-02: vencimiento de la cola de publicación,
cupo previo a generar, y desalojo FIFO del buzón. Correr:
    python scripts/test_queue_inbox.py
"""
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.integrations import agent_inbox as inbox
from app.integrations import publish_queue as pq

tmp = Path(tempfile.mkdtemp(prefix="test-queue-"))
pq._store_path = lambda: tmp / "publish-queue.json"


def _hace(dias: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=dias)).isoformat()


# ── 1. La cola vence lo viejo y libera cupo ──────────────────────────────────
for i in range(pq.MAX_PENDING):
    assert pq.enqueue(f"/media/{i}.jpg", f"pieza {i}", kind="post"), i
assert pq.pending_count() == pq.MAX_PENDING
assert pq.free_slots() == 0
# Con la cola llena NO entra nada: es el estado real medido en prod (30/30).
assert pq.enqueue("/media/nueva.jpg", "no entra") is None

# Envejecemos la mitad más allá del TTL (así estaba: lo más viejo, de hace 24 días).
store = pq.load_store()
for it in store["items"][15:]:
    it["created_at"] = _hace(pq.PENDING_TTL_DIAS + 10)
pq.save_store(store)

assert pq.expire_stale() == 15
assert pq.pending_count() == 15 and pq.free_slots() == 15
# Vencer NO borra: el historial queda para el panel.
assert sum(1 for it in pq.load_store()["items"] if it["status"] == "expired") == 15
assert pq.expire_stale() == 0            # idempotente
assert pq.enqueue("/media/nueva.jpg", "ahora sí") is not None

# Un item sin fecha usable no se vence (mejor publicarlo que perderlo en silencio).
store = pq.load_store()
store["items"][0]["created_at"] = "cualquier cosa"
pq.save_store(store)
assert pq.expire_stale() == 0

# ── 2. Buzón: desaloja la nota MÁS VIEJA, no la nueva ────────────────────────
inbox._FILE = tmp / "agent-notes.json"
for i in range(inbox.MAX_PER_RECIPIENT):
    assert inbox.leave("growth_hacker", "web_optimizer", f"nota {i}")

data = inbox._load()
data["notes"][0]["created_at"] = _hace(3)   # la más vieja, todavía dentro del TTL
vieja = data["notes"][0]["note"]
inbox._save(data)

# Con el buzón lleno la nota nueva ENTRA (antes se descartaba y se perdía lo fresco).
assert inbox.leave("media_auditor", "web_optimizer", "esta es la fresca")
notas = [n["note"] for n in inbox.peek_all() if n["to"] == "web_optimizer"]
assert "esta es la fresca" in notas, notas
assert vieja not in notas, "tenía que caer la más vieja"
assert len(notas) == inbox.MAX_PER_RECIPIENT, notas

# El dedup exacto sigue vivo (una nota repetida no desaloja a nadie).
assert inbox.leave("media_auditor", "web_optimizer", "esta es la fresca") is False
assert len([n for n in inbox.peek_all() if n["to"] == "web_optimizer"]) == inbox.MAX_PER_RECIPIENT

print("OK — cola (vencimiento + cupo) y buzón (desalojo FIFO)")
