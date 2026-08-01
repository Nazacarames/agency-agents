"""Check de brain_search: las dos capas del cerebro (vault + código), relevancia,
umbral y tolerancia a cerebro vacío. Correr: python scripts/test_brain_search.py"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.integrations import brain_search as bs

CEREBRO = {
    "nodes": [{"id": "Nota-Sin-Secciones", "folder": "07-Knowledge",
               "excerpt": "Regla de cobranza: nunca mandamos factura sin recordatorio previo."}],
    "sections": [
        {"note": "2026-07-17-Propuesta-CLAMEVET", "folder": "08-Actualizaciones",
         "title": "La competencia",
         "text": "Neurentia cotizo 14.000 dolares fase 1 mas 500 por mes para la "
                 "camara veterinaria. Scalabl es el incumbente y hizo la web."},
        {"note": "2026-07-12-Anti-Monotonia-Imagenes-Surreal", "folder": "08-Actualizaciones",
         "title": "Rotacion de estilos",
         "text": "Rotacion determinista de estilos de imagen para que el carrusel "
                 "de instagram no repita siempre la misma estetica."},
    ],
    "code": [{"id": "x1", "file": "app/integrations/publish_queue.py",
              "label": "encolar_publicacion()", "kind": "code"}],
}

tmp = Path(tempfile.gettempdir()) / "test-brain-graph.json"
tmp.write_text(json.dumps(CEREBRO), encoding="utf-8")
bs._FILE = tmp
bs._cache["mtime"] = None

# 1. Capa vault: encuentra la SECCIÓN del tema, no otra
hits = bs.search("cuanto cotizo la competencia para la camara veterinaria")
assert hits and hits[0]["note"] == "2026-07-17-Propuesta-CLAMEVET", hits
assert "Neurentia" in hits[0]["text"], hits[0]

# 2. Una nota sin secciones sigue siendo encontrable por su extracto
hits = bs.search("regla de cobranza recordatorio factura")
assert hits and hits[0]["note"] == "Nota-Sin-Secciones", hits

# 3. Capa código: se puede pedir sola
hits = bs.search("encolar publicacion queue", layer="code")
assert hits and hits[0]["layer"] == "code", hits
assert all(h["layer"] == "code" for h in hits)

# 4. Un tema ajeno NO arrastra ruido (umbral de 2 términos)
assert bs.search("receta de milanesas napolitanas") == []
assert bs.search("") == []

# 5. El bloque del prompt trae el pasaje; "" cuando no hay match
b = bs.block("cuanto cotizo la competencia de la camara veterinaria")
assert "Neurentia" in b and "CEREBRO DE LA EMPRESA" in b, b
assert bs.block("receta de milanesas napolitanas") == ""

# 6. Sin cerebro sincronizado el agente sigue corriendo (no explota)
bs._FILE = Path(tempfile.gettempdir()) / "no-existe-brain.json"
bs._cache["mtime"] = None
assert bs.search("lo que sea") == [] and bs.block("lo que sea") == ""

print("OK — brain_search (vault + codigo)")
