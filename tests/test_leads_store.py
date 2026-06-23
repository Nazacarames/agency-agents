"""
Tests del leads_store: motor de secuencia (cadencia día 0/+2/+5/+9), ingest del
reporte de leadhunter, dedup, y corte de secuencia al responder.
"""
from app.integrations import leads_store as ls


def test_ingest_extracts_email_and_phone():
    report = """
# LeadHunter — Reporte

### Lead 1: Distribuidora Norte SA
- Industria: distribución
- Decisor: Juan Pérez, Gerente Comercial
- Web: https://distnorte.com.ar
- Contacto: +54 9 11 5555-1234
- Email: ventas@distnorte.com.ar

### Lead 2: Logística Sur SRL
- Industria: logística
- Contacto (whatsapp): +54 9 351 444-9876
"""
    store = ls._empty_store()
    res = ls.ingest_report(store, report, today="2026-06-22")
    assert res["nuevos"] == 2
    l1 = store["leads"]["ventas@distnorte.com.ar"]
    assert l1["company"].startswith("Distribuidora Norte")
    assert l1["phone"] == "+5491155551234"
    assert l1["channel"] == "email"
    assert l1["state"] == "nuevo"
    assert l1["next_touch_at"] == "2026-06-22"  # due hoy para el primer toque
    # Lead 2 sin email → cae en la cola de WhatsApp manual, no en la secuencia auto.
    wq = ls.whatsapp_queue(store)
    assert len(wq) == 1 and wq[0]["channel"] == "whatsapp"


def test_ingest_from_summary_table_only():
    """Reporte real de leadhunter: contacto SOLO en la tabla resumen, bloques de
    detalle vacíos. El teléfono debe capturarse igual (cola WhatsApp)."""
    report = """# LeadHunter Report

## 1) Tabla resumen

| # | Empresa | Industria | Fit | Contacto +54 | Email |
|---|---------|-----------|-----|--------------|-------|
| 1 | Eidico S.A. | Desarrollista inmobiliaria | 5/6 | +54 9 11 3586-6629 (WA) | (sin email público) |
| 2 | Loginter S.A. | Logística | 5/6 | +54 11 5263-3200 | ventas@loginter.com.ar |

## 2) Detalle por lead

## 🟢 Lead #1 — Eidico S.A.

| Campo | Valor |
|---|---|

## 🟢 Lead #2 — Loginter S.A.

| Campo | Valor |
|---|---|
"""
    store = ls._empty_store()
    res = ls.ingest_report(store, report, today="2026-06-22")
    # 2 empresas, NO 4 (tabla + detalle de la misma empresa = 1 registro)
    assert res["nuevos"] == 2
    assert len(store["leads"]) == 2
    # Eidico sin email → cola WhatsApp. Loginter con email → due para outbound auto.
    eidico = next(l for l in store["leads"].values() if "Eidico" in l["company"])
    assert eidico["phone"] == "+5491135866629"
    assert eidico["industria"] == "Desarrollista inmobiliaria"
    assert eidico["email"] == ""
    loginter = store["leads"]["ventas@loginter.com.ar"]
    assert loginter["company"].startswith("Loginter")
    assert loginter["phone"] == "+541152633200"
    assert ls.whatsapp_queue(store) == [eidico]
    assert [l["key"] for l in ls.due_for_touch(store, today="2026-06-22")] == ["ventas@loginter.com.ar"]


def test_ingest_is_idempotent():
    report = """### Lead 1: Acme SA
- Email: hola@acme.com.ar"""
    store = ls._empty_store()
    ls.ingest_report(store, report, today="2026-06-22")
    res2 = ls.ingest_report(store, report, today="2026-06-23")
    assert res2["nuevos"] == 0 and res2["existentes"] == 1
    assert len(store["leads"]) == 1


