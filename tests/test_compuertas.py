"""Compuertas de aprobación: que apagar sea apagar.

El incidente que las motivó: la pausa de un agente se puso como bandera en UN
camino de salida y se escaparon cuatro mensajes por los otros cinco. Por eso la
compuerta va en el cuello de botella (el método que manda el mail, la función
que publica) y no en cada agente.
"""
import pytest

from app.integrations import compuertas, eventos


@pytest.fixture(autouse=True)
def bitacora_aislada(tmp_path, monkeypatch):
    destino = tmp_path / "agent-events.json"
    monkeypatch.setattr(eventos, "_json_path", lambda: destino)
    monkeypatch.setattr(eventos.db, "enabled", lambda: False)


@pytest.fixture
def con_compuerta(monkeypatch):
    def _set(valor):
        monkeypatch.setattr(compuertas, "activas", lambda: set(valor))
    return _set


def test_sin_compuertas_no_frena_nada():
    """Default: APPROVAL_GATES vacío = el sistema se comporta como siempre."""
    compuertas.frena("mail", "lead@x.com", "Quiere mandar: hola")
    assert eventos.ultimos() == []


def test_con_compuerta_frena_y_deja_el_pedido_anotado(con_compuerta):
    con_compuerta({"mail"})
    with pytest.raises(compuertas.Frenado) as e:
        compuertas.frena("mail", "lead@x.com", "Quiere mandar: propuesta",
                         {"subject": "propuesta"})
    assert e.value.destino == "lead@x.com"
    pend = compuertas.pendientes()
    assert len(pend) == 1
    assert pend[0]["estado"] == "esperando_ok"
    assert pend[0]["ok"] is False, "no salió: no puede figurar como éxito"
    assert pend[0]["detalle"]["subject"] == "propuesta"


def test_aprobar_un_mail_habilita_a_ese_destinatario(con_compuerta):
    """Los agentes reintentan solos todos los días: aprobar una vez alcanza para
    que el próximo intento pase, sin reanudar ninguna corrida."""
    con_compuerta({"mail"})
    with pytest.raises(compuertas.Frenado) as e:
        compuertas.frena("mail", "lead@x.com", "Quiere mandar")
    assert compuertas.resolver(e.value.evento_id, aprobado=True, por="nazareno") is True
    compuertas.frena("mail", "lead@x.com", "Segundo toque")   # ya no levanta
    assert compuertas.pendientes() == []


def test_rechazar_no_abre_el_paso(con_compuerta):
    con_compuerta({"mail"})
    with pytest.raises(compuertas.Frenado) as e:
        compuertas.frena("mail", "lead@x.com", "Quiere mandar")
    compuertas.resolver(e.value.evento_id, aprobado=False, por="nazareno")
    with pytest.raises(compuertas.Frenado):
        compuertas.frena("mail", "lead@x.com", "Insiste")


def test_aprobar_un_destinatario_no_abre_a_los_demas(con_compuerta):
    con_compuerta({"mail"})
    with pytest.raises(compuertas.Frenado) as e:
        compuertas.frena("mail", "uno@x.com", "Quiere mandar")
    compuertas.resolver(e.value.evento_id, aprobado=True)
    with pytest.raises(compuertas.Frenado):
        compuertas.frena("mail", "otro@x.com", "Quiere mandar")


def test_aprobar_un_post_no_abre_la_red_para_siempre(con_compuerta):
    """Un post no va dirigido a nadie: si la aprobación se recordara por red, el
    primer sí habilitaría Instagram para siempre y la compuerta serviría una vez."""
    con_compuerta({"post"})
    with pytest.raises(compuertas.Frenado) as e:
        compuertas.frena("post", "instagram", "Quiere publicar un post")
    compuertas.resolver(e.value.evento_id, aprobado=True)
    with pytest.raises(compuertas.Frenado):
        compuertas.frena("post", "instagram", "Quiere publicar otro post")


def test_la_compuerta_de_un_tipo_no_afecta_al_otro(con_compuerta):
    con_compuerta({"mail"})
    compuertas.frena("post", "instagram", "Quiere publicar")   # sin compuerta: pasa
    with pytest.raises(compuertas.Frenado):
        compuertas.frena("mail", "lead@x.com", "Quiere mandar")


def test_no_se_puede_resolver_dos_veces(con_compuerta):
    con_compuerta({"mail"})
    with pytest.raises(compuertas.Frenado) as e:
        compuertas.frena("mail", "lead@x.com", "Quiere mandar")
    assert compuertas.resolver(e.value.evento_id, aprobado=True) is True
    assert compuertas.resolver(e.value.evento_id, aprobado=False) is False


def test_activas_lee_el_csv_de_settings(monkeypatch):
    from app.config import get_settings
    s = get_settings()
    monkeypatch.setattr(s, "approval_gates", " Mail , post ,, ")
    monkeypatch.setattr(compuertas, "get_settings", lambda: s)
    assert compuertas.activas() == {"mail", "post"}


# ── el cuello de botella: que la compuerta esté donde pasa todo ──

def test_el_mail_no_sale_si_la_compuerta_esta_puesta(con_compuerta, monkeypatch):
    """gmail_client.send_message tiene que frenar ANTES de armar el servicio: si
    frenara después, ya habría pegado contra Google."""
    from app.integrations import gmail_client
    con_compuerta({"mail"})

    cliente = gmail_client.GmailClient.__new__(gmail_client.GmailClient)
    monkeypatch.setattr(gmail_client.GmailClient, "_build_service",
                        lambda self: (_ for _ in ()).throw(
                            AssertionError("no tenía que llegar a Gmail")))
    with pytest.raises(compuertas.Frenado):
        gmail_client.GmailClient.send_message(cliente, to="lead@x.com",
                                              subject="hola", body="texto")
    assert compuertas.pendientes()[0]["destino"] == "lead@x.com"


def test_frenado_es_excepcion_y_no_un_id_vacio():
    """Los que mandan mail guardan el message id que devuelve el cliente. Un id
    vacío se registraría como un envío exitoso que nunca pasó."""
    assert issubclass(compuertas.Frenado, Exception)


def test_un_toque_frenado_no_cuenta_como_error_del_embudo():
    """El log de errores del outbound es el único dato del embudo que no se puede
    reconstruir después. Un mail que espera aprobación no falló, y mezclarlo con
    los rebotes haría ver días de 12 errores que en realidad son 12 pendientes."""
    from app.agents.outbound import OutboundAgent

    class _Ctx:
        args = {"_ob_ingest": {"nuevos": 0}}

    ag = OutboundAgent.__new__(OutboundAgent)
    reporte = ag._render_report(_Ctx(), True, True, sent=[], preview=[], errors=[],
                                missing=[], frenados=["• **Acme** <a@x.com> — primer toque"])
    assert "**Errores:** 0" in reporte
    assert "Esperando tu OK" in reporte
    assert "Acme" in reporte


def test_el_post_frenado_vuelve_como_error_y_no_como_publicado(con_compuerta,
                                                               monkeypatch):
    from app.integrations import social_publish
    con_compuerta({"post"})
    monkeypatch.setattr(social_publish, "publish_instagram",
                        lambda *a, **k: (_ for _ in ()).throw(
                            AssertionError("no tenía que publicar")))
    r = social_publish.publish("foto.png", "texto", targets=["instagram"])
    assert r["ok"] is False
    assert "aprobación" in r["error"]
    assert compuertas.pendientes()[0]["estado"] == "esperando_ok"
