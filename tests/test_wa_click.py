"""Clics a WhatsApp en la web (2026-10-06): sin medirlos no se distingue
"no llega gente" de "llega y no escribe"."""
import json

from fastapi.testclient import TestClient


def test_el_clic_se_guarda_y_sale_en_el_resumen(tmp_path, monkeypatch):
    import app.main as m
    monkeypatch.setattr(m, "_data_dir", lambda: tmp_path)
    monkeypatch.setattr(m, "_verify_webhook_secret", lambda request: None)
    client = TestClient(m.app)              # sin `with`: no arranca el scheduler
    for pagina in ("/precios", "/precios", "/integrar-crm-whatsapp"):
        r = client.post("/api/web/wa-click", content=json.dumps(
            {"path": pagina, "ref": "https://www.google.com/search?q=crm"}))
        assert r.status_code == 200 and r.json() == {"ok": True}
    guardado = json.loads((tmp_path / "wa-clicks.json").read_text(encoding="utf-8"))["clicks"]
    assert [c["path"] for c in guardado] == ["/precios", "/precios", "/integrar-crm-whatsapp"]
    assert guardado[0]["ref"] == "www.google.com"   # sólo el dominio, no la búsqueda
    w = client.get("/api/web/ai-visits").json()["whatsapp"]
    assert w["clics_28d"] == 3 and w["por_pagina_28d"] == {"/precios": 2, "/integrar-crm-whatsapp": 1}


def test_body_roto_es_400(tmp_path, monkeypatch):
    import app.main as m
    monkeypatch.setattr(m, "_data_dir", lambda: tmp_path)
    assert TestClient(m.app).post("/api/web/wa-click", content=b"{no json").status_code == 400
