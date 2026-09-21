"""Un lead no puede estar dos veces, ni quedar sin nadie encima (2026-09-18).

Los dos defectos salieron de mirar el pipeline real:

1. **Duplicados.** 536 leads con 33 grupos de la misma empresa repetida y 27 más
   por teléfono: 37 registros de más. Zarcam Logística estaba dos veces —una por
   teléfono y otra por mail— y la respuesta real había quedado en una sola de las
   dos mientras la secuencia seguía corriendo en la otra. Dos causas:
   `normalize_phone` no sacaba el 9 de celular argentino, y `upsert_lead` buscaba
   sólo por la clave exacta.

2. **Respuestas que se vuelven invisibles.** `mark_replied` corta la secuencia a
   propósito, pero al cortarla el lead deja de aparecer como pendiente. Data Trace
   Argentina contestó el 16/09 y estuvo dos días parado sin que nadie lo viera,
   siendo una de las DOS únicas respuestas en mes y medio.
"""
import pytest

from app.integrations import leads_store as ls


# ── el 9 de celular: se compara sin él, pero se GUARDA con él ──

def test_el_mismo_telefono_con_y_sin_9_es_el_mismo():
    """+54 9 11 4440-0131 y +54 11 4440-0131 son el MISMO teléfono. En el pipeline
    real estaban como dos leads distintos de Química Pilar."""
    assert ls.identidad_telefono("+5491144400131") == ls.identidad_telefono("+541144400131")


def test_lo_que_se_guarda_conserva_el_9():
    """`outbound._wa_link` arma wa.me con esto, y para un celular argentino wa.me
    NECESITA el 9: sin él el link no abre el chat y falla en silencio."""
    assert ls.normalize_phone("+5491135866629") == "+5491135866629"


def test_no_se_come_un_9_que_es_del_numero():
    """El 9 se saca sólo si está pegado al 54. Un 9 más adentro es del número."""
    assert ls.identidad_telefono("+5411944400131") == "+5411944400131"


def test_un_telefono_de_otro_pais_sigue_sin_valer():
    """Limitación conocida y aceptada: el pipeline es AR-only por ahora."""
    assert ls.normalize_phone("+13055551234") == ""
    assert ls.identidad_telefono("+13055551234") == ""


# ── el formato LOCAL, que es como lo escribe la gente (2026-09-21) ──

def test_un_numero_sin_codigo_de_pais_no_se_tira():
    """Antes se exigía `+54` literal y todo lo demás se descartaba EN SILENCIO.
    Medido: los 3 leads inbound de la web —Sumiagro, CBA y Exequiel— quedaron sin
    teléfono, siendo los más valiosos que tuvimos y siendo WhatsApp el canal."""
    assert ls.normalize_phone("1153872152") == "+5491153872152"


@pytest.mark.parametrize("escrito", [
    "1153872152",           # pelado, como sale del formulario
    "11 5387-2152",         # con espacio y guion
    "011 15-5387-2152",     # con el 0 de larga distancia y el 15 de celular
    "+5491153872152",       # internacional completo
    "9 11 5387 2152",       # con el 9 pero sin el país
])
def test_todas_las_formas_de_escribirlo_son_el_mismo_numero(escrito):
    """Si no colapsan a la misma identidad, el mismo lead entra varias veces."""
    assert ls.identidad_telefono(escrito) == "+541153872152"


def test_el_link_de_whatsapp_queda_armable():
    """El punto de todo esto: poder escribirle. wa.me necesita el 9."""
    from app.agents.outbound import _wa_link
    assert _wa_link(ls.normalize_phone("1153872152")) == "https://wa.me/5491153872152"


def test_no_le_come_un_15_que_es_parte_del_numero():
    """El 15 se saca sólo si al sacarlo queda un número de largo válido."""
    assert ls.normalize_phone("1155158888") == "+5491155158888"


def test_un_numero_corto_no_se_inventa():
    assert ls.normalize_phone("1234") == ""
    assert ls.normalize_phone("hola que tal") == ""


def test_el_telefono_cargado_a_mano_tambien_se_normaliza(tmp_path, monkeypatch):
    """Pasó de verdad: se cargó el de Exequiel por el panel, quedó crudo
    (`1153872152`) y el link salió `wa.me/1153872152`, que no abre nada."""
    monkeypatch.setattr(ls, "_STORE_FILE", tmp_path / "leads.json")
    monkeypatch.setattr(ls, "_DATA_DIR", tmp_path)
    store = ls._empty_store()
    k = ls.upsert_lead(store, company="Exequiel", email="exe@hotmail.com")
    ls.save_store(store)

    ls.update_lead(k, {"phone": "1153872152"})
    assert ls.load_store()["leads"][k]["phone"] == "+5491153872152"


def test_si_no_se_puede_normalizar_no_se_pierde(tmp_path, monkeypatch):
    """Peor que un número raro es un número que desaparece."""
    monkeypatch.setattr(ls, "_STORE_FILE", tmp_path / "leads.json")
    monkeypatch.setattr(ls, "_DATA_DIR", tmp_path)
    store = ls._empty_store()
    k = ls.upsert_lead(store, company="Raro", email="raro@x.com")
    ls.save_store(store)

    ls.update_lead(k, {"phone": "+1 305 555 1234"})
    assert ls.load_store()["leads"][k]["phone"] == "+1 305 555 1234"


# ── no crear el duplicado ──

def _store():
    return {"version": 1, "leads": {}}


