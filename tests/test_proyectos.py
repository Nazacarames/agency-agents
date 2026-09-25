"""La sección de Proyectos: los sistemas que operamos, su salud y su auditoría.

Lo que se protege acá es lo que ya se rompió antes en este mismo sistema:
  · Un servicio que contesta 200 mientras su base está muerta NO está sano
    (la lección del healthcheck que mentía).
  · Un proyecto caído no puede voltear el panel de los otros tres.
  · Los hallazgos los detecta CÓDIGO, no el modelo (el "H1 vacío" fue falso
    22 días porque nadie lo verificó contra la realidad).
  · Las credenciales no se verifican en el cierre diario: eso cuesta segundos
    por proveedor y el consentimiento de Gmail está en Testing.
"""
import pytest

from app.integrations import proyectos


class _Resp:
    def __init__(self, code=200, cuerpo=None, revienta=False):
        self.status_code = code
        self._cuerpo = cuerpo if cuerpo is not None else {}
        self._revienta = revienta

    def json(self):
        if self._revienta:
            raise ValueError("no es JSON")
        return self._cuerpo


def _cliente(respuestas):
    """Un httpx.Client falso: `respuestas` mapea url -> _Resp o Exception."""
    class _C:
        def __init__(self, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url, headers=None):
            r = respuestas.get(url, _Resp(404))
            if isinstance(r, Exception):
                raise r
            return r
    return _C


# ── la sonda ──

def test_un_200_con_la_base_muerta_no_es_estar_sano(monkeypatch):
    """CLAMEVET devuelve {"ok":false,"db":false}. El contenedor contesta, pero no
    puede leer un solo dato. Darlo por sano es el healthcheck mintiendo."""
    p = {"sonda": "http://x/health"}
    monkeypatch.setattr(proyectos.httpx, "Client",
                        _cliente({"http://x/health": _Resp(200, {"ok": False, "db": False})}))
    assert proyectos._sondear(p)["estado"] == "degradado"


def test_una_sonda_que_no_devuelve_json_igual_cuenta_como_viva():
    """La landing devuelve HTML. No tener JSON no es estar caído."""
    import app.integrations.proyectos as m
    original = m.httpx.Client
    m.httpx.Client = _cliente({"http://x/": _Resp(200, revienta=True)})
    try:
        assert m._sondear({"sonda": "http://x/"})["estado"] == "ok"
    finally:
        m.httpx.Client = original


def test_un_proyecto_caido_no_voltea_a_los_otros(monkeypatch):
    """Si la excepción escapa, el panel entero queda en blanco justo cuando más
    se lo necesita."""
    monkeypatch.setattr(proyectos.httpx, "Client",
                        _cliente({}))  # todo 404 → todos caídos
    salida = proyectos.salud()
    assert len(salida) == len(proyectos.PROYECTOS)
    remotos = [s for s in salida if s["id"] != "agentes"]
    assert all(s["salud"]["estado"] == "caido" for s in remotos)


def test_este_servicio_no_se_pega_a_si_mismo(monkeypatch):
    """Se colgaba de verdad: el pedido a `/healthz` esperaba al worker que justo
    estaba atendiendo `/api/proyectos`. 20 s de ReadTimeout y el panel diciendo
    "los agentes no responden" desde adentro de los agentes."""
    monkeypatch.setattr(proyectos.httpx, "Client",
                        lambda **k: pytest.fail("no tenía que salir a la red"))
    agentes = next(p for p in proyectos.PROYECTOS if p["id"] == "agentes")
    assert proyectos._sondear(agentes)["estado"] == "ok"
    assert proyectos._sondear(agentes)["ms"] == 0


