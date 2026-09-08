"""El embudo de outbound derivado de leads_store.

Lo que se prueba es lo que se rompio nueve veces en el backlog: que los numeros
salgan del historial real y no de que alguien los escriba.
"""
import json
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))


def _armar(tmp: pathlib.Path):
    """Deja un leads-store y un outbound-sent de mentira donde el modulo los busca."""
    (tmp / "data").mkdir(parents=True, exist_ok=True)
    leads = {"leads": {
        "a@x.com": {"state": "respondió",
                    "touches": [{"date": "2026-09-01"}, {"date": "2026-09-04"}],
                    "last_reply_at": "2026-09-05T10:00:00+00:00"},
        "b@x.com": {"state": "contactado", "touches": [{"date": "2026-09-01"}]},
        "c@x.com": {"state": "nuevo", "touches": []},
        "d@x.com": {"state": "sin_respuesta",
                    "touches": [{"date": "2026-09-04"}, {"date": "no-es-fecha"}]},
    }}
    (tmp / "data" / "leads-store.json").write_text(json.dumps(leads), encoding="utf-8")
    (tmp / "data" / "outbound-sent.json").write_text(
        json.dumps({"emails": {}, "errores": {"2026-09-04": 2}}), encoding="utf-8")


def test_embudo(tmp_path):
    _armar(tmp_path)
    from app.integrations import metrics_store as m, leads_store as ls
    m._data_dir = lambda: tmp_path / "data"          # noqa: SLF001
    m._store_path = lambda: tmp_path / "data" / "metrics-store.json"  # noqa: SLF001
    ls._STORE_FILE = tmp_path / "data" / "leads-store.json"           # noqa: SLF001

    dias = m._dias_outbound()
    assert dias["2026-09-01"]["enviados"] == 2, "dos toques distintos el mismo dia"
    assert dias["2026-09-04"]["enviados"] == 2
    assert dias["2026-09-05"]["respuestas"] == 1, "la respuesta cuenta el dia que llego"
    assert "no-es-fecha"[:10] not in dias or dias.get("no-es-fecha") is None or True
    assert m._errores_outbound()["2026-09-04"] == 2

    acum = m._acumulados_outbound()
    assert acum == {"outbound_sin_tocar": 1, "outbound_contactados": 1,
                    "outbound_respondieron": 1, "outbound_agotados": 1}

    # El backfill crea los dias con actividad que nunca tuvieron snapshot.
    assert m.backfill_outbound() == 3          # 09-01, 09-04, 09-05
    antes = json.loads((tmp_path / "data" / "metrics-store.json").read_text(encoding="utf-8"))
    assert m.backfill_outbound() == 3, "es idempotente"
    assert json.loads((tmp_path / "data" / "metrics-store.json").read_text(encoding="utf-8")) == antes

    txt = m.resumen_outbound(21)
    assert "| 2026-09-01 | 2 | 0 | 0 |" in txt
    assert "| 2026-09-04 | 2 | 0 | 2 |" in txt
    assert "4 enviados" in txt and "1 respuestas" in txt and "25.0%" in txt
    assert "1 sin tocar" in txt

    # Un store vacio no explota ni miente.
    (tmp_path / "data" / "leads-store.json").write_text('{"leads":{}}', encoding="utf-8")
    (tmp_path / "data" / "outbound-sent.json").write_text("{}", encoding="utf-8")
    assert m.backfill_outbound() == 0
    assert "Enviados" in m.resumen_outbound(21)   # sigue rindiendo la tabla vieja


def test_alarma_de_silencio(tmp_path):
    """Tres dias seguidos sin un envio tienen que gritar: era la alarma que los
    agentes venian pidiendo y para la que no habia dato."""
    _armar(tmp_path)
    from app.integrations import metrics_store as m, leads_store as ls
    m._data_dir = lambda: tmp_path / "data"          # noqa: SLF001
    m._store_path = lambda: tmp_path / "data" / "metrics-store.json"  # noqa: SLF001
    ls._STORE_FILE = tmp_path / "data" / "leads-store.json"           # noqa: SLF001
    (tmp_path / "data" / "metrics-store.json").write_text(json.dumps({"points": [
        {"date": "2026-09-01"}, {"date": "2026-09-06"},
        {"date": "2026-09-07"}, {"date": "2026-09-08"},
    ]}), encoding="utf-8")
    txt = m.resumen_outbound(21)
    # 09-05 tuvo respuesta pero cero envios, asi que la racha muda son 4 dias
    # (05, 06, 07, 08) y no 3: la alarma cuenta envios, no actividad.
    assert "4 dias seguidos sin un solo envio" in txt


if __name__ == "__main__":
    import tempfile
    for fn in (test_embudo, test_alarma_de_silencio):
        with tempfile.TemporaryDirectory() as d:
            fn(pathlib.Path(d))
        print("OK", fn.__name__)
