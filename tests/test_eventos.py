"""La bitácora única: que lo que sale al mundo quede anotado y con dueño.

El bug que motivó esto: `write_run_log` escribía en logs/agent_runs.jsonl, que
muere en cada deploy, y no guardaba acciones sino tokens. Estos tests corren
contra el fallback JSON (sin DATABASE_URL), que es exactamente el modo en el que
corre un test y el modo degradado en producción.
"""
import json

import pytest

from app.integrations import eventos


@pytest.fixture(autouse=True)
def bitacora_aislada(tmp_path, monkeypatch):
    """Cada test con su propio archivo y sin DB: nada de tocar data/ real."""
    destino = tmp_path / "agent-events.json"
    monkeypatch.setattr(eventos, "_json_path", lambda: destino)
    monkeypatch.setattr(eventos.db, "enabled", lambda: False)
    return destino


def test_anota_lo_que_salio_y_se_puede_leer_despues():
    eventos.registrar("mail", "Mail enviado: propuesta", destino="cliente@x.com",
                      ref="msg-1")
    filas = eventos.ultimos()
    assert len(filas) == 1
    assert filas[0]["tipo"] == "mail"
    assert filas[0]["destino"] == "cliente@x.com"
    assert filas[0]["ref"] == "msg-1"
    assert filas[0]["ok"] is True
    assert filas[0]["ts"], "sin fecha la línea de tiempo no sirve"


def test_el_evento_hereda_el_agente_de_la_corrida():
    """gmail_client no sabe qué agente lo llamó; `en_curso` se lo dice sin que
    haya que pasarlo por toda la pila."""
    with eventos.en_curso("outbound", "run-42"):
        eventos.registrar("mail", "Mail enviado", destino="lead@x.com")
    fila = eventos.ultimos()[0]
    assert fila["agente"] == "outbound"
    assert fila["run_id"] == "run-42"


def test_fuera_de_la_corrida_no_inventa_un_dueño():
    eventos.registrar("mail", "Mail suelto")
    assert eventos.ultimos()[0]["agente"] == ""


def test_el_contexto_se_devuelve_al_salir():
    with eventos.en_curso("outbound", "run-1"):
        with eventos.en_curso("inbox_assistant", "run-2"):
            assert eventos.actor() == ("inbox_assistant", "run-2")
        assert eventos.actor() == ("outbound", "run-1")
    assert eventos.actor() == ("", "")


def test_lo_mas_nuevo_primero_y_filtrable():
    eventos.registrar("mail", "uno", agente="outbound")
    eventos.registrar("post", "dos", agente="social_media")
    eventos.registrar("mail", "tres", agente="outbound")
    assert [f["resumen"] for f in eventos.ultimos()] == ["tres", "dos", "uno"]
    assert [f["resumen"] for f in eventos.ultimos(tipo="mail")] == ["tres", "uno"]
    assert [f["resumen"] for f in eventos.ultimos(agente="social_media")] == ["dos"]


def test_guarda_los_fallos_igual_que_los_exitos():
    """Una bitácora que sólo anota lo que salió bien no sirve para entender por
    qué algo no llegó."""
    eventos.registrar("post", "IG rechazó el video", ok=False,
                      detalle={"error": "media type"})
    fila = eventos.ultimos()[0]
    assert fila["ok"] is False
    assert fila["detalle"]["error"] == "media type"


def test_ids_incrementales_sin_colisionar(bitacora_aislada):
    for i in range(5):
        eventos.registrar("run", f"corrida {i}")
    ids = [f["id"] for f in eventos.ultimos()]
    assert len(set(ids)) == 5
    guardado = json.loads(bitacora_aislada.read_text(encoding="utf-8"))
    assert [g["id"] for g in guardado] == [1, 2, 3, 4, 5]


