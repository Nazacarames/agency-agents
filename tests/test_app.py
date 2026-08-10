"""
Tests estructurales — verifican que la app se monta correctamente
SIN necesidad de API keys ni credenciales reales.

Cubren:
- Todos los agentes se registran
- Cada agente tiene name único, description no vacía, system_prompt no vacío
- Los schedules parsean como cron expressions válidas
- FastAPI expone los endpoints esperados
- El healthz responde con status=ok
"""
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture
def settings_empty():
    from app.config import Settings
    return Settings(
        minimax_api_key="",
        discord_webhook_url="",
        webhook_secret="test-secret",
        scheduler_enabled=False,
    )


def test_settings_defaults():
    from app.config import Settings
    s = Settings()
    assert s.scheduler_timezone == "America/Buenos_Aires"
    assert s.minimax_model_primary == "MiniMax-M3"
    assert "MiniMax-M2.5" in s.minimax_fallbacks_list
    assert s.port == 8000


def test_settings_empty_string_sanitization():
    from app.config import Settings
    # placeholders del .env.example se vuelven string vacío
    s = Settings(minimax_api_key="***", discord_webhook_url="REEMPLAZAR", webhook_secret="REEMPL...n")
    assert s.minimax_api_key == ""
    assert s.discord_webhook_url == ""
    assert s.webhook_secret == ""


def test_all_agents_registered():
    from app.agents.registry import list_agents
    agents = list_agents()
    names = {a.name for a in agents}

    # Los 8 agentes originales de OpenClaw
    expected = {
        "leadhunter",
        "content_creator",
        "growth_hacker",
        "creative_strategist",
        "social_media",
        "outbound",
        "media_auditor",
        "seo_specialist",
    }
    assert expected.issubset(names), f"Faltan: {expected - names}"


def test_agents_have_valid_metadata():
    from app.agents.registry import list_agents
    for a in list_agents():
        assert a.name, f"Agent {a.__class__.__name__} sin name"
        assert a.description, f"Agent {a.name} sin description"
        assert a.system_prompt, f"Agent {a.name} sin system_prompt"
        assert len(a.system_prompt) > 100, f"Agent {a.name} system_prompt muy corto"


def test_agent_schedules_parse():
    """Todos los schedules deben parsear como cron expressions válidas."""
    from apscheduler.triggers.cron import CronTrigger
    import pytz
    from app.agents.registry import list_agents

    for a in list_agents():
        if not a.schedule:
            continue
        # Si parsea, OK. Si no, levanta ValueError.
        CronTrigger.from_crontab(a.schedule, timezone=pytz.timezone(a.timezone))


def test_agent_names_unique():
    from app.agents.registry import list_agents
    names = [a.name for a in list_agents()]
    assert len(names) == len(set(names)), f"Nombres duplicados: {names}"


def test_fastapi_endpoints_present():
    from app.main import app
    paths = {r.path for r in app.routes if hasattr(r, "path")}
    required = {
        "/healthz",
        "/",
        "/agents",
        "/agents/{name}",
        "/run/{name}",
        "/webhook/lead",
        "/docs",
    }
    missing = required - paths
    assert not missing, f"Endpoints faltantes: {missing}"


def test_healthz_endpoint(settings_empty, monkeypatch):
    """El healthz responde 200 con status=ok y la config cargada."""
    # Parchar get_settings para usar settings vacías
    from app import main as app_main
    from app.config import get_settings as original_get_settings

    def fake_get_settings():
        return settings_empty

    # Invalidate lru_cache
    original_get_settings.cache_clear()
    monkeypatch.setattr("app.config.get_settings", fake_get_settings)
    monkeypatch.setattr("app.main.get_settings", fake_get_settings)

    from app.main import app
    with TestClient(app) as client:
        resp = client.get("/healthz")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert "version" in body
        assert "services" in body
        assert body["services"]["minimax_configured"] is False
        assert body["services"]["discord_configured"] is False


def test_agents_list_endpoint():
    from app.main import app
    with TestClient(app) as client:
        resp = client.get("/agents")
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, list)
        assert len(body) >= 8
        names = {a["name"] for a in body}
        assert "leadhunter" in names


def test_run_endpoint_requires_secret():
    from app.main import app
    with TestClient(app) as client:
        resp = client.post("/run/leadhunter", json={"async_run": False})
        assert resp.status_code in (401, 503)  # 503 si no hay secret configurado


