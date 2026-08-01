"""Check de vault_search: relevancia, umbral y tolerancia a cerebro vacío.
Correr: python scripts/test_vault_search.py"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.integrations import vault_search as vs

GRAFO = {"nodes": [
    {"id": "2026-07-17-Propuesta-CLAMEVET", "folder": "08-Actualizaciones",
     "excerpt": "Camara veterinaria nacional: plataforma regulatoria con foro, "
                "ingesta del boletin SENASA y alertas por producto."},
    {"id": "2026-07-12-Anti-Monotonia-Imagenes-Surreal", "folder": "08-Actualizaciones",
     "excerpt": "Rotacion determinista de estilos de imagen para que el carrusel "
                "de instagram no repita siempre la misma estetica."},
    {"id": "MOC-05-Agents", "folder": "05-Agents",
     "excerpt": "Indice de los agentes de la agencia."},
]}

tmp = Path(tempfile.gettempdir()) / "test-brain-graph.json"
tmp.write_text(json.dumps(GRAFO), encoding="utf-8")
vs._FILE = tmp
vs._cache["mtime"] = None

# 1. La query encuentra la nota del tema, no otra
hits = vs.search("propuesta para la camara veterinaria con foro regulatorio")
assert hits and hits[0]["id"] == "2026-07-17-Propuesta-CLAMEVET", hits

hits = vs.search("que estilo de imagen uso en el carrusel de instagram")
assert hits and hits[0]["id"] == "2026-07-12-Anti-Monotonia-Imagenes-Surreal", hits

# 2. Un tema ajeno NO arrastra ruido (el umbral de 2 términos)
assert vs.search("receta de milanesas napolitanas") == []
assert vs.search("") == []

# 3. El bloque para el prompt trae el extracto, y es "" cuando no hay match
b = vs.block("camara veterinaria foro regulatorio")
assert "SENASA" in b and "vault de Obsidian" in b, b
assert vs.block("receta de milanesas napolitanas") == ""

# 4. Sin cerebro sincronizado el agente sigue corriendo (no explota)
vs._FILE = Path(tempfile.gettempdir()) / "no-existe-brain.json"
vs._cache["mtime"] = None
assert vs.search("lo que sea") == [] and vs.block("lo que sea") == ""

print("OK — vault_search")
