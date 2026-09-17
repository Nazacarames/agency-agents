"""Los agentes ya no tocan Vertex (decisión del dueño, 2026-09-16).

Vertex era lo ÚNICO de Google que factura por uso acá: Imagen, Veo y Gemini.
Gmail, Drive, Search Console, YouTube y la API de Ads son gratis y se quedan.
Google Cloud pasa a ser exclusivo de CLAMEVET.

Reemplazos: imagen y video → Higgsfield; texto → Kimi K3; mirar imágenes →
GLM 5.3 Flash. Todo por cuentas que ya teníamos.
"""
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "app"


# ── que no quede ninguna llamada viva a Vertex en los caminos migrados ──

def test_los_modulos_migrados_no_llaman_mas_a_vertex():
    for rel in ("integrations/vision.py", "integrations/reel_study.py",
                "agents/tiktok_creator.py"):
        t = (APP / rel).read_text(encoding="utf-8")
        assert "aiplatform.googleapis.com" not in t, rel
        # en vision.py y reel_study.py "Gemini" sólo puede aparecer contando la
        # historia, nunca como endpoint
        assert "generateContent" not in t, rel


def test_tiktok_creator_ya_no_usa_los_motores_de_google():
    t = (APP / "agents/tiktok_creator.py").read_text(encoding="utf-8")
    assert "veo_video" not in t
    assert "omni_video" not in t
    assert "higgsfield" in t


def test_la_cadena_de_imagenes_arranca_por_higgsfield():
    from app.config import get_settings
    assert get_settings().image_provider == "higgsfield"


def test_minimax_sigue_siendo_la_red_de_las_imagenes():
    """Sin credencial de Higgsfield las imágenes tienen que salir igual: MiniMax
    no depende de Google y estaba en la cadena desde antes."""
    t = (APP / "integrations/image_gen.py").read_text(encoding="utf-8")
    i = t.index('"higgsfield": [')
    fin = t.index("]", i)
    assert "_minimax_image" in t[i:fin], "MiniMax tiene que quedar de fallback"


# ── visión y texto por NVIDIA ──

def test_vision_se_prende_con_la_cuenta_de_nvidia(monkeypatch):
    from app.config import get_settings
    from app.integrations import vision
    s = get_settings()
    monkeypatch.setattr(s, "nvidia_api_key", "")
    monkeypatch.setattr(vision, "get_settings", lambda: s)
    assert vision.enabled() is False
    monkeypatch.setattr(s, "nvidia_api_key", "nvapi-x")
    assert vision.enabled() is True


def test_el_texto_va_por_kimi_y_las_imagenes_por_el_modelo_de_vision(monkeypatch):
    """Kimi no tiene variante multimodal en los catálogos que tenemos (verificado
    el 2026-09-16), así que mirar y escribir usan modelos distintos."""
    from app.config import get_settings
    from app.integrations import vision
    s = get_settings()
    monkeypatch.setattr(s, "nvidia_api_key", "nvapi-x")
    monkeypatch.setattr(vision, "get_settings", lambda: s)
    usados = []
    monkeypatch.setattr(vision, "_completar",
                        lambda m, proveedor, mt: usados.append(proveedor) or "ok")

    vision.synthesize("un texto", "resumilo")
    img = Path(__file__).parent / "_tmp.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)
    try:
        vision.describe([str(img)], "que ves")
    finally:
        img.unlink()

    assert usados == ["kimi", "vision"]


def test_el_proveedor_de_vision_existe_en_el_cliente():
    """Es GLM 5.3 Flash y no Llama, medido el 2026-09-17 con la misma imagen:
    llama-3.2-90b no respondio NINGUNA de 3 veces (timeout a 300 s) y
    llama-3.2-11b era rapido pero erro las dos. El flash tarda ~155 s y acierta."""
    from app.clients.nvidia import _PROVIDER_MODEL, provider_model
    from app.config import get_settings
    assert "vision" in _PROVIDER_MODEL
    assert "kimi" in _PROVIDER_MODEL
    assert provider_model("vision", get_settings()) == "z-ai/glm-5.3-flash"
    # El flash razona: sin freno la descripcion vuelve vacia.
    _, extra = _PROVIDER_MODEL["vision"]
    assert extra.get("reasoning_effort") == "low"


