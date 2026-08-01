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
         "text": "Neurentia cotizó 14.000 dólares fase 1 más 500 por mes para la "
                 "cámara veterinaria. Scalabl es el incumbente y hizo la web."},
        {"note": "2026-07-12-Anti-Monotonia-Imagenes-Surreal", "folder": "08-Actualizaciones",
         "title": "Rotacion de estilos",
         "text": "Rotacion determinista de estilos de imagen para que el carrusel "
                 "de instagram no repita siempre la misma estetica."},
    ],
    "code": [{"id": "x1", "file": "app/integrations/publish_queue.py",
              "label": "encolar_publicacion()", "kind": "code"}],
}
# Biblioteca de terceros: mismo tema, texto más largo → sin penalización le gana
# a la doctrina propia y el agente termina citando un README ajeno.
CEREBRO["sections"].append(
    {"note": "README-paid-media", "folder": "06-Resources", "ref": True,
     "title": "Paid Media Division",
     "text": "Camara veterinaria: paid media playbook, competencia, cotizacion, "
             "camara, veterinaria, competencia, cotizacion, presupuesto generico."})

tmp = Path(tempfile.gettempdir()) / "test-brain-graph.json"
tmp.write_text(json.dumps(CEREBRO), encoding="utf-8")
bs._FILE = tmp
bs._cache["mtime"] = None

# 1. Capa vault: encuentra la SECCIÓN del tema, no otra. La consulta va SIN
# tildes y el pasaje las tiene: sin plegar acentos esto no matchea nunca.
hits = bs.search("cuanto cotizo la competencia para la camara veterinaria")
assert hits and hits[0]["note"] == "2026-07-17-Propuesta-CLAMEVET", hits
assert "Neurentia" in hits[0]["text"], hits[0]
assert bs.search("cámara veterinaria competencia")[0]["note"] == \
    "2026-07-17-Propuesta-CLAMEVET"   # y al revés también

# 2. Una nota sin secciones sigue siendo encontrable por su extracto
hits = bs.search("regla de cobranza recordatorio factura")
assert hits and hits[0]["note"] == "Nota-Sin-Secciones", hits

# 3. Capa código: se puede pedir sola
hits = bs.search("encolar publicacion queue", layer="code")
assert hits and hits[0]["layer"] == "code", hits
assert all(h["layer"] == "code" for h in hits)

# 3b. La doctrina propia le gana a la biblioteca de terceros sobre el mismo tema
hits = bs.search("competencia cotizacion camara veterinaria", k=2)
assert hits[0]["note"] == "2026-07-17-Propuesta-CLAMEVET", [h["note"] for h in hits]

# 4. Un tema ajeno NO arrastra ruido (umbral de 2 términos)
assert bs.search("receta de milanesas napolitanas") == []
assert bs.search("") == []

# 5. El bloque del prompt trae el pasaje; "" cuando no hay match
b = bs.block("cuanto cotizo la competencia de la camara veterinaria")
assert "Neurentia" in b and "CEREBRO DE LA EMPRESA" in b, b
assert bs.block("receta de milanesas napolitanas") == ""

# 5b. Capa MATERIAL (playbook/dirección de arte): se pide aparte y NUNCA compite
#     con la doctrina en la búsqueda general.
bs._MATERIAL = {"playbook de prueba": ("_test_material", "texto")}
bs._cache["mtime"] = None
import types
mod = types.ModuleType("app.integrations._test_material")
mod.texto = lambda: ("# Regla de los 2 segundos\nEl gancho entra antes del segundo dos "
                     "o el scroll se lo lleva puesto, siempre.\n"
                     "# Carruseles\nEl carrusel educativo es el formato que mas guarda "
                     "genera en instagram para cuentas de servicios.\n")
sys.modules["app.integrations._test_material"] = mod

hits = bs.search("carrusel educativo instagram", layer="material")
assert hits and hits[0]["fuente"] == "playbook de prueba", hits
assert all(h["layer"] != "material" for h in bs.search("carrusel educativo instagram"))

# Piso: una consulta que no matchea NADA igual sale con reglas base — antes el
# agente recibía el material entero, quedarse en cero sería un retroceso.
b = bs.block("xyz sin relacion alguna", layer="material")
assert "MATERIAL DE COMPETENCIA" in b and "2 segundos" in b, b

# 6. Sin cerebro sincronizado el agente sigue corriendo (no explota)
bs._MATERIAL = {}
bs._FILE = Path(tempfile.gettempdir()) / "no-existe-brain.json"
bs._cache["mtime"] = None
assert bs.search("lo que sea") == [] and bs.block("lo que sea") == ""

print("OK — brain_search (vault + codigo)")