def test_get_nonexistent_agent():
    from app.main import app
    with TestClient(app) as client:
        resp = client.get("/agents/does_not_exist")
        assert resp.status_code == 404


def test_dashboard_pantalla_departamentos():
    """La pantalla de Departamentos sirve y conserva sus piezas estructurales.

    El HTML es un archivo único de ~3.8k líneas sin build ni tests de UI: si alguien
    renombra o borra un contenedor del OS (stage, rail, drawer, vistas), esto avisa acá
    en vez de descubrirse mirando la pantalla en prod.
    """
    from app.main import app
    with TestClient(app) as client:
        resp = client.get("/dashboard")
        assert resp.status_code == 200
        html = resp.text
        for marca in ("neoStage", "neoRail", "neoDrawer", "neoCore",
                      "setNeoView('radial')", "setNeoView('orbital')"):
            assert marca in html, f"falta {marca} en el dashboard"
        # el texto del stage tiene que quedar legible: nada por debajo de 11px
        stage_css = re.findall(r"\.(?:orb-l|ns-l|ta-task|ta-b|ta-name|ts-name|nr-d|nr-h|"
                               r"nr-lens|nr-lg|brain-dom|neo-node-l|neo-node-s)"
                               r"(?![\w-]|::)\s*\{[^}]*?font-size:([\d.]+)px", html)
        assert stage_css, "no se encontraron tamaños de fuente del stage"
        chicos = [t for t in stage_css if float(t) < 11]
        assert not chicos, f"texto del stage por debajo de 11px: {chicos}"


def test_daily_batch_no_mata_a_los_leads_nuevos():
    """El lote diario tiene que incluir primer-toque aunque haya follow-ups vencidos.

    Reproduce el estado real del 2026-08-07: 165 leads nuevos (vencen hoy) contra 140
    follow-ups atrasados semanas. `due_for_touch` ordena por vencimiento, así que un corte
    plano `due[:cap]` se llevaba SOLO follow-ups y los nuevos no se contactaban nunca.
    """
    from app.integrations import leads_store as ls

    viejos = [{"key": f"fu{i}", "next_step": 2, "next_touch_at": "2026-07-13"}
              for i in range(140)]
    nuevos = [{"key": f"nv{i}", "next_step": 0, "next_touch_at": "2026-08-07"}
              for i in range(165)]
    due = sorted(viejos + nuevos,
                 key=lambda l: (l["next_touch_at"], -l["next_step"]))

    lote = ls.daily_batch(due, 10)
    assert len(lote) == 10, "el lote tiene que llenar el cupo"
    day0 = [l for l in lote if not l["next_step"]]
    assert day0, "sin este reparto los leads nuevos nunca se contactan"
    assert len(day0) == 5 and len(lote) - len(day0) == 5, "cupo repartido mitad y mitad"

    # Un solo carril con demanda se lleva todo el cupo: no se desperdician envíos.
    assert len(ls.daily_batch(viejos, 10)) == 10
    assert len(ls.daily_batch(nuevos, 10)) == 10
    # Menos leads que cupo → van todos; cupo cero → no se manda nada.
    assert len(ls.daily_batch(due[:3], 10)) == 3
    assert ls.daily_batch(due, 0) == []


def test_meeting_update_parcial_no_borra_campos():
    """Marcar una reunión como realizada no puede borrarle título, lugar ni notas.

    `MeetingBody` tiene defaults que NO son None (title="Reunión", location="", notes=""),
    así que `exclude_none` los dejaba pasar y el update parcial los escribía encima.
    `update_meeting` aplica todo lo que llegue, así que el filtro tiene que ser acá.
    """
    from app.main import MeetingBody

    parcial = MeetingBody(**{"status": "realizada"}).model_dump(exclude_unset=True)
    assert parcial == {"status": "realizada"}, f"se colaron campos no pedidos: {parcial}"

    # exclude_none —lo que había antes— arrastra los defaults y pisa datos reales.
    viejo = MeetingBody(**{"status": "realizada"}).model_dump(exclude_none=True)
    assert viejo.get("title") == "Reunión" and viejo.get("notes") == "", (
        "si esto cambia, el comentario del endpoint quedó desactualizado")

    # Lo que sí se manda explícito tiene que llegar, aunque coincida con el default.
    explicito = MeetingBody(**{"title": "Reunión"}).model_dump(exclude_unset=True)
    assert explicito == {"title": "Reunión"}


