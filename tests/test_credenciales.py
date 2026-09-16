"""El llavero: que se pueda saber qué credencial anda y qué se rompe al rotarla,
sin que el valor de ninguna se escape por la respuesta.

Contexto: una sola service account con scope `cloud-platform` la usan imágenes,
video, Drive, Search Console y YouTube. Darle identidad propia a cada agente está
bloqueado por la política de la organización (no se pueden crear claves nuevas),
así que lo que queda es conocer el radio de explosión antes de rotar y enterarse
cuando una credencial se muere, en vez de degradar en silencio.
"""
import pytest

from app.integrations import credenciales


def test_nunca_devuelve_el_valor_de_una_credencial(monkeypatch):
    from app.config import get_settings
    s = get_settings()
    secreto = "ESTO-ES-UN-SECRETO-QUE-NO-PUEDE-SALIR"
    monkeypatch.setattr(s, "google_service_account_json", secreto)
    monkeypatch.setattr(s, "meta_page_token", secreto)
    monkeypatch.setattr(s, "database_url", secreto)
    monkeypatch.setattr(credenciales, "get_settings", lambda: s)

    texto = repr(credenciales.estado(verificar=False))
    assert secreto not in texto


def test_dice_quien_usa_cada_credencial_y_que_se_rompe():
    for fila in credenciales.estado():
        assert fila["usan"], f"{fila['clave']} sin dueños: no se puede rotar a ciegas"
        assert fila["rompe"], f"{fila['clave']} sin consecuencia declarada"
        assert fila["env"], f"{fila['clave']} sin variable de entorno"


def test_una_credencial_ausente_no_se_verifica_ni_cuenta_como_caida(monkeypatch):
    """Ausente ≠ caída. Si no está configurada, el agente que la usa está apagado
    a propósito; gritar por eso todos los días entrena a ignorar los avisos."""
    from app.config import get_settings
    s = get_settings()
    monkeypatch.setattr(s, "google_service_account_json", "")
    monkeypatch.setattr(credenciales, "get_settings", lambda: s)
    monkeypatch.setattr(credenciales, "_vertex",
                        lambda s: (_ for _ in ()).throw(
                            AssertionError("no tenía que verificar lo que no está")))
    fila = [f for f in credenciales.estado(verificar=True) if f["clave"] == "vertex_sa"][0]
    assert fila["presente"] is False
    assert fila["estado"] == "ausente"
    assert credenciales.caidas(credenciales.estado(verificar=False)) == []


def test_una_clave_revocada_se_reporta_como_caida(monkeypatch):
    from app.config import get_settings
    s = get_settings()
    monkeypatch.setattr(s, "google_service_account_json", '{"client_email": "x@y.iam"}')
    monkeypatch.setattr(credenciales, "get_settings", lambda: s)
    monkeypatch.setattr(credenciales, "_vertex",
                        lambda s: ("fail", "RefreshError: invalid_grant"))
    # El verificador vive dentro de INVENTARIO, así que se parchea ahí.
    monkeypatch.setitem(credenciales.INVENTARIO[0], "verificar", credenciales._vertex)

    filas = credenciales.estado(verificar=True)
    vertex = [f for f in filas if f["clave"] == "vertex_sa"][0]
    assert vertex["estado"] == "fail"
    assert "invalid_grant" in vertex["detalle"]
    assert [c["clave"] for c in credenciales.caidas(filas)] == ["vertex_sa"]


def test_sin_verificador_no_se_inventa_un_ok(monkeypatch):
    """Las que no tienen forma barata de probarse dicen `sin_verificador`, no `ok`.
    Un verde que nadie midió es peor que no tener semáforo."""
    from app.config import get_settings
    s = get_settings()
    monkeypatch.setattr(s, "tiktok_client_key", "k")
    monkeypatch.setattr(s, "tiktok_client_secret", "s")
    monkeypatch.setattr(credenciales, "get_settings", lambda: s)
    fila = [f for f in credenciales.estado(verificar=True) if f["clave"] == "tiktok"][0]
    assert fila["estado"] == "sin_verificador"


def test_el_radio_de_explosion_de_la_service_account_esta_completo():
    """Es la llave que abre todo el proyecto de Google Cloud: si la lista de quién
    la usa queda corta, rotarla rompe algo sin aviso.

    Desde el 2026-09-16 la lista es MÁS CORTA a propósito: se le sacaron Imagen,
    Veo y Gemini (lo único que facturaba) y quedó sólo con APIs gratis.
    """
    r = credenciales.radio_de_explosion("vertex_sa")
    usan = " ".join(r["usan"]).lower()
    for esperado in ("drive", "search_console", "youtube"):
        assert esperado in usan, f"falta {esperado} en el radio de explosión"
    for fuera in ("image_gen", "veo", "reel_study"):
        assert fuera not in usan, f"{fuera} ya no usa la service account"
    assert "cloud-platform" in r["alcance"]


def test_radio_de_explosion_de_algo_que_no_existe():
    with pytest.raises(KeyError):
        credenciales.radio_de_explosion("no_existe")


def test_omitir_saltea_la_verificacion(monkeypatch):
    """El watchdog ya hace su propio refresh de Gmail; sin `omitir` pediría dos
    refresh del mismo token en cada corrida."""
    from app.config import get_settings
    s = get_settings()
    monkeypatch.setattr(s, "gmail_client_id", "id")
    monkeypatch.setattr(s, "gmail_client_secret", "sec")
    monkeypatch.setattr(s, "gmail_refresh_token", "tok")
    monkeypatch.setattr(credenciales, "get_settings", lambda: s)
    monkeypatch.setattr(credenciales, "_gmail",
                        lambda s: (_ for _ in ()).throw(
                            AssertionError("no tenía que verificar Gmail dos veces")))
    monkeypatch.setitem(
        [i for i in credenciales.INVENTARIO if i["clave"] == "gmail_oauth"][0],
        "verificar", credenciales._gmail)
    filas = credenciales.estado(verificar=True, omitir={"gmail_oauth"})
    gmail = [f for f in filas if f["clave"] == "gmail_oauth"][0]
    assert gmail["estado"] == "sin_verificar"