def test_al_video_se_le_avisa_que_son_fotos(monkeypatch, tmp_path):
    """Sin esto el modelo opina sobre música y ritmo de un video que no escuchó,
    que es exactamente lo que este sistema no puede hacer."""
    from app.config import get_settings
    from app.integrations import vision
    s = get_settings()
    monkeypatch.setattr(s, "nvidia_api_key", "nvapi-x")
    monkeypatch.setattr(vision, "get_settings", lambda: s)
    f = tmp_path / "f01.jpg"
    f.write_bytes(b"\xff\xd8\xff" + b"0" * 16)
    monkeypatch.setattr(vision, "_frames", lambda v, n=8: [f])
    visto = {}
    monkeypatch.setattr(vision, "describe",
                        lambda rutas, prompt, **k: visto.update(prompt=prompt) or "ok")

    vision.describe_video("/tmp/x.mp4", "analizá el reel")

    assert "NO tenés el audio" in visto["prompt"]
    assert "analizá el reel" in visto["prompt"]


# ── Higgsfield ──

def test_higgsfield_apagado_sin_credenciales(monkeypatch):
    from app.config import get_settings
    from app.integrations import higgsfield
    s = get_settings()
    monkeypatch.setattr(s, "higgsfield_key_id", "")
    monkeypatch.setattr(s, "higgsfield_key_secret", "")
    monkeypatch.setattr(higgsfield, "get_settings", lambda: s)
    assert higgsfield.enabled() is False
    assert higgsfield.generar_video("un prompt") == b""
    assert higgsfield.generar_imagen("un prompt") == []
    assert higgsfield.generate_and_wait("un prompt") == {}


def test_la_auth_de_higgsfield_no_es_bearer(monkeypatch):
    """Es `Key <id>:<secret>`. Con Bearer da 401 y se pierde media hora."""
    from app.config import get_settings
    from app.integrations import higgsfield
    s = get_settings()
    monkeypatch.setattr(s, "higgsfield_key_id", "id1")
    monkeypatch.setattr(s, "higgsfield_key_secret", "sec1")
    monkeypatch.setattr(higgsfield, "get_settings", lambda: s)
    h = higgsfield._headers()
    assert h["Authorization"] == "Key id1:sec1"
    assert "Mozilla" in h["User-Agent"], "sin User-Agent de browser, Cloudflare da 403"


def test_el_video_pide_audio_explicito(monkeypatch):
    """`generate_audio` viene en False por default: por eso los primeros videos
    del banco salieron mudos."""
    from app.config import get_settings
    from app.integrations import higgsfield
    s = get_settings()
    monkeypatch.setattr(s, "higgsfield_key_id", "id1")
    monkeypatch.setattr(s, "higgsfield_key_secret", "sec1")
    monkeypatch.setattr(higgsfield, "get_settings", lambda: s)
    enviado = {}
    monkeypatch.setattr(higgsfield, "_submit",
                        lambda ruta, cuerpo: enviado.update(cuerpo) or None)

    higgsfield.generar_video("naza hablando")

    assert enviado["generate_audio"] is True
    assert enviado["aspect_ratio"] == "9:16"
    # STRINGS, no números ni "1080p": así lo pide la spec oficial. Con enteros o
    # con la "p" la API rechaza cada request, y se descubriría recién el día que
    # alguien pegue la credencial.
    assert enviado["resolution"] == "1080"
    assert enviado["duration"] == "8"
    assert isinstance(enviado["duration"], str)


def test_falta_de_credito_se_distingue_de_un_error_cualquiera():
    """Sin crédito no se reintenta: reintentar no lo arregla y ensucia el diagnóstico."""
    from app.integrations.higgsfield import _sin_credito
    assert _sin_credito({}, 402) is True
    assert _sin_credito({"error": "insufficient credits"}, 400) is True
    assert _sin_credito({"error": "bad prompt"}, 400) is False


# ── verificado contra la OpenAPI oficial, no contra la memoria ──

