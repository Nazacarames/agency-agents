"""Los hechos medidos tienen que cubrir los DOS sitios.

Si `bloque_todos` devuelve uno solo, el plan de crecimiento vuelve a mirar
nada más la landing de la agencia y el CRM —que es lo que se cobra por mes—
queda sin optimizar por nadie.
"""
from app.integrations import landing_facts


def _falso(url):
    return {"ok": True, "url": url, "bytes": 1000, "h1": "titulo", "h1_cantidad": 1,
            "title": "t", "meta_description": "d", "contadores_en_cero": 0,
            "google_ads": True, "ga4": False, "meta_pixel": False}


def test_bloque_todos_trae_los_dos(monkeypatch):
    monkeypatch.setattr(landing_facts, "medir", _falso)
    landing_facts._CACHE.clear()
    txt = landing_facts.bloque_todos()
    assert "https://automiq.agency" in txt
    assert "https://crm.automiq.agency" in txt
    assert txt.count("=== fin hechos ===") == 2


def test_el_cache_no_se_pisa_entre_sitios(monkeypatch):
    """Con una sola ranura, medir el segundo sitio borraba al primero y cada
    llamada volvia a bajar el HTML."""
    bajadas = []

    def contando(url):
        bajadas.append(url)
        return _falso(url)

    monkeypatch.setattr(landing_facts, "medir", contando)
    landing_facts._CACHE.clear()
    landing_facts.bloque_todos()
    landing_facts.bloque_todos()
    assert len(bajadas) == 2, "la segunda vuelta tenia que salir del cache"


def test_crm_web_es_un_area_valida():
    from app.integrations import backlog
    assert "crm-web" in backlog.AREAS