def test_hermes_extract_backend_no_cae_en_searxng(tmp_path, monkeypatch):
    """`web_extract` necesita un backend propio: searxng no sabe extraer.

    Sin `web.extract_backend`, Hermes resuelve el extract cayendo a `web.backend`
    —que fijamos en searxng para la búsqueda— y searxng es search-only: devolvía
    "search-only backend and cannot extract URL content" en cada intento. Los
    agentes lo reportaban como "web_extract caído" desde 2026-07-21.
    """
    import yaml
    from app.clients import hermes as h

    monkeypatch.setattr(h, "_HERMES_HOME", tmp_path / ".hermes")
    monkeypatch.setenv("TAVILY_API_KEY", "x" * 8)

    r = h.fijar_backend_busqueda()
    assert r["ok"] and r["cambio"]
    web = yaml.safe_load((tmp_path / ".hermes" / "config.yaml").read_text("utf-8"))["web"]
    assert web["search_backend"] == "searxng", "la búsqueda tiene que ir por el shim"
    assert web["extract_backend"] == "tavily", "sin esto el extract cae en searxng"
    assert h.fijar_backend_busqueda()["cambio"] is False, "tiene que ser idempotente"

    # La key de Tavily NO puede borrarse del entorno del hijo: Hermes chequea que
    # esté para considerar el backend usable, y sin ella el extract vuelve a caer.
    assert "TAVILY_API_KEY" not in h._HERMES_SEARCH_KEYS
    env = {"TAVILY_API_KEY": "x" * 8, "EXA_API_KEY": "y" * 8}
    h._wire_search_backend(env, SimpleNamespace(webhook_secret="s" * 10), "leadhunter")
    assert env.get("TAVILY_API_KEY"), "se borró la única key que sabe extraer"
    assert "EXA_API_KEY" not in env, "las demás sí se sacan: le ganarían al shim"
    assert "/api/searx/" in env["SEARXNG_URL"]


def test_drop_trigram_conserva_los_mensajes(tmp_path, monkeypatch):
    """Borrar el índice trigram no puede perder un solo mensaje.

    El 2026-08-07 el trigram eran 162 MB de los 296 de state.db (el texto queda
    guardado 3 veces: en `messages` y una copia entera dentro de cada FTS). Se
    borra el índice, nunca los datos — y los triggers van ANTES que la tabla: un
    trigger vivo apuntando a una tabla borrada rompe cada insert de mensaje.
    """
    import sqlite3
    from app.clients import hermes as h

    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setattr(h, "_HERMES_HOME", home)
    con = sqlite3.connect(str(home / "state.db"))
    try:
        con.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, content TEXT)")
        con.execute("CREATE VIRTUAL TABLE messages_fts_trigram "
                    "USING fts5(content, tokenize='trigram')")
        for t, cuerpo in (("insert", "INSERT INTO messages_fts_trigram(rowid, content) "
                                     "VALUES (new.id, new.content);"),
                          ("delete", "DELETE FROM messages_fts_trigram WHERE rowid = old.id;"),
                          ("update", "DELETE FROM messages_fts_trigram WHERE rowid = old.id;")):
            con.execute(f"CREATE TRIGGER messages_fts_trigram_{t} AFTER {t.upper()} "
                        f"ON messages BEGIN {cuerpo} END")
        con.executemany("INSERT INTO messages (content) VALUES (?)",
                        [(f"mensaje {i}",) for i in range(50)])
        con.commit()
    finally:
        con.close()

    r = h.sessions_drop_trigram()
    assert r["ok"] and r["cambio"], r
    assert r["mensajes_ahora"] == r["mensajes_antes"] == 50, "se perdieron mensajes"
    assert r["integridad"] == "ok"

    con = sqlite3.connect(str(home / "state.db"))
    try:
        assert not con.execute("SELECT 1 FROM sqlite_master WHERE "
                               "name='messages_fts_trigram'").fetchone()
        assert not con.execute("SELECT 1 FROM sqlite_master WHERE type='trigger' "
                               "AND name LIKE 'messages_fts_trigram%'").fetchone(), \
            "quedó un trigger apuntando a la tabla borrada"
        # con los triggers vivos, esto reventaría — es el caso que protege el orden
        con.execute("INSERT INTO messages (content) VALUES ('despues')")
        con.commit()
        assert con.execute("SELECT count(*) FROM messages").fetchone()[0] == 51
    finally:
        con.close()

    assert h.sessions_drop_trigram()["cambio"] is False, "tiene que ser idempotente"