def test_las_rutas_salen_de_la_spec_oficial():
    """Escritas de memoria estaban mal las cuatro: host api.* en vez de platform.*,
    /veo3.1/text-to-video, soul/v2/standard y resolution "1080p". Se corrigieron
    leyendo la OpenAPI 2.0.0 que ya estaba bajada en Downloads."""
    import ast
    from app.integrations import higgsfield
    assert higgsfield.BASE == "https://platform.higgsfield.ai"

    # Se miran los literales del CÓDIGO, no el archivo entero: el docstring
    # nombra las rutas viejas justamente para explicar por qué estaban mal, y un
    # grep crudo se tropieza con esa explicación.
    arbol = ast.parse((APP / "integrations/higgsfield.py").read_text(encoding="utf-8"))
    literales = {n.value for n in ast.walk(arbol)
                 if isinstance(n, ast.Constant) and isinstance(n.value, str)
                 and "\n" not in n.value}
    for malo in ("https://api.higgsfield.ai", "veo3.1/text-to-video",
                 "higgsfield-ai/soul/v2/standard"):
        assert malo not in literales, f"{malo} sigue usándose en el código"
    for bueno in ("veo3.1", "veo3.1/reference-to-video",
                  "higgsfield-ai/soul/standard"):
        assert bueno in literales, f"falta la ruta {bueno}"


def test_con_referencias_usa_el_endpoint_que_conserva_la_cara(monkeypatch):
    """/veo3.1/reference-to-video toma image_urls. Es lo que mantiene la cara de
    Nazareno entre clips: sin eso cada video le inventa una persona distinta."""
    from app.config import get_settings
    from app.integrations import higgsfield
    s = get_settings()
    monkeypatch.setattr(s, "higgsfield_key_id", "id1")
    monkeypatch.setattr(s, "higgsfield_key_secret", "sec1")
    monkeypatch.setattr(higgsfield, "get_settings", lambda: s)
    visto = {}
    monkeypatch.setattr(higgsfield, "_submit",
                        lambda ruta, cuerpo: visto.update(ruta=ruta, **cuerpo) or None)

    higgsfield.generar_video("naza", referencias=["https://x/1.png"])
    assert visto["ruta"] == "veo3.1/reference-to-video"
    assert visto["image_urls"] == ["https://x/1.png"]

    visto.clear()
    higgsfield.generar_video("naza")
    assert visto["ruta"] == "veo3.1"
    assert "image_urls" not in visto


def test_las_imagenes_van_en_un_solo_pedido(monkeypatch):
    """La API tiene num_images: pedirlas de a una gastaba un request por imagen."""
    from app.config import get_settings
    from app.integrations import higgsfield
    s = get_settings()
    monkeypatch.setattr(s, "higgsfield_key_id", "id1")
    monkeypatch.setattr(s, "higgsfield_key_secret", "sec1")
    monkeypatch.setattr(higgsfield, "get_settings", lambda: s)
    pedidos = []
    monkeypatch.setattr(higgsfield, "_submit",
                        lambda ruta, cuerpo: pedidos.append(cuerpo) or None)

    higgsfield.generar_imagen("un gato", aspect_ratio="9:16", n=4)

    assert len(pedidos) == 1, "un request, no cuatro"
    assert pedidos[0]["num_images"] == 4
    assert pedidos[0]["aspect_ratio"] == "9:16"


def test_un_aspect_ratio_que_la_api_no_acepta_cae_a_uno_valido(monkeypatch):
    from app.config import get_settings
    from app.integrations import higgsfield
    s = get_settings()
    monkeypatch.setattr(s, "higgsfield_key_id", "id1")
    monkeypatch.setattr(s, "higgsfield_key_secret", "sec1")
    monkeypatch.setattr(higgsfield, "get_settings", lambda: s)
    pedidos = []
    monkeypatch.setattr(higgsfield, "_submit",
                        lambda ruta, cuerpo: pedidos.append(cuerpo) or None)

    higgsfield.generar_imagen("x", aspect_ratio="7:3", n=1)
    assert pedidos[0]["aspect_ratio"] == "1:1"


def test_tiktok_creator_le_pasa_las_referencias():
    t = (APP / "agents/tiktok_creator.py").read_text(encoding="utf-8")
    assert "reference_image_urls=refs" in t
