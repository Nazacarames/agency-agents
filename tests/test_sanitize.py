"""
Tests del sanitizador de output del modelo: saca caracteres CJK (chino/japonés/
coreano) que MiniMax a veces inyecta, sin tocar español/tildes/emojis.
"""
from app.agents._common import sanitize_model_text


def test_strips_chinese_and_cleans_gap():
    txt = "Logística de回收 / gestión de envases"
    out, n = sanitize_model_text(txt)
    assert n == 2
    assert "回" not in out and "收" not in out
    assert "  " not in out  # el hueco no deja doble espacio


def test_preserves_spanish_accents_and_emoji():
    txt = "Cotización rápida con ñ y emoji 🚀 — sin cambios"
    out, n = sanitize_model_text(txt)
    assert n == 0
    assert out == txt


def test_strips_japanese_and_korean():
    out, n = sanitize_model_text("test ひら y 가나 fin")
    assert n == 4
    assert "test  y  fin".replace("  ", " ") in out or "test y fin" in out


def test_removes_space_before_punctuation():
    # "rápida 见 a tiempo, sin" → al sacar el char no debe quedar " ,"
    out, n = sanitize_model_text("rápida见, a tiempo")
    assert n == 1
    assert " ," not in out


def test_empty_and_none_safe():
    assert sanitize_model_text("") == ("", 0)
    assert sanitize_model_text(None) == (None, 0)


# ── Voseo: el tuteo inequívoco que se le escapa al modelo ──
from app.agents._common import vosear


def test_pasa_a_voseo_el_tuteo_inequivoco():
    out, n = vosear("Si necesitas más clientes, contáctanos. ¿Tienes WhatsApp Business?")
    assert out == "Si necesitás más clientes, contactanos. ¿Tenés WhatsApp Business?"
    assert n == 3


def test_respeta_mayusculas():
    assert vosear("ESCRÍBENOS HOY")[0] == "ESCRIBINOS HOY"
    assert vosear("Tú decidís")[0] == "Vos decidís"


def test_no_toca_lo_que_puede_ser_otra_cosa():
    """«la prueba», «él descubre», «tu negocio», «el área de TI» y lo que ya
    está en voseo quedan igual."""
    txt = ("La prueba gratis dura 30 días; el dueño descubre que tu negocio pierde "
           "consultas. El área de TI ya lo sabe. Vos tenés el control y estás a tiempo.")
    out, n = vosear(txt)
    assert out == txt and n == 0


def test_no_toca_urls_ni_hashtags():
    txt = "Mirá https://ejemplo.com/tienes y #puedes"
    assert vosear(txt)[0] == txt
