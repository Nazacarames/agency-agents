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
