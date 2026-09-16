"""Generación de video FRENADA: los shorts salen del banco ya generado.

Decisión del dueño (2026-09-16): "usemos esos videos generados anteriormente, no
generemos más por el momento, hasta nuevo aviso". Con `video_gen_enabled=False`
el sistema no llama a Higgsfield ni gasta un crédito.
"""
import json

import pytest

from app.integrations import video_bank as vb


@pytest.fixture(autouse=True)
def banco_aislado(tmp_path, monkeypatch):
    """Cada test con su propio banco: nada de tocar el de verdad."""
    monkeypatch.setattr(vb, "_FILE", tmp_path / "video-bank.json")
    return tmp_path


def _pieza(prompt, copy="", media=""):
    it = vb.agregar(prompt, copy=copy)
    if media and it:
        vb.marcar_listo(it["n"], media)
    return it


PROMPT = "Vertical 9:16 cinematic commercial. Un local de barrio de noche con luz cálida."


# ── el interruptor ──

def test_la_generacion_esta_apagada_por_defecto():
    from app.config import get_settings
    assert get_settings().video_gen_enabled is False


def test_con_la_generacion_apagada_no_se_llama_a_higgsfield(monkeypatch, tmp_path):
    from app.config import get_settings
    from app.agents import tiktok_creator as tc
    from app.integrations import higgsfield

    s = get_settings()
    monkeypatch.setattr(s, "video_gen_enabled", False)
    monkeypatch.setattr(higgsfield, "generate_and_wait",
                        lambda *a, **k: pytest.fail("no tenía que generar"))

    clip = tmp_path / "banco_x.mp4"
    clip.write_bytes(b"0" * 10)
    agente = tc.TikTokCreatorAgent.__new__(tc.TikTokCreatorAgent)
    monkeypatch.setattr(agente, "_clip_del_banco", lambda: (clip, "un copy"))

    texto, ruta = agente._add_nazareno_clip("VEO_FRASE: lo que sea")

    assert ruta == clip
    assert agente._veo_frase == "un copy"


# ── el préstamo rota ──

def test_presta_el_clip_menos_usado():
    """Sin rotación el sistema publicaría siempre el mismo video."""
    a = _pieza(PROMPT + " uno", media="/media/banco_a.mp4")
    b = _pieza(PROMPT + " dos", media="/media/banco_b.mp4")

    assert vb.tomar_para_short()["n"] == a["n"]
    assert vb.tomar_para_short()["n"] == b["n"]
    assert vb.tomar_para_short()["n"] == a["n"], "vuelve al primero, no se queda en uno"


def test_lleva_la_cuenta_de_usos():
    _pieza(PROMPT, media="/media/banco_a.mp4")
    vb.tomar_para_short()
    vb.tomar_para_short()
    item = vb.tomar_para_short()
    assert item["usos"] == 3
    assert item["ultimo_uso"]


def test_una_pieza_sin_archivo_no_se_presta():
    """`agregar` deja la pieza PENDIENTE sin media: prestarla daría un short sin clip."""
    _pieza(PROMPT)                      # sin media
    assert vb.tomar_para_short() is None


def test_banco_vacio_no_rompe():
    assert vb.tomar_para_short() is None


# ── el subtítulo ──

def test_el_subtitulo_sale_del_clip_y_no_de_lo_que_escribio_el_modelo(monkeypatch, tmp_path):
    """El clip del banco ya trae SU voz diciendo otra cosa. Subtitular la frase
    nueva sería poner en pantalla palabras que nadie dice."""
    from app.config import get_settings
    from app.agents import tiktok_creator as tc

    s = get_settings()
    monkeypatch.setattr(s, "video_gen_enabled", False)
    clip = tmp_path / "banco_y.mp4"
    clip.write_bytes(b"0" * 10)
    agente = tc.TikTokCreatorAgent.__new__(tc.TikTokCreatorAgent)
    monkeypatch.setattr(agente, "_clip_del_banco",
                        lambda: (clip, "el copy del clip"))

    agente._add_nazareno_clip("VEO_FRASE: una frase totalmente distinta")

    assert agente._veo_frase == "el copy del clip"
    assert "totalmente distinta" not in agente._veo_frase


def test_sin_copy_no_se_inventa_subtitulo(monkeypatch, tmp_path):
    from app.config import get_settings
    from app.agents import tiktok_creator as tc
    s = get_settings()
    monkeypatch.setattr(s, "video_gen_enabled", False)
    agente = tc.TikTokCreatorAgent.__new__(tc.TikTokCreatorAgent)
    monkeypatch.setattr(agente, "_clip_del_banco", lambda: (tmp_path / "x.mp4", ""))
    agente._add_nazareno_clip("VEO_FRASE: algo")
    assert agente._veo_frase == "", "mejor sin subtítulo que con uno que miente"


# ── el carril UGC también respeta el freno ──

def test_el_ugc_no_genera_con_el_freno_puesto(monkeypatch):
    from app.config import get_settings
    from app.integrations import ugc_video
    s = get_settings()
    monkeypatch.setattr(s, "video_gen_enabled", False)
    assert ugc_video.enabled() is False


def test_el_ugc_ya_no_usa_google():
    from pathlib import Path
    t = (Path(__file__).resolve().parents[1] / "app" / "integrations"
         / "ugc_video.py").read_text(encoding="utf-8")
    assert "veo_video" not in t
    assert "omni_video" not in t
