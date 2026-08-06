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
