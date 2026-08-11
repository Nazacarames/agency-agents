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


def test_email_muerto_no_vuelve_a_gastar_cupo():
    """Un mail que rebota seguro tiene que salir de la secuencia, no solo frenarse.

    La barrera de entregabilidad hacía `continue` sin tocar el lead: quedaba `nuevo`
    con `next_touch_at` vencido, así que volvía a entrar al lote al día siguiente y
    fallaba igual. El 2026-08-10 `Cuyana Repuestos` seguía en step 0 con fecha del
    21/07, ocupando un cupo de primer-toque todos los días.
    """
    from app.integrations import leads_store as ls

    store = {"leads": {
        "con-tel": {"key": "con-tel", "company": "Con teléfono", "state": "nuevo",
                    "email": "ventas@dominio-muerto.com.ar", "phone": "+5493410000000",
                    "next_step": 0, "next_touch_at": "2026-07-21", "touches": []},
        "sin-tel": {"key": "sin-tel", "company": "Sin teléfono", "state": "nuevo",
                    "email": "info@otro-muerto.com.ar", "phone": "",
                    "next_step": 0, "next_touch_at": "2026-07-21", "touches": []},
    }}
    # antes: los dos entran al lote de hoy
    assert len(ls.due_for_touch(store, today="2026-08-10")) == 2

    assert ls.marcar_email_muerto(store, "con-tel", "sin MX", today="2026-08-10") == "whatsapp"
    assert ls.marcar_email_muerto(store, "sin-tel", "sin MX", today="2026-08-10") == "cerrado"

    # después: ninguno vuelve a gastar cupo
    assert ls.due_for_touch(store, today="2026-08-10") == []
    # el que tiene teléfono NO se pierde: queda para contacto a mano
    assert [l["key"] for l in ls.whatsapp_queue(store)] == ["con-tel"]
    assert store["leads"]["sin-tel"]["state"] == "sin_respuesta"
    # queda por qué se lo dio de baja
    assert "sin MX" in store["leads"]["con-tel"]["notes"][0]["note"]
    assert ls.marcar_email_muerto(store, "no-existe", "x") is None


def test_lead_con_email_sin_agenda_se_rescata():
    """Un lead que consigue email después de nacer tiene que volver a la cola.

    `add_lead` solo agenda si nace CON email. El enriquecimiento busca uno publicado
    en el sitio y lo setea, pero no agenda — y como `_is_due(None)` es False, el lead
    queda invisible para siempre. El 2026-08-10 había 13 así, con email verificado.
    """
    from app.integrations import leads_store as ls

    store = {"leads": {
        "enriquecido": {"key": "enriquecido", "company": "Enriquecido", "state": "nuevo",
                        "email": "info@real.com.ar", "next_step": 0,
                        "next_touch_at": None, "touches": []},
        "agotado": {"key": "agotado", "company": "Agotado", "state": "sin_respuesta",
                    "email": "info@agotado.com.ar", "next_step": 4,
                    "next_touch_at": None, "touches": [{"step": 3}]},
        "sin_mail": {"key": "sin_mail", "company": "Solo WhatsApp", "state": "nuevo",
                     "email": "", "phone": "+5493410000000", "next_step": 0,
                     "next_touch_at": None, "touches": []},
    }}
    assert ls.due_for_touch(store, today="2026-08-10") == [], "arranca invisible"

    assert ls.reprogramar_sin_agenda(store, today="2026-08-10") == 1
    assert [l["key"] for l in ls.due_for_touch(store, today="2026-08-10")] == ["enriquecido"]
    # el que agotó la secuencia NO se reprograma: sería reiniciarla sin que nadie lo pida
    assert store["leads"]["agotado"]["next_touch_at"] is None
    # sin email no hay nada que agendar: ese va por WhatsApp
    assert store["leads"]["sin_mail"]["next_touch_at"] is None
    assert ls.reprogramar_sin_agenda(store, today="2026-08-10") == 0, "idempotente"