def test_la_misma_empresa_por_telefono_y_despues_por_mail_es_un_solo_lead():
    """Es exactamente lo que pasó con Zarcam."""
    s = _store()
    k1 = ls.upsert_lead(s, company="Zarcam Logística S.A.", phone="+543487576000")
    k2 = ls.upsert_lead(s, company="Zarcam Logística", email="info@zarcam.com.ar",
                        phone="+5493487576000")
    assert len(s["leads"]) == 1, f"se duplicó: {list(s['leads'])}"
    assert k1 == k2
    # y el mail nuevo se guardó en el lead que ya existía
    assert s["leads"][k1]["email"] == "info@zarcam.com.ar"


def test_el_sufijo_societario_no_hace_dos_empresas():
    """«Racer SRL» y «Racer S.R.L.» son la misma. Estaban las dos en el pipeline."""
    s = _store()
    ls.upsert_lead(s, company="Racer SRL")
    ls.upsert_lead(s, company="Racer S.R.L.")
    assert len(s["leads"]) == 1


def test_dos_empresas_distintas_siguen_siendo_dos():
    """El dedup no puede juntar lo que no va junto."""
    s = _store()
    ls.upsert_lead(s, company="Metalúrgica Llamas", email="a@llamas.com")
    ls.upsert_lead(s, company="Metalúrgica Finke", email="b@finke.com")
    assert len(s["leads"]) == 2


def test_no_pisa_el_estado_del_lead_que_ya_existia():
    s = _store()
    k = ls.upsert_lead(s, company="Data Trace", email="info@datatrace.com.ar")
    s["leads"][k]["state"] = "respondió"
    ls.upsert_lead(s, company="Data Trace Argentina SRL", email="info@datatrace.com.ar")
    assert s["leads"][k]["state"] == "respondió"


# ── limpiar los que ya están duplicados ──

def test_la_fusion_conserva_la_respuesta_y_borra_el_otro():
    """Lo crítico: el registro que tiene la respuesta no se puede perder."""
    s = _store()
    s["leads"] = {
        "tel:+543487576000": {"key": "tel:+543487576000", "company": "Zarcam Logística S.A.",
                              "phone": "+543487576000", "state": "contactado",
                              "touches": [{"date": "2026-08-18"}], "last_reply_at": None},
        "info@zarcam.com.ar": {"key": "info@zarcam.com.ar", "company": "Zarcam Logística",
                               "email": "info@zarcam.com.ar", "phone": "+543487576000",
                               "state": "respondió", "touches": [{"date": "2026-09-11"}],
                               "last_reply_at": "2026-09-11T12:00:09+00:00"},
    }
    r = ls.fusionar_duplicados(s)
    assert r["borrados"] == 1
    assert len(s["leads"]) == 1
    queda = next(iter(s["leads"].values()))
    assert queda["last_reply_at"], "se perdió la respuesta"
    assert len(queda["touches"]) == 2, "se perdieron toques"
    assert queda["phone"] == "+543487576000"


def test_la_fusion_no_toca_lo_que_no_esta_duplicado():
    s = _store()
    ls.upsert_lead(s, company="Una Sola", email="x@unasola.com")
    antes = dict(s["leads"])
    assert ls.fusionar_duplicados(s)["borrados"] == 0
    assert s["leads"] == antes


# ── que una respuesta no se vuelva invisible ──

def test_el_que_contesto_y_nadie_toco_aparece():
    s = _store()
    s["leads"] = {"a": {"key": "a", "company": "Data Trace Argentina SRL",
                        "email": "info@datatrace.com.ar", "state": "respondió",
                        "touches": [{"date": "2026-09-10"}],
                        "last_reply_at": "2026-09-16T12:00:08+00:00"}}
    pend = ls.respondidos_sin_atender(s, dias=1)
    assert len(pend) == 1
    assert pend[0]["empresa"] == "Data Trace Argentina SRL"
    assert pend[0]["dias"] >= 1


def test_si_lo_tocaron_despues_ya_no_aparece():
    """Zarcam contestó el 11 y se la re-enganchó el 16: está atendida."""
    s = _store()
    s["leads"] = {"a": {"key": "a", "company": "Zarcam", "state": "respondió",
                        "touches": [{"date": "2026-09-16"}],
                        "last_reply_at": "2026-09-11T12:00:09+00:00"}}
    assert ls.respondidos_sin_atender(s, dias=1) == []


def test_el_que_ya_avanzo_a_reunion_no_es_un_pendiente():
    s = _store()
    s["leads"] = {"a": {"key": "a", "company": "X", "state": "reunión", "touches": [],
                        "last_reply_at": "2026-09-01T12:00:00+00:00"}}
    assert ls.respondidos_sin_atender(s, dias=1) == []


def test_el_que_nunca_contesto_no_es_un_pendiente():
    s = _store()
    s["leads"] = {"a": {"key": "a", "company": "X", "state": "contactado",
                        "touches": [], "last_reply_at": None}}
    assert ls.respondidos_sin_atender(s, dias=1) == []


def test_el_chief_los_pone_en_el_brief(monkeypatch):
    """No alcanza con detectarlo: si no llega al brief, sigue invisible."""
    from app.agents import chief_of_staff as cos
    monkeypatch.setattr(cos, "_respuestas_sin_atender",
                        lambda: "- **Data Trace** — contestó el 2026-09-16")
    from pathlib import Path
    fuente = (Path(cos.__file__)).read_text(encoding="utf-8")
    assert "_respuestas_sin_atender()" in fuente
    assert "CONTESTARON Y NADIE LES RESPONDIÓ" in fuente
