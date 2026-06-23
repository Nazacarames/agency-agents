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

| # | Empresa | Industria | Fit | Contacto verificado +54 |
|---|---------|-----------|-----|--------------------------|
| 1 | Eidico S.A. | Desarrollista inmobiliaria | 5/6 | +54 9 11 3586-6629 (WA) |
| 2 | Loginter S.A. | Logística | 5/6 | +54 11 5263-3200 |

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
    wq = ls.whatsapp_queue(store)
    assert len(wq) == 2
    eidico = next(l for l in store["leads"].values() if "Eidico" in l["company"])
    assert eidico["phone"] == "+5491135866629"
    assert eidico["industria"] == "Desarrollista inmobiliaria"


def test_ingest_is_idempotent():
    report = """### Lead 1: Acme SA
- Email: hola@acme.com.ar"""
    store = ls._empty_store()
    ls.ingest_report(store, report, today="2026-06-22")
    res2 = ls.ingest_report(store, report, today="2026-06-23")
    assert res2["nuevos"] == 0 and res2["existentes"] == 1
    assert len(store["leads"]) == 1


def test_sequence_cadence_advances_0_2_5_9():
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
    assert store["leads"][key]["next_touch_at"] == "2026-06-27"  # +3
    ls.record_touch(store, key, step=2, today="2026-06-27")
    assert store["leads"][key]["next_touch_at"] == "2026-07-01"  # +4
    # Último toque → secuencia agotada
    ls.record_touch(store, key, step=3, today="2026-07-01")
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
