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
FEED = pq.MAX_PENDING_FEED
for i in range(FEED):
    assert pq.enqueue(f"/media/{i}.jpg", f"pieza {i}", kind="post"), i
assert pq.pending_count(lane="feed") == FEED
assert pq.free_slots("feed") == 0
# Carril de feed lleno: no entra otra pieza de feed…
assert pq.enqueue("/media/nueva.jpg", "no entra") is None
# …pero las historias drenan aparte (2/día), así que su carril sigue abierto. Con el
# tope único compartido esto NO pasaba: el feed se comía la cola y las historias
# quedaban afuera (2026-08-07 en prod: 27 de feed contra 3 historias, 30/30).
assert pq.free_slots("story") == pq.MAX_PENDING_STORY
assert pq.enqueue("/media/h.jpg", "historia", kind="story") is not None

# Envejecemos parte del feed más allá del TTL (así estaba: lo más viejo, 24 días).
store = pq.load_store()
viejos = [it for it in store["items"] if it["kind"] == "post"][5:]
for it in viejos:
    it["created_at"] = _hace(pq.PENDING_TTL_DIAS + 10)
pq.save_store(store)

assert pq.expire_stale() == len(viejos)
assert pq.pending_count(lane="feed") == FEED - len(viejos)
assert pq.free_slots("feed") == len(viejos)
# Vencer NO borra: el historial queda para el panel.
assert sum(1 for it in pq.load_store()["items"] if it["status"] == "expired") == len(viejos)
assert pq.expire_stale() == 0            # idempotente
assert pq.enqueue("/media/nueva.jpg", "ahora sí") is not None

# Ningún carril puede aceptar más de lo que alcanza a drenar antes de vencer: si acepta
# más, esas piezas vencen sin publicarse y la cuota de imagen que costaron se tira.
assert pq.MAX_PENDING_FEED <= 1 * pq.PENDING_TTL_DIAS
assert pq.MAX_PENDING_STORY <= pq.MAX_STORIES_PER_DAY * pq.PENDING_TTL_DIAS

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
