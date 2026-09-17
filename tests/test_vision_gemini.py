"""Mirar vuelve a ser rápido, y el video vuelve a tener audio (2026-09-17).

Contexto, porque es fácil confundirlo: el 2026-09-16 se sacó **Vertex** de los
agentes por facturar. Esto es **AI Studio**, que es otra cosa: una API key suelta,
sin tarjeta y sin facturación. Entra sólo para MIRAR.

Lo que devuelve y habíamos perdido: analizar el VIDEO NATIVO con audio. Medido
con el mismo clip, acertó que no tiene audio — o sea que lo escuchó de verdad.
"""
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "app"


@pytest.fixture
def con_ai_studio(monkeypatch):
    from app.config import get_settings
    from app.integrations import gemini_free
    s = get_settings()
    monkeypatch.setattr(s, "gemini_api_key", "AQ.loquesea")
    monkeypatch.setattr(gemini_free, "get_settings", lambda: s)
    return s


@pytest.fixture
def sin_ai_studio(monkeypatch):
    from app.config import get_settings
    from app.integrations import gemini_free
    s = get_settings()
    monkeypatch.setattr(s, "gemini_api_key", "")
    monkeypatch.setattr(gemini_free, "get_settings", lambda: s)
    return s


# ── que no se confunda con Vertex ──

def test_no_usa_vertex_ni_service_account():
    """Si alguien lo cablea con la service account volvemos a facturar, que es
    exactamente lo que se decidió sacar."""
    t = (APP / "integrations/gemini_free.py").read_text(encoding="utf-8")
    assert "aiplatform.googleapis.com" not in t
    assert "service_account" not in t
    assert "generativelanguage.googleapis.com" in t


def test_apagado_sin_key(sin_ai_studio):
    from app.integrations import gemini_free
    assert gemini_free.enabled() is False
    assert gemini_free.describir_imagenes(["x.png"], "que ves") == ""
    assert gemini_free.describir_video("x.mp4", "que ves") == ""


def test_le_apaga_el_pensamiento(con_ai_studio, monkeypatch):
    """Los flash de Gemini piensan y ese pensamiento sale del MISMO presupuesto
    de tokens que la respuesta: sin apagarlo vuelve truncada o vacía. Ya nos pasó
    en CLAMEVET y con GLM."""
    from app.integrations import gemini_free
    visto = {}

    class _R:
        status_code = 200
        text = ""
        def json(self):
            return {"candidates": [{"content": {"parts": [{"text": "ok"}]}}]}

    class _C:
        def __init__(self, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def post(self, url, params=None, json=None):
            visto.update(json or {})
            return _R()

    monkeypatch.setattr(gemini_free.httpx, "Client", _C)
    gemini_free._generar([{"text": "hola"}], 500)
    cfg = visto["generationConfig"]
    assert cfg["thinkingConfig"]["thinkingBudget"] == 0


def test_prueba_varios_modelos_cuando_se_satura(con_ai_studio, monkeypatch):
    """El tier gratis devuelve 503 "high demand" de verdad: pasó en una de las
    pruebas. Sin cadena, esa llamada se perdía."""
    from app.integrations import gemini_free
    intentos = []

    class _R:
        def __init__(self, code, txt=""):
            self.status_code, self._t = code, txt
            self.text = "high demand"
        def json(self):
            return {"candidates": [{"content": {"parts": [{"text": self._t}]}}]}

    class _C:
        def __init__(self, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def post(self, url, params=None, json=None):
            modelo = url.split("/models/")[1].split(":")[0]
            intentos.append(modelo)
            return _R(200, "descripcion") if len(intentos) > 1 else _R(503)

    monkeypatch.setattr(gemini_free.httpx, "Client", _C)
    assert gemini_free._generar([{"text": "x"}], 300) == "descripcion"
    assert len(intentos) == 2, "tiene que probar el siguiente modelo"
    assert intentos[0] == gemini_free.MODELOS[0]


def test_un_video_muy_pesado_no_se_manda(con_ai_studio, tmp_path):
    """El inlineData tiene techo: mandarlo igual es gastar el intento."""
    from app.integrations import gemini_free
    v = tmp_path / "gordo.mp4"
    v.write_bytes(b"0" * (gemini_free.MAX_INLINE + 10))
    assert gemini_free.describir_video(str(v), "que ves") == ""


# ── la cadena en vision.py ──

def test_el_video_va_NATIVO_antes_que_por_frames(con_ai_studio, monkeypatch, tmp_path):
    """Lo importante de todo esto: con audio y movimiento, no fotos sueltas."""
    from app.integrations import vision, gemini_free
    v = tmp_path / "clip.mp4"
    v.write_bytes(b"0" * 100)
    monkeypatch.setattr(gemini_free, "describir_video",
                        lambda ruta, prompt, mt=1800: "lo vi y lo escuche")
    monkeypatch.setattr(vision, "_frames",
                        lambda *a, **k: pytest.fail("no tenía que sacar frames"))

    assert vision.describe_video(str(v), "analiza") == "lo vi y lo escuche"


def test_si_ai_studio_no_contesta_el_video_cae_a_frames(con_ai_studio, monkeypatch, tmp_path):
    from app.config import get_settings
    from app.integrations import vision, gemini_free
    s = get_settings()
    monkeypatch.setattr(s, "nvidia_api_key", "nvapi-x")
    monkeypatch.setattr(vision, "get_settings", lambda: s)
    v = tmp_path / "clip.mp4"
    v.write_bytes(b"0" * 100)
    f = tmp_path / "f01.jpg"
    f.write_bytes(b"\xff\xd8\xff" + b"0" * 10)
    monkeypatch.setattr(gemini_free, "describir_video", lambda *a, **k: "")
    monkeypatch.setattr(vision, "_frames", lambda *a, **k: [f])
    visto = {}
    monkeypatch.setattr(vision, "describe",
                        lambda rutas, prompt, **k: visto.update(p=prompt) or "por frames")

    assert vision.describe_video(str(v), "analiza") == "por frames"
    assert "NO tenés el audio" in visto["p"], "si son fotos, hay que avisarlo"


def test_las_imagenes_prueban_ai_studio_primero(con_ai_studio, monkeypatch, tmp_path):
    from app.integrations import vision, gemini_free
    img = tmp_path / "a.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 20)
    monkeypatch.setattr(gemini_free, "describir_imagenes",
                        lambda rutas, prompt, mt=1800: "lo vio gemini")
    monkeypatch.setattr(vision, "_completar",
                        lambda *a, **k: pytest.fail("no tenía que ir a NVIDIA"))

    assert vision.describe([str(img)], "que ves") == "lo vio gemini"


def test_sin_ai_studio_las_imagenes_siguen_por_nvidia(sin_ai_studio, monkeypatch, tmp_path):
    """Quitar la key no puede dejar ciego al sistema."""
    from app.config import get_settings
    from app.integrations import vision
    s = get_settings()
    monkeypatch.setattr(s, "nvidia_api_key", "nvapi-x")
    monkeypatch.setattr(vision, "get_settings", lambda: s)
    img = tmp_path / "a.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 20)
    monkeypatch.setattr(vision, "_completar",
                        lambda m, proveedor, mt: f"por {proveedor}")

    assert vision.describe([str(img)], "que ves") == "por vision"