def test_sequence_cadence_advances_0_2_4_7():
    store = ls._empty_store()
    key = ls.upsert_lead(store, company="Acme", email="a@acme.com", today="2026-06-22")
    # Día 0: due para step 0
    due = ls.due_for_touch(store, today="2026-06-22")
    assert [l["key"] for l in due] == [key]
    ls.record_touch(store, key, step=0, today="2026-06-22")
    assert store["leads"][key]["next_step"] == 1
    assert store["leads"][key]["next_touch_at"] == "2026-06-24"  # +2
    # No due todavía el 23
    assert ls.due_for_touch(store, today="2026-06-23") == []
    # Due el 24 → step 1
    assert len(ls.due_for_touch(store, today="2026-06-24")) == 1
    ls.record_touch(store, key, step=1, today="2026-06-24")
    assert store["leads"][key]["next_touch_at"] == "2026-06-26"  # +2
    ls.record_touch(store, key, step=2, today="2026-06-26")
    assert store["leads"][key]["next_touch_at"] == "2026-06-29"  # +3
    # Último toque → secuencia agotada
    ls.record_touch(store, key, step=3, today="2026-06-29")
    assert store["leads"][key]["next_touch_at"] is None
    assert store["leads"][key]["state"] == "sin_respuesta"
    assert ls.due_for_touch(store, today="2026-08-01") == []


def test_reply_stops_sequence():
    store = ls._empty_store()
    key = ls.upsert_lead(store, company="Acme", email="a@acme.com", today="2026-06-22")
    ls.record_touch(store, key, step=0, today="2026-06-22")
    lead = ls.mark_replied(store, email="A@Acme.com", when="2026-06-23T10:00:00")
    assert lead is not None
    assert store["leads"][key]["state"] == "respondió"
    assert store["leads"][key]["next_touch_at"] is None
    # Ya no aparece como due nunca más
    assert ls.due_for_touch(store, today="2026-07-30") == []


def test_reply_from_unknown_sender_is_ignored():
    store = ls._empty_store()
    ls.upsert_lead(store, company="Acme", email="a@acme.com", today="2026-06-22")
    assert ls.mark_replied(store, email="random@stranger.com") is None


def test_match_and_remove_keys():
    store = ls._empty_store()
    ls.upsert_lead(store, company="Buena PyME", email="ventas@buenapyme.com.ar", today="2026-06-23")
    ls.upsert_lead(store, company="Fate", email="sac@fate.com.ar", today="2026-06-23")
    ls.upsert_lead(store, company="Coto", email="contactoweb@coto.com.ar", today="2026-06-23")
    # match por dominio de las grandes
    bad = ls.match_keys(store, email_contains=["fate.com", "coto.com"])
    assert set(bad) == {"sac@fate.com.ar", "contactoweb@coto.com.ar"}
    removed = ls.remove_keys(store, bad)
    assert removed == 2
    assert list(store["leads"].keys()) == ["ventas@buenapyme.com.ar"]


def test_match_untouched_only_and_state():
    store = ls._empty_store()
    k1 = ls.upsert_lead(store, company="A", email="a@a.com", today="2026-06-23")
    ls.upsert_lead(store, company="B", email="b@b.com", today="2026-06-23")
    ls.record_touch(store, k1, step=0, today="2026-06-23")  # a@a.com ya tocado
    untouched = ls.match_keys(store, states=["nuevo"], untouched_only=True)
    assert untouched == ["b@b.com"]


def test_reset_store_empties():
    import tempfile
    from pathlib import Path
    orig = ls._STORE_FILE
    ls._STORE_FILE = Path(tempfile.mkdtemp()) / "s.json"
    try:
        store = ls._empty_store()
        ls.upsert_lead(store, company="A", email="a@a.com", today="2026-06-23")
        ls.save_store(store)
        fresh = ls.reset_store()
        assert fresh["leads"] == {}
        assert ls.load_store()["leads"] == {}
    finally:
        ls._STORE_FILE = orig


def test_seed_from_sent_log_avoids_remailing():
    report = """### Lead 1: Acme SA
- Email: hola@acme.com.ar"""
    store = ls._empty_store()
    sent = {"hola@acme.com.ar": {"company": "Acme", "date": "2026-06-20"}}
    ls.ingest_report(store, report, today="2026-06-22", sent_log_emails=sent)
    lead = store["leads"]["hola@acme.com.ar"]
    # No arranca en step 0 hoy: ya estaba contactado el 20 → próximo follow-up el 22.
    assert lead["state"] == "contactado"
    assert lead["next_step"] == 1
    assert lead["next_touch_at"] == "2026-06-22"
