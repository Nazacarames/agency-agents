"""El único gasto de Google Cloud es CLAMEVET (2026-09-17).

El dato que lo motivó, de la facturación del 1 al 16 de septiembre:

    Gemini on Agent Platform     US$ 26,93
    Veo on Agent Platform        US$ 22,40
    Agent Platform Model Garden  US$ 10,10
    Vertex Embeddings API        US$  0,01   <- esto es CLAMEVET

O sea: CLAMEVET gasta un centavo y lo demás son los agentes. La proyección del
mes era US$ 114,65 contra un presupuesto que es hosting + Workspace y nada más.

Por qué el freno va en `veo_video._token()` y no en una bandera por camino: los
CUATRO caminos de pago de este servicio (Veo, Omni, Nano Banana Pro, Imagen 4)
piden su token ahí. Una bandera por camino es como se escaparon 4 mensajes
cuando la pausa de un cliente tapaba uno de seis caminos.

Por qué NO se borra la credencial de Railway: la misma service account la usan
Search Console y YouTube, que son gratis y se usan.
"""
import pytest

from app.config import get_settings
from app.integrations import image_gen, veo_video


@pytest.fixture
def con_credencial(monkeypatch):
    """Con la llave puesta, que es el estado real: está en Railway porque la
    necesitan Search Console y YouTube."""
    s = get_settings()
    monkeypatch.setattr(s, "google_service_account_json", '{"project_id": "x"}')
    monkeypatch.setattr(veo_video, "get_settings", lambda: s)
    return s


def test_esta_frenado_por_defecto():
    """Si el default fuera True, un deploy nuevo o un env sin la variable vuelve
    a facturar sin que nadie lo decida."""
    assert get_settings().google_cloud_pago is False


def test_tener_la_llave_no_alcanza_para_gastar(con_credencial, monkeypatch):
    """Antes `enabled()` decía True con sólo existir la credencial. Ése era el
    agujero: lo que se apagó el 2026-09-16 fue una bandera, no la llave."""
    monkeypatch.setattr(con_credencial, "google_cloud_pago", False)
    assert veo_video.enabled() is False


def test_el_token_de_pago_levanta_y_no_devuelve_vacio(con_credencial, monkeypatch):
    """Vacío haría fallar la llamada con un 401 confuso a mitad de camino."""
    monkeypatch.setattr(con_credencial, "google_cloud_pago", False)
    with pytest.raises(RuntimeError, match="CLAMEVET"):
        veo_video._token()


def test_se_puede_volver_a_prender_sin_tocar_codigo(con_credencial, monkeypatch):
    monkeypatch.setattr(con_credencial, "google_cloud_pago", True)
    assert veo_video.enabled() is True


def test_omni_tambien_queda_frenado(con_credencial, monkeypatch):
    """Omni llama a Veo: si mirara otra bandera, se escapaba por ahí."""
    from app.integrations import omni_video
    monkeypatch.setattr(con_credencial, "google_cloud_pago", False)
    assert omni_video.enabled() is False


def test_las_dos_imagenes_pagas_piden_el_token_frenado(con_credencial, monkeypatch):
    """Nano Banana Pro e Imagen 4 no tienen bandera propia: dependen de que el
    token les diga que no."""
    monkeypatch.setattr(con_credencial, "google_cloud_pago", False)
    monkeypatch.setattr(image_gen, "get_settings", lambda: con_credencial)
    for fn in (image_gen._nano_banana, image_gen._vertex_imagen):
        with pytest.raises(RuntimeError, match="CLAMEVET"):
            fn("un perro", "1:1", 1)


def test_un_provider_desconocido_no_cae_en_google_pago():
    """Un typo en IMAGE_PROVIDER mandaba a facturar: el default del `.get` era la
    cadena nano -> vertex, que son los dos de Google."""
    import inspect
    fuente = inspect.getsource(image_gen)
    i = fuente.index(".get(provider,")
    default = fuente[i:i + 200]
    assert "_nano_banana" not in default, "el default volvió a ser Google pago"
    assert "_vertex_imagen" not in default


def test_lo_gratis_no_se_rompe():
    """Search Console y YouTube usan la MISMA credencial y no pasan por el token
    de pago. Si alguien los enchufa a `veo_video._token()`, se apagan solos."""
    from pathlib import Path
    app = Path(__file__).resolve().parents[1] / "app"
    for archivo in ("integrations/search_console.py", "integrations/youtube_client.py"):
        t = (app / archivo).read_text(encoding="utf-8")
        assert "veo_video" not in t, f"{archivo} quedaría frenado con el gasto"
