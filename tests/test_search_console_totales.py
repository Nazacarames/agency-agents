"""Las métricas del SEO que sirven para decidir (2026-10-06): el total de
impresiones bajó y se leyó como caída, cuando lo que se fue era la página 6+."""
from datetime import date


def test_top10_y_clics_sin_marca(monkeypatch):
    from app.integrations import search_console as sc
    monkeypatch.setattr(sc, "enabled", lambda: True)
    monkeypatch.setattr(sc, "_session", lambda: object())
    monkeypatch.setattr(sc, "_resolve_site", lambda sess: "sc-domain:automiq.agency")
    hoy = date.today()

    def falso(sess, site, start, end, dims, limit=250):
        actual = (hoy - end).days < 10      # la ventana actual termina hace 3 días
        if dims != ["query"]:
            return []
        if actual:
            return [{"keys": ["automiq"], "clicks": 5, "impressions": 8, "ctr": .6, "position": 1.2},
                    {"keys": ["crm con whatsapp"], "clicks": 1, "impressions": 35, "ctr": .03, "position": 7.2},
                    {"keys": ["automatizar ecommerce"], "clicks": 0, "impressions": 19, "ctr": 0, "position": 69.7}]
        return [{"keys": ["automiq"], "clicks": 4, "impressions": 7, "ctr": .5, "position": 1.5},
                {"keys": ["automatizar ecommerce"], "clicks": 0, "impressions": 65, "ctr": 0, "position": 68.2}]

    monkeypatch.setattr(sc, "_query", falso)
    t = sc.snapshot()["totales"]
    assert t["impresiones"] == 62 and t["impresiones_antes"] == 72      # "bajó"
    assert t["impresiones_top10"] == 43 and t["impresiones_top10_antes"] == 7   # pero no
    assert t["clicks_sin_marca"] == 1 and t["clicks_sin_marca_antes"] == 0