def test_sin_secreto_no_pide_el_resumen(monkeypatch):
    """Sin `panel_secret` el pedido saldría sin credencial y volvería 401. Mejor
    ni salir: el proyecto igual se muestra con su salud."""
    from app.config import get_settings
    s = get_settings()
    monkeypatch.setattr(s, "panel_secret", "")
    monkeypatch.setattr(proyectos, "get_settings", lambda: s)
    monkeypatch.setattr(proyectos.httpx, "Client",
                        lambda **k: pytest.fail("no tenía que salir a la red"))
    assert proyectos._resumen_remoto({"resumen": "http://x/health/resumen"}) == {}


def test_el_resumen_va_con_el_secreto_de_panel(monkeypatch):
    from app.config import get_settings
    visto = {}

    class _C:
        def __init__(self, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def get(self, url, headers=None):
            visto.update(headers or {})
            return _Resp(200, {"empresas": 3})

    s = get_settings()
    monkeypatch.setattr(s, "panel_secret", "sec-123")
    monkeypatch.setattr(proyectos, "get_settings", lambda: s)
    monkeypatch.setattr(proyectos.httpx, "Client", _C)

    assert proyectos._resumen_remoto({"resumen": "http://x/h"}) == {"empresas": 3}
    assert visto["X-Panel-Secret"] == "sec-123"
    assert "Authorization" not in visto


# ── la auditoría ──

def test_el_asistente_mudo_es_lo_primero_que_se_dice():
    """El 2026-09-24 Google cortó Vertex por facturación impaga: el asistente de
    CLAMEVET estuvo mudo toda la mañana con TODOS los demás números sanos, y el
    panel lo mostraba en verde. Nos enteramos por el cliente."""
    h = proyectos._auditar_clamevet(
        {"documentos_con_error": 0, "documentos": 10, "fragmentos": 900,
         "empresas": 5, "socios": 5, "consultas_7d": 12,
         "asistente_ok": False, "asistente_detalle": "Vertex respondió 403: dunning"})
    assert h and h[0]["severidad"] == proyectos.ALTA
    assert "asistente" in h[0]["que"].lower()
    assert "403" in h[0]["por_que"]


def test_una_plataforma_que_no_reporta_el_campo_no_inventa_hallazgo():
    """Una versión vieja de la plataforma no manda `asistente_ok`. Ausente no es
    roto — es justo el error del 'H1 vacío'."""
    assert proyectos._auditar_clamevet(
        {"documentos_con_error": 0, "documentos": 10, "fragmentos": 900,
         "empresas": 5, "socios": 5, "consultas_7d": 12, "ultimo_boletin": ""}) == []


def test_documentos_en_error_son_severidad_alta():
    """Un documento que no se indexó deja al asistente contestando sin ese
    material — y sin avisar que le falta."""
    h = proyectos._auditar_clamevet({"documentos_con_error": 2, "documentos": 10,
                                     "fragmentos": 900, "consultas_7d": 5})
    assert any(x["severidad"] == proyectos.ALTA and "error" in x["que"] for x in h)


def test_documentos_sin_fragmentos_es_el_rag_vacio():
    h = proyectos._auditar_clamevet({"documentos": 40, "fragmentos": 0,
                                     "consultas_7d": 3})
    assert any("cero fragmentos" in x["que"] for x in h)


def test_todo_bien_no_inventa_hallazgos():
    """Lo contrario del 'H1 vacío': si no hay nada, no hay nada que decir."""
    assert proyectos._auditar_clamevet(
        {"documentos_con_error": 0, "documentos": 10, "fragmentos": 900,
         "empresas": 5, "socios": 5, "consultas_7d": 12, "ultimo_boletin": ""}) == []


def test_canales_activos_y_cero_mensajes_es_alarma():
    """Es el síntoma de que se cortó el webhook o venció un token. Los mensajes
    que entran mientras tanto no se recuperan."""
    h = proyectos._auditar_crm({"canales_activos": 3, "mensajes_24h": 0})
    assert any(x["severidad"] == proyectos.ALTA for x in h)


def test_sin_canales_el_silencio_no_es_alarma():
    """Cero mensajes sin ningún canal conectado es lo esperable, no una falla."""
    h = proyectos._auditar_crm({"canales_activos": 0, "mensajes_24h": 0})
    assert not any("cero mensajes" in x["que"].lower() for x in h)


def test_un_token_vencido_sale_con_el_nombre_del_canal():
    h = proyectos._auditar_crm({"canales_activos": 1, "mensajes_24h": 5,
                                "tokens": [{"status": "expired", "name": "Portones SA",
                                            "channel_type": "whatsapp",
                                            "detail": "Session expired"}]})
    assert any("Portones SA" in x["que"] and x["severidad"] == proyectos.ALTA for x in h)


def test_una_empresa_activa_sin_canal_se_reporta():
    h = proyectos._auditar_crm({"canales_activos": 1, "mensajes_24h": 4,
                                "empresas_detalle": [
                                    {"nombre": "Sin Canal SA", "activa": True,
                                     "canales": 0, "usuarios": 2}]})
    assert any("Sin Canal SA" in x["que"] for x in h)


def test_una_empresa_dada_de_baja_no_se_reporta():
    """Una cuenta cerrada sin canales es lo correcto, no un hallazgo."""
    h = proyectos._auditar_crm({"canales_activos": 1, "mensajes_24h": 4,
                                "empresas_detalle": [
                                    {"nombre": "Ex Cliente", "activa": False,
                                     "canales": 0, "usuarios": 0}]})
    assert h == []


def test_el_cierre_diario_no_sale_a_verificar_credenciales(monkeypatch):
    """Verificar sale a pedir un token contra cada proveedor: segundos por
    credencial, y el consentimiento de Gmail está en Testing."""
    from app.integrations import credenciales
    monkeypatch.setattr(credenciales, "caidas",
                        lambda *a, **k: pytest.fail("no tenía que verificar"))
    proyectos._auditar_agentes({"fallas_recientes": 1}, credenciales_en_vivo=False)


def test_la_auditoria_a_pedido_si_las_verifica(monkeypatch):
    from app.integrations import credenciales
    monkeypatch.setattr(credenciales, "caidas",
                        lambda *a, **k: [{"clave": "meta", "rompe": "IG y FB"}])
    h = proyectos._auditar_agentes({})
    assert any("meta" in x["que"] and "IG y FB" in x["por_que"] for x in h)


def test_los_hallazgos_salen_ordenados_por_gravedad(monkeypatch):
    """El que mira el tablero lee de arriba. Lo grave tiene que estar arriba."""
    monkeypatch.setattr(proyectos, "salud", lambda pid=None: [
        {"id": "crm", "nombre": "CRM", "salud": {"estado": "ok", "ms": 100, "detalle": ""},
         "numeros": {"canales_activos": 2, "mensajes_24h": 0,
                     "empresas_detalle": [{"nombre": "X", "activa": True,
                                           "canales": 0, "usuarios": 1}]}}])
    monkeypatch.setattr(proyectos, "_tokens_del_crm", lambda: [])
    r = proyectos.auditar()
    severidades = [h["severidad"] for h in r["hallazgos"]]
    assert severidades == sorted(severidades, key=lambda s: {"alta": 0, "media": 1}[s])
    assert r["altas"] == 1


def test_un_proyecto_caido_no_se_audita_por_dentro(monkeypatch):
    """Si no responde, sus números no existen: inventar hallazgos sobre datos que
    no se pudieron leer es exactamente el error que no queremos."""
    monkeypatch.setattr(proyectos, "salud", lambda pid=None: [
        {"id": "crm", "nombre": "CRM", "salud": {"estado": "caido", "ms": 40,
                                                 "detalle": "HTTP 502"},
         "numeros": {}}])
    r = proyectos.auditar()
    assert len(r["hallazgos"]) == 1
    assert "no responde" in r["hallazgos"][0]["que"]


def test_la_tool_rechaza_un_proyecto_que_no_existe():
    from packs.automiq.tools import auditar_proyecto
    r = auditar_proyecto("inventado")
    assert "error" in r and "clamevet" in r["disponibles"]