def test_el_json_tiene_techo(monkeypatch):
    """Sin tope, el fallback se come el disco del contenedor."""
    monkeypatch.setattr(eventos, "MAX_JSON", 3)
    for i in range(6):
        eventos.registrar("run", f"corrida {i}")
    filas = eventos.ultimos()
    assert len(filas) == 3
    assert [f["resumen"] for f in filas] == ["corrida 5", "corrida 4", "corrida 3"]


def test_nunca_voltea_la_corrida(monkeypatch):
    """Regla dura: registrar es best-effort. Si la escritura falla, el mail ya
    salió y la corrida tiene que seguir."""
    def explota(*a, **k):
        raise OSError("disco lleno")
    monkeypatch.setattr(eventos, "write_json_atomic", explota)
    assert eventos.registrar("mail", "sale igual") is None


def test_recorta_campos_largos_en_vez_de_romper():
    eventos.registrar("mail", "x" * 900, destino="y" * 400, ref="z" * 600)
    fila = eventos.ultimos()[0]
    assert len(fila["resumen"]) == 500
    assert len(fila["destino"]) == 200
    assert len(fila["ref"]) == 300


# ── el cableado: que la corrida y lo que sale adentro queden atribuidos ──

class _MiniMaxFalso:
    def complete(self, **kw):
        from app.clients.minimax import MiniMaxResponse
        return MiniMaxResponse(text="informe listo", model="falso", input_tokens=10,
                               output_tokens=5, stop_reason="end_turn", raw={},
                               elapsed_ms=1)


_CLASE_FALSA = []


def _agente_de_prueba():
    # `BaseAgent.__init_subclass__` registra cada subclase en un registry global y
    # rechaza duplicados, así que la clase se define UNA vez y se reusa.
    if not _CLASE_FALSA:
        from app.agents.base import BaseAgent

        class Falso(BaseAgent):
            name = "agente_de_prueba"
            deliver_to_discord = False

            def build_user_message(self, ctx):
                return "hola"

            def system_prompt(self, ctx=None):
                return "sos un agente"

        _CLASE_FALSA.append(Falso)
    return _CLASE_FALSA[0]()


def _ctx():
    from app.agents.base import AgentContext
    from app.config import get_settings
    return AgentContext(settings=get_settings(), minimax=_MiniMaxFalso(), discord=None,
                        run_id="run-1", triggered_by="cron", args={})


def test_una_corrida_ok_queda_en_la_bitacora():
    _agente_de_prueba().run(_ctx())
    fila = eventos.ultimos(tipo="run")[0]
    assert fila["agente"] == "agente_de_prueba"
    assert fila["run_id"] == "run-1"
    assert fila["ok"] is True
    assert fila["destino"] == "cron", "de dónde vino la corrida importa para auditarla"


def test_una_corrida_que_falla_tambien(monkeypatch):
    ag = _agente_de_prueba()
    monkeypatch.setattr(ag, "build_user_message",
                        lambda ctx: (_ for _ in ()).throw(RuntimeError("se cayo")))
    with pytest.raises(RuntimeError):
        ag.run(_ctx())
    fila = eventos.ultimos(tipo="run")[0]
    assert fila["ok"] is False
    assert "RuntimeError" in fila["resumen"]
    assert "se cayo" in fila["detalle"]["error"]


def test_el_mail_que_sale_adentro_de_una_corrida_lleva_el_agente(monkeypatch):
    """gmail_client no recibe el nombre del agente por parametro: lo saca del
    contexto de la corrida. Si esto se rompe, los mails quedan huerfanos."""
    from app.integrations import gmail_client

    ag = _agente_de_prueba()
    monkeypatch.setattr(
        ag, "build_user_message",
        lambda ctx: gmail_client._anotar("mail", "Mail enviado: prueba",
                                         destino="lead@x.com", ref="msg-9") or "hola")
    ag.run(_ctx())
    mail = eventos.ultimos(tipo="mail")[0]
    assert mail["agente"] == "agente_de_prueba"
    assert mail["run_id"] == "run-1"
    assert mail["destino"] == "lead@x.com"
