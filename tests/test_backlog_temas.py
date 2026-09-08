"""temas_repetidos: dejar de esconder que el equipo pide lo mismo N veces.

El caso real: nueve pendientes distintos de chief_of_staff pidiendo la serie
historica de outbound, cada uno figurando como "reportado 1 vez".
"""
import json
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))


def _store(tmp: pathlib.Path, titulos):
    items = []
    for n, (area, tit) in enumerate(titulos):
        items.append({"id": f"{n:08x}", "area": area, "titulo": tit,
                      "estado": "abierto", "abierto": "2026-09-01T00:00:00+00:00",
                      "veces": 1, "origenes": ["chief_of_staff"]})
    f = tmp / "backlog.json"
    f.write_text(json.dumps({"items": items}), encoding="utf-8")
    return f


def test_agrupa_por_palabra_de_codigo(tmp_path):
    from app.integrations import backlog as b
    b._FILE = _store(tmp_path, [                       # noqa: SLF001
        ("dev", "modificar outbound para hard-fail si series_historicas_w34_w35 no estan pobladas"),
        ("dev", "outbound - suspender envios si series_historicas_w34_w35 no se reporto"),
        ("dev", "agregar hard-fail en outbound.py: si series_historicas_w34_w35 no esta poblado"),
        ("dev", "content_creator - rotacion de angulo psicologico del pool de cinco"),
    ])
    grupos = b.temas_repetidos("dev")
    assert grupos, "tres pendientes sobre lo mismo tienen que agruparse"
    g = grupos[0]
    assert g["cantidad"] == 3
    assert "outbound" in g["tema"] or "series_historicas" in g["tema"]
    assert "00000003" not in g["ids"], "el de content_creator no pertenece al grupo"

    # Y el agente lo lee antes que la lista.
    txt = b.bloque("dev")
    assert "3 pendientes distintos hablan de" in txt
    assert txt.index("pendientes distintos hablan") < txt.index("modificar outbound")


def test_no_agrupa_por_ruido(tmp_path):
    """Un ano suelto o una palabra de relleno no son un tema."""
    from app.integrations import backlog as b
    b._FILE = _store(tmp_path, [                       # noqa: SLF001
        ("web", "revisar el sitemap antes del 2026-09-30 pero sin tocar el home"),
        ("web", "confirmar el pixel antes del 2026-10-01 pero con la cuenta nueva"),
        ("web", "verificar el schema antes del 2026-10-02 pero en produccion"),
    ])
    temas = [g["tema"] for g in b.temas_repetidos("web")]
    assert not any(t.isdigit() for t in temas), "un numero no dice de que se trata"
    assert "pero" not in temas


def test_menos_del_minimo_no_es_tema(tmp_path):
    from app.integrations import backlog as b
    b._FILE = _store(tmp_path, [                       # noqa: SLF001
        ("dev", "arreglar el leadhunter que arma emails por patron"),
        ("dev", "el leadhunter tiene que marcar sitio_debil cuando el score es bajo"),
    ])
    assert b.temas_repetidos("dev") == [], "dos no es un patron"


if __name__ == "__main__":
    import tempfile
    for fn in (test_agrupa_por_palabra_de_codigo, test_no_agrupa_por_ruido,
               test_menos_del_minimo_no_es_tema):
        with tempfile.TemporaryDirectory() as d:
            fn(pathlib.Path(d))
        print("OK", fn.__name__)