def test_extract_field_toma_el_valor_de_su_propia_label():
    """`Web:` a mitad de línea tiene que dar la URL, no el resto del renglón.

    El 2026-08-10, 0 de 343 leads tenían `web` guardado, así que
    `enrich_missing_emails` —que lo exige— nunca pudo correr. Dos causas: el
    formato pedía Empleados y Web en la MISMA línea, y el parser partía en el
    primer `:` de la línea (el de Empleados).
    """
    from app.integrations.leads_store import _extract_field

    # el caso que rompía: dos campos en una línea
    b = "- Empleados: 25-50   Web: https://maderzu.com.ar\n- Decisor: Ana Pérez"
    assert _extract_field(b, "web") == "https://maderzu.com.ar"
    assert _extract_field(b, "empleados") == "25-50"
    assert _extract_field(b, "decisor") == "Ana Pérez"

    # "web" en prosa NO es el sitio: antes devolvía la frase entera
    assert _extract_field("- Discovery signals: (1) web con App Google Play", "web") == ""

    # formato nuevo (una label por línea) y markdown alrededor
    assert _extract_field("- Web: https://x.com.ar", "web") == "https://x.com.ar"
    assert _extract_field("**Empresa:** Bolsaplast S.R.L.", "empresa") == "Bolsaplast S.R.L."
    assert _extract_field("- Industria | distribución", "industria") == "distribución"
    assert _extract_field("- Empleados: 10", "web") == ""


def test_reporte_resumen_no_aporta_leads():
    """Un resumen de leadhunter no debe pasar por un reporte con 0 leads del día.

    El 2026-08-10 leadhunter entregó "Listo. El reporte completo de 10 leads está
    impreso en la respuesta" — sin un solo contacto. `ingest_report` devuelve todo
    en cero y antes eso se leía igual que un día flojo: la caída de captura se
    venía atribuyendo a un token vencido inexistente.
    """
    from app.integrations import leads_store as ls

    resumen = ("Listo. El reporte completo de 10 leads está impreso en la respuesta.\n\n"
               "10 leads generados, todos con contacto verificado.\n"
               "Top 5 para outreach inmediato: Racer · Mosto Bebidas · Corblock.\n")
    store = {"leads": {}}
    st = ls.ingest_report(store, resumen, today="2026-08-10")
    assert not any(st.get(k) for k in ("nuevos", "existentes", "sin_identidad")), st
    assert store["leads"] == {}, "un resumen no puede crear leads fantasma"

    # un reporte de verdad sí entra
    real = ("### Lead 1: Bolsaplast S.R.L.\n"
            "- Industria: plásticos\n"
            "- Web: https://bolsaplastsrl.com.ar\n"
            "- email: consultas@bolsaplastsrl.com.ar\n"
            "- Teléfono: +54 341 555 1234\n")
    st2 = ls.ingest_report({"leads": {}}, real, today="2026-08-10")
    assert any(st2.get(k) for k in ("nuevos", "existentes", "sin_identidad")), st2


def test_insert_de_clientes_tiene_los_placeholders_justos():
    """Cada columna del INSERT necesita su `%s`. Se cuenta acá porque el desajuste
    NO se ve leyendo: revienta recién al crear un cliente, contra la DB real.

    Pasó al agregar `setup_fee` (2026-08-10): la columna entró en la lista y el
    placeholder no.
    """
    import re
    from pathlib import Path

    def _slots(expr: str) -> int:
        """Valores separados por comas de NIVEL SUPERIOR.

        No alcanza con `split(",")`: `COALESCE(%s,now())` es UN valor y la coma de
        adentro lo partiría en dos.
        """
        n, prof = 1, 0
        for ch in expr:
            if ch == "(":
                prof += 1
            elif ch == ")":
                prof -= 1
            elif ch == "," and prof == 0:
                n += 1
        return n

    def _entre_parentesis(texto: str, desde: int) -> str:
        """Contenido del paréntesis que abre en/después de `desde`, balanceado.

        Con regex no alcanza: el VALUES tiene paréntesis anidados (`COALESCE(...)`)
        y cualquier `\\)` corta antes o después de donde debe.
        """
        ini = texto.index("(", desde)
        prof = 0
        for i in range(ini, len(texto)):
            if texto[i] == "(":
                prof += 1
            elif texto[i] == ")":
                prof -= 1
                if prof == 0:
                    return texto[ini + 1:i]
        raise AssertionError("paréntesis sin cerrar")

    src = Path("app/integrations/clients_store.py").read_text(encoding="utf-8")
    # el SQL viene partido en varios literales concatenados: se unen primero
    plano = re.sub(r'"\s*\n\s*"', "", src)
    pares = []
    for m in re.finditer(r"INSERT INTO clients\s*\(", plano):
        cols_raw = _entre_parentesis(plano, m.end() - 1)
        vals_raw = _entre_parentesis(plano, plano.index("VALUES", m.end()))
        pares.append((cols_raw, vals_raw))
    assert pares, "no se encontró ningún INSERT de clients"
    for cols_raw, vals_raw in pares:
        cols = [c for c in cols_raw.split(",") if c.strip()]
        slots = _slots(vals_raw)
        assert len(cols) == slots, (
            f"INSERT desbalanceado: {len(cols)} columnas contra {slots} valores\n"
            f"columnas: {cols}\nvalores: {vals_raw}")
