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
import base64
import gzip
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


def test_facturado_del_anio_suma_unico_y_mensualidades():
    """El facturado del año = pago único + mensualidades devengadas, y NO cuenta
    lo que todavía no se cobra.

    El MRR sólo describe el mes en curso y el pago único no entra ahí, así que sin
    esto un contrato como CLAMEVET (US$3.000 único + 500/mes) no aparecía en
    ninguna métrica.
    """
    from app.integrations import clients_store as cs

    clientes = [
        # activo desde marzo: 500/mes × (mar..jun = 4) + 3.000 de alta
        {"id": "a", "name": "Activo", "status": "activo", "currency": "USD",
         "monthly_fee": 500, "setup_fee": 3000, "start_date": "2026-03-10"},
        # onboarding = todavía NO paga: no suma nada aunque tenga fees cargados
        {"id": "b", "name": "Onboarding", "status": "onboarding", "currency": "USD",
         "monthly_fee": 900, "setup_fee": 5000, "start_date": "2026-02-01"},
        # alta futura: no se factura por adelantado
        {"id": "c", "name": "Futuro", "status": "activo", "currency": "USD",
         "monthly_fee": 400, "setup_fee": 100, "start_date": "2026-11-01"},
    ]
    orig = cs.list_clients
    cs.list_clients = lambda: clientes
    try:
        r = cs.billed_year(2026, hoy="2026-06")     # el mes se inyecta, no se parchea
    finally:
        cs.list_clients = orig

    assert r["unico_usd"] == 3000, r
    assert r["recurrente_usd"] == 2000, r   # 500 × 4 meses (mar,abr,may,jun)
    assert r["total_usd"] == 5000, r
    assert [d["name"] for d in r["por_cliente"]] == ["Activo"], "sólo el que factura"
    assert r["hasta"] == "2026-06", "el año en curso se corta en el mes actual"


# ── DMARC ──────────────────────────────────────────────────────────────────

_DMARC_XML = b"""<?xml version="1.0"?>
<feedback>
  <report_metadata>
    <org_name>google.com</org_name>
    <date_range><begin>1786060800</begin><end>1786147200</end></date_range>
  </report_metadata>
  <policy_published><domain>automiq.agency</domain><p>none</p></policy_published>
  <record>
    <row><source_ip>209.85.220.69</source_ip><count>8</count>
      <policy_evaluated><disposition>none</disposition><dkim>fail</dkim><spf>fail</spf></policy_evaluated>
    </row>
    <identifiers><header_from>automiq.agency</header_from></identifiers>
    <auth_results>
      <dkim><domain>otrodominio.com.ar</domain><selector>google</selector><result>pass</result></dkim>
      <spf><domain>otrodominio.com.ar</domain><result>pass</result></spf>
    </auth_results>
  </record>
  <record>
    <row><source_ip>1.2.3.4</source_ip><count>5</count>
      <policy_evaluated><disposition>none</disposition><dkim>pass</dkim><spf>fail</spf></policy_evaluated>
    </row>
    <identifiers><header_from>automiq.agency</header_from></identifiers>
    <auth_results>
      <dkim><domain>automiq.agency</domain><selector>google</selector><result>pass</result></dkim>
      <spf><domain>relay-ajeno.net</domain><result>none</result></spf>
    </auth_results>
  </record>
</feedback>
"""


class _FakeSvc:
    def users(self): return self
    def messages(self): return self
    def attachments(self): return self

    def list(self, **kw):
        return SimpleNamespace(execute=lambda: {"messages": [{"id": "m1"}]})

    def get(self, **kw):
        if "messageId" in kw:      # descarga del adjunto
            data = base64.urlsafe_b64encode(gzip.compress(_DMARC_XML)).decode()
            return SimpleNamespace(execute=lambda: {"data": data})
        return SimpleNamespace(execute=lambda: {
            "id": "m1",
            "payload": {"parts": [{"filename": "informe.xml.gz",
                                   "body": {"attachmentId": "a1"}}]},
        })


def test_dmarc_solo_marca_falla_lo_que_no_alinea_por_ningun_lado(monkeypatch):
    """Un reenvío alinea por DKIM aunque el SPF sea de otro dominio: NO es una
    falla. Si lo contáramos, cada mail reenviado dispararía una alerta de
    suplantación y el aviso dejaría de significar nada."""
    from app.integrations import dmarc_reports as dr

    monkeypatch.setattr(dr, "_service", lambda s: _FakeSvc())
    monkeypatch.setattr(dr, "_dominios_conocidos", set)
    s = SimpleNamespace(gmail_configured=True, gmail_user_id="me",
                        gmail_client_id="x", gmail_client_secret="x",
                        gmail_refresh_token="x")
    out = dr.resumen(s)

    assert out["ok"] is True
    assert out["mensajes"] == 13          # 8 + 5, todo lo reportado
    assert out["fallan"] == 8             # sólo el que no alinea por ningún lado
    assert len(out["fallas"]) == 1
    assert out["fallas"][0]["dkim"] == "otrodominio.com.ar"
    assert out["fallas"][0]["ip"] == "209.85.220.69"


def test_dmarc_no_alerta_por_mail_reenviado_por_un_lead(monkeypatch):
    """Le escribimos a un prospecto, su servidor reparte el mail a N buzones
    internos y re-firma cada copia con SU dominio: DMARC lo reporta como no
    alineado. Es nuestro propio mail. Si contara, cada corrida de outbound
    dispararía una alerta de suplantación."""
    from app.integrations import dmarc_reports as dr

    monkeypatch.setattr(dr, "_service", lambda s: _FakeSvc())
    monkeypatch.setattr(dr, "_dominios_conocidos", lambda: {"otrodominio.com.ar"})
    s = SimpleNamespace(gmail_configured=True, gmail_user_id="me",
                        gmail_client_id="x", gmail_client_secret="x",
                        gmail_refresh_token="x")
    out = dr.resumen(s)

    assert out["fallan"] == 0             # nada que alertar
    assert out["reenviados"] == 8         # pero no se oculta: queda contado aparte
    assert out["fallas"][0]["reenvio_de_lead"] is True


def test_dmarc_sin_credenciales_no_revienta():
    """El watchdog lo llama en cada pasada: si Gmail no está configurado tiene que
    devolver ok=False, no tirar la corrida entera."""
    from app.integrations import dmarc_reports as dr
    out = dr.resumen(SimpleNamespace(gmail_configured=False))
    assert out["ok"] is False and out["fallan"] == 0


def test_backlog_no_duplica_el_mismo_hallazgo_redactado_distinto(tmp_path, monkeypatch):
    """El valor del backlog es la EDAD, y la edad muere si cada redacción abre un
    ítem nuevo. El LLM no escribe igual dos días seguidos, así que el dedup tiene
    que tolerar la reformulación."""
    from app.integrations import backlog as bl
    monkeypatch.setattr(bl, "_FILE", tmp_path / "backlog.json")

    a = bl.abrir("web", "El H1 del home está vacío", origen="web_auditor")
    b = bl.abrir("web", "El H1 de la home esta vacio", origen="seo_specialist")
    assert a and b and a["id"] == b["id"]          # mismo ítem, no dos
    assert b["veces"] == 2                          # y queda contado que se repitió
    assert sorted(b["origenes"]) == ["seo_specialist", "web_auditor"]
    assert len(bl.abiertos()) == 1

    # Área distinta = ítem distinto: lo que cambia es QUIÉN puede cerrarlo.
    bl.abrir("dev", "El H1 del home está vacío", origen="chief_of_staff")
    assert len(bl.abiertos()) == 2
    assert len(bl.abiertos("web")) == 1


def test_backlog_no_cierra_sin_evidencia(tmp_path, monkeypatch):
    """'Resuelto' sin evidencia es una opinión: así es como un pendiente se cierra
    solo y reaparece a los tres días."""
    from app.integrations import backlog as bl
    monkeypatch.setattr(bl, "_FILE", tmp_path / "backlog.json")

    it = bl.abrir("dev", "outbound: el modo day0 no existe en el código", origen="chief_of_staff")
    assert bl.resolver(it["id"], "ok") is False              # evidencia vacía → no cierra
    assert len(bl.abiertos()) == 1
    assert bl.resolver(it["id"], "commit abc123: daily_batch reserva la mitad del cupo") is True
    assert bl.abiertos() == []
    assert bl.resolver(it["id"], "commit abc123: ya estaba cerrado") is False   # no revive


def test_backlog_area_invalida_se_ignora(tmp_path, monkeypatch):
    """Se cosecha de texto libre de un LLM: un área inventada no puede crear una
    categoría fantasma que después nadie mira."""
    from app.integrations import backlog as bl
    monkeypatch.setattr(bl, "_FILE", tmp_path / "backlog.json")
    assert bl.abrir("marketing", "algo que suena importante") is None
    assert bl.abrir("web", "corto") is None                  # título sin sustancia
    assert bl.abiertos() == []


def test_harvest_saca_pendientes_del_texto_crudo_del_agente(tmp_path, monkeypatch):
    """El backlog se llena cosechando marcadores del output del agente, igual que
    NOTA_PARA/LECCION. Si el regex no engancha con lo que un LLM realmente escribe
    (viñetas, negritas, backticks), no se registra nada y todo el mecanismo es humo."""
    from app.agents.registry import get_agent
    from app.integrations import backlog as bl
    monkeypatch.setattr(bl, "_FILE", tmp_path / "backlog.json")

    salida = (
        "# Auditoría\n"
        "El home sigue sin H1 y sin tracking.\n"
        "- `PENDIENTE(web)`: el H1 del home está vacío, hay que poner el titular real\n"
        "* **PENDIENTE(dev):** outbound necesita un modo day0 que hoy no existe\n"
        "> PENDIENTE(humano): decidir los 9 números reales de los contadores del home\n"
        "PENDIENTE(inventada): esto no debería entrar\n"
    )
    agente = get_agent("web_auditor")
    agente._harvest_collab(salida, SimpleNamespace(run_id="test"))

    abiertos = bl.abiertos()
    assert {i["area"] for i in abiertos} == {"web", "dev", "humano"}   # el área falsa no entró
    assert all(i["origenes"] == ["web_auditor"] for i in abiertos)

    # Y se cierran por id, con la misma cosecha.
    dev = bl.abiertos("dev")[0]
    agente._harvest_collab(f"RESUELTO({dev['id']}): commit 1234abc, daily_batch ya reserva cupo",
                           SimpleNamespace(run_id="test"))
    assert bl.abiertos("dev") == []


def test_harvest_no_corta_el_pendiente_ni_anota_los_que_no_existen(tmp_path, monkeypatch):
    """El 2026-08-13 seis de los catorce pendientes abiertos eran ilegibles: cuatro
    cortados a mitad de frase porque el LLM envolvió el renglón y el regex leía
    hasta el fin de LÍNEA, y uno que decía 'ninguno en esta corrida'. Un registro
    con 43% de ruido no le hace presión a nadie."""
    from app.agents.registry import get_agent
    from app.integrations import backlog as bl
    monkeypatch.setattr(bl, "_FILE", tmp_path / "backlog.json")

    salida = (
        "PENDIENTE(humano): confirmar si tenemos cuenta de TikTok abierta y\n"
        "si podemos publicar sin pasar por el sandbox\n"
        "\n"
        "PENDIENTE(dev): ninguno en esta corrida. Las correcciones son de web\n"
    )
    get_agent("seo_specialist")._harvest_collab(salida, SimpleNamespace(run_id="test"))

    abiertos = bl.abiertos()
    assert [i["area"] for i in abiertos] == ["humano"]          # el "ninguno" no entró
    assert abiertos[0]["titulo"].endswith("sin pasar por el sandbox")


def test_la_palabra_del_gate_sale_del_caption_del_post():
    """Las keywords del comment-gate rotan con cada tanda (AGENTE en W34, once
    distintas en W35). Mantenerlas a mano en un regex era una tarea semanal que se
    olvidaba: la palabra la pide el propio caption, así que se lee de ahí."""
    from app.integrations.comment_watch import _GATE_WORDS, _palabras_del_post

    cap = "3 pedidos perdidos. Comentá AUDITORIA y te mando la planilla."
    assert _palabras_del_post(cap) == {"auditoria"}
    assert not _GATE_WORDS.search("auditoria")            # no está en la lista fija
    assert _GATE_WORDS.search("me pasás la DEMO?")        # las de siempre siguen
    assert _palabras_del_post('Escribí "REPOSICION" abajo') == {"reposicion"}


def test_el_feed_pasado_de_tope_drena_mas_rapido(tmp_path, monkeypatch):
    """A 1/día una cola pasada de tope no se recupera: el 2026-08-17 había 15
    pendientes de feed, el más viejo del 03/08, y 5 vencieron sin salir mientras
    `enqueue()` rechazaba lo nuevo. Por encima del tope drena de a 3; por debajo,
    vuelve solo a 1 por día."""
    from app.integrations import publish_queue as pq
    monkeypatch.setattr(pq, "_data_dir", lambda: tmp_path)

    class _FakeSP:
        enabled = staticmethod(lambda: True)
        publish = staticmethod(lambda *a, **k: {"ok": True, "results": {"instagram": {"ok": True}}})

    monkeypatch.setitem(__import__("sys").modules, "app.integrations.social_publish", _FakeSP)
    monkeypatch.setattr(pq, "_notify_discord", lambda *a, **k: None)
    monkeypatch.setattr(pq, "backfill_permalinks", lambda: {})

    for i in range(pq.MAX_PENDING_FEED):
        assert pq.enqueue(f"img{i}.jpg", caption=f"pieza {i}", kind="post")
    # El 15 no entra por `enqueue` (el tope lo frena); en producción la cola quedó
    # pasada de tope desde antes de que el tope existiera. Se simula igual.
    store = pq.load_store()
    store["items"].insert(0, dict(store["items"][0], id="extra", image="extra.jpg"))
    pq.save_store(store)
    assert pq.pending_count(lane="feed") > pq.MAX_PENDING_FEED

    res = pq.drain_one()
    assert len([res["feed"]] + res.get("feed_extra", [])) == pq.FEED_CATCHUP
    assert pq.pending_count(lane="feed") == pq.MAX_PENDING_FEED + 1 - pq.FEED_CATCHUP

    # ya está bajo el tope: al otro día vuelve a salir una sola (force saltea el 1/día)
    res2 = pq.drain_one(force=True)
    assert "feed_extra" not in res2 and res2["feed"]["ok"]

    # Y una pieza en su último día SALE: vencer antes de publicar era garantizar que
    # no saliera nunca. Se la envejece a un día del TTL.
    store = pq.load_store()
    viejo = (__import__("datetime").datetime.now(__import__("datetime").timezone.utc)
             - __import__("datetime").timedelta(days=pq.PENDING_TTL_DIAS - 1)).isoformat()
    for it in store["items"]:
        if it.get("status") == "pending":
            it["created_at"] = viejo
    pq.save_store(store)
    res3 = pq.drain_one(force=True)
    assert len([res3["feed"]] + res3.get("feed_extra", [])) == pq.FEED_CATCHUP


def test_el_titulo_largo_se_corta_donde_se_entiende(tmp_path, monkeypatch):
    """El 2026-08-17 cinco de los 24 abiertos terminaban a mitad de palabra
    ("...publicar la página con outline d") porque el tope de 300 cortaba a la
    bruta. El agente escribe un párrafo donde va un título: el corte tiene que
    caer en la última oración cerrada, o al menos en una palabra entera."""
    from app.integrations import backlog as bl
    monkeypatch.setattr(bl, "_FILE", tmp_path / "backlog.json")

    parrafo = ("Recortar el title tag a 54 caracteres. " + "Reescribir la meta description. " * 8
               + "Y despues publicar la pagina con outline de este plan")
    assert len(parrafo) > 300
    it = bl.abrir("web", parrafo, origen="test")

    assert it["titulo"].endswith("…")
    assert it["titulo"][:-1].endswith(("description", "chars", "caracteres"))   # palabra entera
    assert 150 < len(it["titulo"]) <= 301
    assert bl.abrir("web", "corto pero valido para el minimo")["titulo"][-1] != "…"


def test_watchdog_caza_el_reporte_enano_sin_marcador(tmp_path, monkeypatch):
    """El 2026-08-10 leadhunter entregó 723 bytes diciendo que el reporte estaba
    'impreso en la respuesta'. Terminó bien y sin firma de degradación, así que
    ningún chequeo lo vio: los 10 leads se perdieron y outbound ingestó 0."""
    from app.integrations import watchdog as wd
    monkeypatch.setattr(wd, "_DATA", tmp_path)
    hoy = __import__("datetime").datetime.now(wd._TZ).strftime("%Y-%m-%d")

    for i, dia in enumerate(["2026-08-06", "2026-08-07", "2026-08-08", "2026-08-09"]):
        (tmp_path / f"leadhunter-report-{dia}.md").write_text("x" * 30000, encoding="utf-8")
    (tmp_path / f"leadhunter-report-{hoy}.md").write_text(
        "Listo. El reporte completo de 10 leads está impreso en la respuesta.", encoding="utf-8")

    degradados = dict(wd._degraded_reports(SimpleNamespace()))
    assert "leadhunter" in degradados
    assert "bytes" in degradados["leadhunter"]

    # Un agente que SIEMPRE entrega corto no es una falla: se compara contra sí mismo.
    for dia in ["2026-08-06", "2026-08-07", "2026-08-08"]:
        (tmp_path / f"inbox-assistant-report-{dia}.md").write_text("ok, 3 hilos", encoding="utf-8")
    (tmp_path / f"inbox-assistant-report-{hoy}.md").write_text("ok, 2 hilos", encoding="utf-8")
    assert "inbox_assistant" not in dict(wd._degraded_reports(SimpleNamespace()))


def test_watchdog_avisa_pendientes_del_dueno_a_agencia(tmp_path, monkeypatch):
    """Los `humano` van a #agencia, no al canal de errores, y con escalones: al
    aparecer y al cruzar 3/7/14/21/30 días. Avisar todos los días del mismo
    pendiente es exactamente cómo el trío de la web sobrevivió 22 briefs."""
    from app.integrations import watchdog as wd, backlog as bl
    monkeypatch.setattr(wd, "_DATA", tmp_path)
    monkeypatch.setattr(wd, "_STATE", tmp_path / "watchdog-state.json")
    monkeypatch.setattr(bl, "_FILE", tmp_path / "backlog.json")
    monkeypatch.setattr(wd, "_check_gmail", lambda s: ("skip", "sin credenciales"))
    monkeypatch.setattr(wd, "_missed_runs", lambda s: [])

    bl.abrir("humano", "Decidir quien firma el cierre de CLAMEVET", dias_atras=19)
    bl.abrir("dev", "El build de Astro de la landing falla", dias_atras=1)

    enviados = []

    class _Discord:
        def send(self, _msg, url=None, embed=None):
            enviados.append((url, embed.title, embed.description))

    s = SimpleNamespace(gmail_configured=False, watchdog_grace_min=30,
                        discord_agencia_webhook_url="https://discord.test/agencia",
                        discord_webhook_errors="https://discord.test/errores",
                        discord_webhook_url="")
    out = wd.check(s, discord=_Discord())

    agencia = [e for e in enviados if e[0] == "https://discord.test/agencia"]
    assert len(agencia) == 1, "el pendiente humano tiene que ir a #agencia"
    assert "19 día(s)" in agencia[0][2]                    # con la edad, que es la presión
    assert "CLAMEVET" in agencia[0][2]
    assert "Astro" not in agencia[0][2]                    # el dev NO es tarea del dueño
    assert out["backlog_humano_avisados"] == 1

    # Segunda pasada del mismo día: ya avisado, no vuelve a molestar.
    enviados.clear()
    assert wd.check(s, discord=_Discord())["backlog_humano_avisados"] == 0
    assert enviados == []


def test_watchdog_no_marca_avisado_si_no_hay_canal(tmp_path, monkeypatch):
    """Sin webhook el pendiente NO puede quedar marcado como avisado: se silenciaría
    hasta el próximo escalón, que puede caer una semana después."""
    from app.integrations import watchdog as wd, backlog as bl
    monkeypatch.setattr(wd, "_DATA", tmp_path)
    monkeypatch.setattr(wd, "_STATE", tmp_path / "watchdog-state.json")
    monkeypatch.setattr(bl, "_FILE", tmp_path / "backlog.json")
    monkeypatch.setattr(wd, "_check_gmail", lambda s: ("skip", ""))
    monkeypatch.setattr(wd, "_missed_runs", lambda s: [])
    bl.abrir("humano", "Dar los 9 numeros reales de los contadores del home")

    class _Discord:
        def send(self, *a, **k):
            pass

    s = SimpleNamespace(gmail_configured=False, watchdog_grace_min=30,
                        discord_agencia_webhook_url="", discord_webhook_errors="",
                        discord_webhook_url="")
    wd.check(s, discord=_Discord())
    # Con el canal ya configurado, el mismo pendiente TIENE que salir.
    s.discord_agencia_webhook_url = "https://discord.test/agencia"
    assert wd.check(s, discord=_Discord())["backlog_humano_avisados"] == 1


def test_autopsia_habla_cuando_nada_tracciona(monkeypatch):
    """El feedback de contenido se apagaba justo cuando la noticia era mala: con
    todo en 0 devolvía '' y los agentes seguían produciendo más de lo mismo sin
    enterarse nunca. Al 2026-08-12 eran 20 piezas con 0 interacciones."""
    from app.integrations import content_autopsy as ca

    cero = [{"caption": f"pieza {i}", "type": "FEED", "permalink": "", "reach": 3,
             "interactions": 0, "saved": 0, "shares": 0} for i in range(20)]
    monkeypatch.setattr(ca, "analyze", lambda n=20: cero)
    txt = ca.block()
    assert "NO ESTÁ TRACCIONANDO" in txt
    assert "20 piezas" in txt and "alcance sumado: 60" in txt
    assert "PENDIENTE(humano)" in txt          # la salida no es "escribí otra pieza"

    # Cuenta que recién arranca: 3 piezas en 0 no concluyen nada, sigue en silencio.
    monkeypatch.setattr(ca, "analyze", lambda n=20: cero[:3])
    assert ca.block() == ""

    # Con tracción real gana el bloque de siempre (top/bottom), no el de alarma.
    con = [dict(cero[0], interactions=42, caption="la que funcionó"),
           *[dict(c, interactions=1) for c in cero[1:6]]]
    monkeypatch.setattr(ca, "analyze", lambda n=20: con)
    txt = ca.block()
    assert "QUÉ FUNCIONÓ DE LO NUESTRO" in txt and "NO ESTÁ TRACCIONANDO" not in txt


def test_chief_conserva_el_final_de_los_reportes_largos():
    """El Chief cortaba con txt[:2200] sobre reportes de 30-40 KB: leía la portada
    y tiraba las conclusiones, los quick wins y los pedidos al humano, que viven al
    final. Por eso repetía hallazgos en vez de accionarlos."""
    from app.agents.chief_of_staff import _recortar, _PER_REPORT

    largo = "PORTADA Y METODOLOGIA\n" + ("relleno " * 5000) + "\nQUICK WIN: poner el H1 del home"
    out = _recortar(largo)
    assert len(out) < len(largo)
    assert "PORTADA Y METODOLOGIA" in out            # el arranque sigue estando
    assert "QUICK WIN: poner el H1 del home" in out  # y ahora TAMBIÉN el final
    assert "recortado el medio" in out

    corto = "un reporte breve que entra entero"
    assert _recortar(corto) == corto


def test_chief_ve_a_todos_los_agentes_del_roster():
    """Con tope 12 y 18 agentes en el cron, un lunes se caían 4 — y como el orden es
    por hora de entrega, los que se perdían eran los de la mañana (leadhunter 08:00,
    cabecera del embudo) del único que lee todo."""
    from app.agents.chief_of_staff import _MAX_REPORTS
    from app.scheduler import DEFAULT_SCHEDULES
    assert _MAX_REPORTS >= len(DEFAULT_SCHEDULES), (
        f"{len(DEFAULT_SCHEDULES)} agentes con cron pero el Chief lee {_MAX_REPORTS}")


def test_bitacora_conserva_el_error_del_deploy_fallido(tmp_path, monkeypatch):
    """La bitácora es lo ÚNICO que la próxima corrida sabe de las anteriores, y la
    escribe el modelo. El 2026-08-12 el modelo NO emitió su bloque Y el deploy
    falló: la iteración se perdió entera y la próxima iba a repetir el mismo
    cambio contra el mismo error, con el temp ya borrado."""
    from app.integrations import seo_progress as sp
    monkeypatch.setattr(sp, "_PATH", tmp_path / "seo-progress.md")

    sp.write("# Bitácora SEO/GEO\n## Estado\nlínea de base vieja")
    assert sp.anotar_fallo("2026-08-12", "vercel deploy falló: Error en precios.astro línea 41")

    txt = sp.read()
    assert "El último deploy FALLÓ" in txt
    assert "precios.astro línea 41" in txt
    assert "línea de base vieja" in txt          # no se pisa lo que ya había
    assert txt.index("FALLÓ") < txt.index("línea de base vieja")   # el aviso va arriba

    # Un segundo fallo REEMPLAZA al anterior: importa el último, no la pila.
    sp.anotar_fallo("2026-08-13", "otro error distinto")
    txt2 = sp.read()
    assert txt2.count("El último deploy FALLÓ") == 1
    assert "otro error distinto" in txt2 and "precios.astro" not in txt2
    assert "línea de base vieja" in txt2


def test_landing_facts_mide_el_html_de_verdad(monkeypatch):
    """El 'H1 del home vacío' se reportó 22 días seguidos en tres auditorías y era
    falso. Un hallazgo inventado se lleva una de las tres acciones diarias del dueño
    y, con un backlog que acumula edad, encima gana autoridad."""
    from app.integrations import landing_facts as lf

    html = ("<html><head><title>Automiq</title>"
            '<meta name="description" content="Automatizacion con IA">'
            "<script>gtag('config','AW-18330940659')</script></head><body>"
            '<h1 class="reveal">Automatizacion con IA a medida que '
            '<span class="grad-text">potencia tu empresa</span></h1>'
            + '<div class="stat">0</div>' * 9 + "</body></html>")

    class _R:
        status_code, text = 200, html

    monkeypatch.setattr(lf, "_CACHE", {"t": 0.0, "url": "", "datos": {}})
    monkeypatch.setitem(__import__("sys").modules, "httpx",
                        SimpleNamespace(get=lambda *a, **k: _R()))
    d = lf.medir("https://automiq.agency")
    assert d["ok"]
    assert d["h1"] == "Automatizacion con IA a medida que potencia tu empresa"
    assert d["h1_cantidad"] == 1
    assert d["contadores_en_cero"] == 9
    assert d["google_ads"] is True and d["ga4"] is False and d["meta_pixel"] is False

    txt = lf.bloque("https://automiq.agency")
    assert "NO HAY H1" not in txt and "potencia tu empresa" in txt
    assert "Contadores mostrando 0: 9" in txt


def test_landing_facts_sin_red_no_inventa(monkeypatch):
    """Si no se pudo medir, el bloque tiene que PROHIBIR afirmar — ese vacío es
    justo por donde se colaba el hallazgo inventado."""
    from app.integrations import landing_facts as lf

    def _boom(*a, **k):
        raise RuntimeError("sin red")

    monkeypatch.setattr(lf, "_CACHE", {"t": 0.0, "url": "", "datos": {}})
    monkeypatch.setitem(__import__("sys").modules, "httpx", SimpleNamespace(get=_boom))
    txt = lf.bloque("https://automiq.agency")
    assert "No pude bajar" in txt and "NO afirmes nada" in txt


def test_web_optimizer_cierra_los_pendientes_que_ejecuta(tmp_path, monkeypatch):
    """web_optimizer overridea run() entero y por eso se salteaba la cosecha de
    marcadores de la clase base — siendo el ÚNICO agente que ejecuta trabajo del
    backlog. El 2026-08-12 creó /gracias, emitió RESUELTO(...) y el ítem quedó
    abierto igual: el pendiente se leía como no hecho."""
    from app.agents.base import BaseAgent
    from app.agents.registry import get_agent
    from app.integrations import backlog as bl
    monkeypatch.setattr(bl, "_FILE", tmp_path / "backlog.json")
    monkeypatch.setattr(BaseAgent, "post_process", lambda self, t, c: t)

    it = bl.abrir("web", "La pagina /precios no tiene formulario de contacto")
    agente = get_agent("web_optimizer")
    ctx = SimpleNamespace(run_id="test", discord=None, args={},
                          settings=SimpleNamespace(discord_webhook_for=lambda n: ""))

    agente._deliver(ctx, f"Listo el preview.\nRESUELTO({it['id']}): cree el form en "
                         "src/pages/precios.astro y deployo el preview OK\n"
                         "PENDIENTE(humano): hace falta el ID de GA4 para cablear la medicion")
    assert bl.abiertos("web") == []                    # el que ejecutó, se cerró
    humanos = bl.abiertos("humano")
    assert len(humanos) == 1 and "GA4" in humanos[0]["titulo"]


def test_inventario_del_workdir_distingue_las_hipotesis(tmp_path):
    """Cuando un agente entrega un resumen en vez del entregable (leadhunter,
    2026-08-10: 723 bytes contra 28-42 KB de sus otros días) el workdir ya se borró
    y no se puede separar 'no escribió nada' de 'lo escribió en un .json que el
    rescate no mira'. El inventario es esa evidencia."""
    from app.clients.hermes import _inventario

    (tmp_path / "leads.json").write_bytes(b"x" * 5000)
    (tmp_path / "notas.md").write_bytes(b"y" * 200)
    sub = tmp_path / "tmp"
    sub.mkdir()
    (sub / "scratch.txt").write_bytes(b"z" * 50)
    ruido = tmp_path / "_cc_stdout.bin"
    ruido.write_bytes(b"0" * 9999)

    inv = _inventario(str(tmp_path), {str(ruido)})
    assert "leads.json:5000" in inv                 # el entregable grande, visible
    assert "notas.md:200" in inv
    assert "scratch.txt:50" in inv                  # también lo anidado
    assert "_cc_stdout" not in inv                  # el stdout no es un artefacto
    assert inv.index("leads.json") < inv.index("notas.md")   # más grande primero

    assert _inventario(str(tmp_path / "no-existe"), set()) == ""   # nunca revienta


def test_hermes_avisa_al_canal_de_errores_con_la_evidencia(monkeypatch):
    """El watchdog caza el reporte enano recién en su próxima pasada; para
    leadhunter (08:00) eso caía 14:15, DESPUÉS de outbound (12:00). Este aviso salta
    apenas pasa y lleva la evidencia para decidir si re-correrlo."""
    from app.clients import hermes as h, discord as dc

    enviados = []

    class _WH:
        def __init__(self, settings):
            pass

        def send(self, _c, url=None, embed=None):
            enviados.append((url, embed.title, embed.description))

        def close(self):
            pass

    monkeypatch.setattr(dc, "DiscordWebhook", _WH)
    s = SimpleNamespace(discord_webhook_errors="https://discord.test/errores",
                        discord_webhook_url="https://discord.test/general")
    h._avisar_errores(s, "leadhunter", 723, 0, "leads.json:5000 · notas.md:200", "…resumen final")

    assert len(enviados) == 1
    url, titulo, desc = enviados[0]
    assert url == "https://discord.test/errores"     # errores, no el canal general
    assert "leadhunter" in desc and "723" in desc
    assert "leads.json:5000" in desc                 # la evidencia, no sólo el síntoma
    assert "outbound ingesta 0" in desc              # y qué significa para el día


def test_hermes_aviso_no_tira_la_corrida_si_discord_falla(monkeypatch):
    """El aviso es best-effort: una corrida que SÍ entregó algo no se puede perder
    porque el webhook esté caído."""
    from app.clients import hermes as h, discord as dc

    class _Roto:
        def __init__(self, settings):
            raise RuntimeError("webhook caido")

    monkeypatch.setattr(dc, "DiscordWebhook", _Roto)
    h._avisar_errores(SimpleNamespace(discord_webhook_errors="", discord_webhook_url=""),
                      "leadhunter", 723, 0, "leads.json:5000", "resumen")


def test_watchdog_corre_antes_de_que_salga_el_outbound():
    """Sin una pasada entre leadhunter (08:00) y outbound (12:00), un reporte enano
    se sabía 14:15 y el día ya estaba perdido."""
    from apscheduler.triggers.cron import CronTrigger
    from app.scheduler import WATCHDOG_CRON, DEFAULT_SCHEDULES

    horas = {int(h) for h in WATCHDOG_CRON.split()[1].split(",")}
    lead = int(DEFAULT_SCHEDULES["leadhunter"].split()[1])
    out = int(DEFAULT_SCHEDULES["outbound"].split()[1])
    assert any(lead < h < out for h in horas), (
        f"watchdog corre {sorted(horas)}: ninguna pasada entre leadhunter ({lead}) y outbound ({out})")
    CronTrigger.from_crontab(WATCHDOG_CRON)          # y sigue siendo un cron válido


def test_la_instruccion_de_pendientes_exige_verificar():
    """Dos fantasmas en dos días: un 'H1 vacío' que nunca estuvo vacío (22 días
    seguidos, 3 auditorías) y una 'casilla inexistente' que era un grupo que
    funciona. Un pendiente falso se lleva una acción del día del dueño y, como el
    registro acumula días, con el tiempo parece MÁS urgente en vez de menos."""
    from app.agents.registry import get_agent
    bloque = get_agent("inbox_assistant")._collab_block()
    assert "PENDIENTE(<area>)" in bloque
    assert "VERIFICASTE" in bloque
    assert "sospecha" in bloque.lower()


def test_backlog_acepta_una_nota_del_dueno_sin_cerrar(tmp_path, monkeypatch):
    """Faltaba el canal de vuelta: el sistema sabía pedir y no sabía escuchar. Con
    CLAMEVET el dueño ya estaba en contacto y los agentes se lo seguían pidiendo."""
    from app.integrations import backlog as bl
    monkeypatch.setattr(bl, "_FILE", tmp_path / "backlog.json")

    it = bl.abrir("humano", "CLAMEVET: definir quien firma el mail de cierre", dias_atras=19)
    assert bl.anotar(it["id"], "Ya estoy en contacto directo, de esto me ocupo yo") is not None
    abiertos = bl.abiertos("humano")
    assert len(abiertos) == 1                       # la nota NO lo cierra
    assert abiertos[0]["notas"][0]["por"] == "dueño"

    txt = bl.bloque("humano")
    assert "de esto me ocupo yo" in txt
    assert "no lo vuelvas a pedir" in txt           # y manda sobre lo que el agente suponga

    assert bl.anotar("noexiste", "hola") is None
    assert bl.anotar(it["id"], "x") is None          # nota vacía no entra


def test_la_vara_de_humano_exige_agotar_lo_reversible():
    """El agente escalaba cualquier elección: 'defino si publico con el nombre real
    del cliente o uno genérico' llegó a #agencia como acción del dueño, teniendo una
    opción conservadora obvia y reversible."""
    from app.agents.registry import get_agent
    bloque = get_agent("content_creator")._collab_block()
    assert "último recurso" in bloque
    assert "conservadora" in bloque
    assert "nombre real del" in bloque              # el caso real, como ejemplo de lo que NO va


def test_lead_de_la_web_se_distingue_de_la_prospeccion():
    """Los formularios sí se guardaban, pero quedaban indistinguibles entre 350
    leads de prospección: en el panel parecía que no llegaban."""
    from app.integrations import leads_store as ls
    v = ls.lead_view({"key": "k", "company": "Corralón X", "origen": "web",
                      "mensaje": "quiero automatizar los pedidos"})
    assert v["origen"] == "web" and "automatizar" in v["mensaje"]
    assert ls.lead_view({"key": "k2"})["origen"] == "prospeccion"


def test_dashboard_muestra_lo_del_dueno_y_los_leads_web():
    """Las dos cosas que el dueño pidió ver en el panel: lo que depende de él (con
    caja para contestar sin cerrar) y los formularios de la web, que sí se guardaban
    pero quedaban indistinguibles entre 350 leads de prospección."""
    from app.main import app
    with TestClient(app) as client:
        html = client.get("/dashboard").text
        for marca in ("overviewBacklog", "overviewInbound",
                      "backlogHumanoHtml", "inboundWebHtml",
                      "bklNota", "bklListo",
                      "/api/backlog?area=humano", "/api/backlog/'+id+'/nota",
                      "l.origen==='web'"):
            assert marca in html, f"falta {marca} en el dashboard"
        # La tarjeta de SEO tiene que explicar el atraso de Google: sin eso se lee
        # como panel desactualizado y se desconfía de un número que está bien.
        assert "días de atraso" in html


def test_citar_un_pendiente_existente_no_crea_otro(tmp_path, monkeypatch):
    """El 2026-08-12 seo_specialist emitió tres PENDIENTE que decían "(PENDIENTE
    22dfcb1e, ... sin duplicar — solo referencia)" y entraron igual como ítems
    nuevos: el dueño terminó con la misma tarea tres veces. El dedup difuso no los
    agarra — reformulados dan 0.48 de similitud, y bajar el umbral a eso fusionaría
    cosas distintas."""
    from app.integrations import backlog as bl
    monkeypatch.setattr(bl, "_FILE", tmp_path / "backlog.json")

    orig = bl.abrir("humano", "Pasar los IDs reales de Meta Pixel y GA4 para cablear la medicion",
                    origen="web_optimizer")
    ref = bl.abrir("humano",
                   "pasar IDs reales de Meta Pixel y GA4 para cablear la medicion. Sin esto no "
                   f"se puede medir el sprint. (PENDIENTE {orig['id']}, solo referencia)",
                   origen="seo_specialist")
    assert ref["id"] == orig["id"]                  # es el MISMO ítem
    assert len(bl.abiertos("humano")) == 1          # y no aparece dos veces
    assert ref["veces"] == 2
    assert sorted(ref["origenes"]) == ["seo_specialist", "web_optimizer"]

    # Un id que no existe no bloquea un pendiente legítimo.
    bl.abrir("humano", "Revisar el preview y promoverlo (ver deadbeef, que ya no está)",
             origen="seo_specialist")
    assert len(bl.abiertos("humano")) == 2


def test_si_el_dueno_ya_contesto_el_watchdog_no_insiste(tmp_path, monkeypatch):
    """Dijo 'de CLAMEVET me ocupo yo' y el aviso se lo seguía mandando igual.
    Insistir sobre algo que ya contestó es lo que convierte el canal en ruido."""
    from app.integrations import watchdog as wd, backlog as bl
    monkeypatch.setattr(wd, "_DATA", tmp_path)
    monkeypatch.setattr(wd, "_STATE", tmp_path / "watchdog-state.json")
    monkeypatch.setattr(bl, "_FILE", tmp_path / "backlog.json")
    monkeypatch.setattr(wd, "_check_gmail", lambda s: ("skip", ""))
    monkeypatch.setattr(wd, "_missed_runs", lambda s: [])

    mio = bl.abrir("humano", "CLAMEVET: definir quien firma el cierre", dias_atras=19)
    bl.abrir("humano", "Pasar los IDs reales de Meta Pixel y GA4", dias_atras=1)
    bl.anotar(mio["id"], "De esto me ocupo yo, ya estoy en contacto")

    enviados = []

    class _D:
        def send(self, _c, url=None, embed=None):
            enviados.append(embed.description)

    s = SimpleNamespace(gmail_configured=False, watchdog_grace_min=30,
                        discord_agencia_webhook_url="https://discord.test/agencia",
                        discord_webhook_errors="", discord_webhook_url="")
    assert wd.check(s, discord=_D())["backlog_humano_avisados"] == 1
    texto = "\n".join(enviados)
    assert "Meta Pixel" in texto                 # el que no contestó, sí avisa
    assert "CLAMEVET" not in texto               # el que contestó, no


def _mision_deleg(tmp_path, monkeypatch, agentes):
    from app.integrations import missions_store as mis
    monkeypatch.setattr(mis, "_json_path", lambda: tmp_path / "missions.json")
    monkeypatch.setattr(mis.db, "enabled", lambda: False)
    mis.create_mission(objective="Delegaciones del cierre del 2026-08-12",
                       agents=list(agentes),
                       plan=[{"agent": a, "task": f"tarea de {a}"} for a in agentes])
    return mis


def test_la_delegacion_se_cierra_y_la_mision_cambia_de_estado(tmp_path, monkeypatch):
    """Al 2026-08-12 había 15 misiones de delegación y las 15 seguían en `lanzada`:
    el Chief juzgaba si se habían cumplido pero lo escribía sólo en prosa, y
    update_mission no la llamaba nadie. El contador subía 1 por día y no distinguía
    delegar bien de delegar al vacío."""
    mis = _mision_deleg(tmp_path, monkeypatch, ["outbound", "social_media"])

    assert mis.list_missions()[0]["status"] == "lanzada"
    mis.marcar_delegacion("outbound", True, "mando 6 mails day-0, mode_ejecutado=day0")
    assert mis.list_missions()[0]["status"] == "parcial"      # falta el otro
    mis.marcar_delegacion("social_media", False, "no separo feed de historias")
    m = mis.list_missions()[0]
    assert m["status"] == "parcial"                            # uno sí, uno no
    hechos = {p["agent"]: p["hecho"] for p in m["plan"]}
    assert hechos == {"outbound": True, "social_media": False}

    # Sin nada pendiente para ese agente, no inventa un cierre.
    assert mis.marcar_delegacion("outbound", True, "de nuevo") is None


def test_todas_cumplidas_cierra_la_mision(tmp_path, monkeypatch):
    mis = _mision_deleg(tmp_path, monkeypatch, ["leadhunter"])
    mis.marcar_delegacion("leadhunter", True, "reporto verification_rate al inicio")
    assert mis.list_missions()[0]["status"] == "cumplida"


def test_el_agente_ve_su_propio_historial(tmp_path, monkeypatch):
    """El bucle de mejora: un agente que ve 'cumpliste 1 de 2, y esta quedó sin
    hacer' tiene el dato para corregirse. Antes ese resultado se perdía al día
    siguiente con el brief."""
    mis = _mision_deleg(tmp_path, monkeypatch, ["outbound", "social_media"])
    mis.marcar_delegacion("outbound", True, "mando 6 day-0")
    mis.marcar_delegacion("social_media", False, "no separo feed de historias")

    txt = mis.bloque_cumplimiento("social_media")
    assert "0 de 1" in txt
    assert "no separo feed de historias" in txt
    assert mis.bloque_cumplimiento("web_optimizer") == ""      # sin historial, no ensucia

    c = mis.cumplimiento("outbound")
    assert c["cumplidas"] == 1 and c["juzgadas"] == 1


def test_chief_lleva_su_veredicto_al_registro(tmp_path, monkeypatch):
    """El puente que faltaba: el Chief escribía ✅/⏫ en prosa y la misión seguía
    'lanzada'. Ahora la línea DELEG_OK/DELEG_NO la cierra de verdad."""
    from app.agents.registry import get_agent
    mis = _mision_deleg(tmp_path, monkeypatch, ["outbound", "leadhunter"])
    chief = get_agent("chief_of_staff")

    brief = ("## Seguimiento\n"
             "- ✅ outbound: salieron los day-0.\n"
             "`DELEG_OK(outbound)`: mando 6 primeros toques, mode_ejecutado=day0\n"
             "* **DELEG_NO(leadhunter):** entrego un resumen de 723 bytes, sin leads\n"
             "DELEG_OK(agente_inventado): no existe, se ignora\n")
    cerradas = chief._cerrar_delegaciones(brief, SimpleNamespace(run_id="t"))

    assert sorted(cerradas) == [("leadhunter", False), ("outbound", True)]
    m = mis.list_missions()[0]
    assert m["status"] == "parcial"
    assert {p["agent"]: p["hecho"] for p in m["plan"]} == {"outbound": True, "leadhunter": False}


def test_video_bank_reparte_el_stock_a_lo_largo_del_ano(tmp_path, monkeypatch):
    """El bundle de Higgsfield dura 10 días y da para un año de contenido, pero
    publish_queue tiene tope 14 y vence a los 14 días: meterle 156 videos sería
    perderlos casi todos. El banco los guarda y los suelta cuando toca."""
    from app.integrations import video_bank as vb
    monkeypatch.setattr(vb, "_FILE", tmp_path / "video-bank.json")

    for i in range(6):
        assert vb.agregar(f"Nazareno mira a camara y dice el gancho numero {i}, plano medio 9:16",
                          copy=f"copy {i}", origen="tiktok_creator")
    assert vb.agregar("corto") is None                       # prompt sin sustancia

    assert vb.resumen()["sin_generar"] == 6
    assert vb.marcar_listo(1, "/media/001.mp4")["archivo"] == "001.mp4"
    vb.marcar_listo(2, "/media/002.mp4")
    assert vb.planificar(por_semana=3) == 2

    listos = [i for i in vb.toca_hoy() ]
    assert len(listos) == 1                                  # el #2 cae a +2 días
    assert listos[0]["n"] == 1
    assert vb.marcar_encolado(1) is True
    assert vb.marcar_encolado(1) is False                    # no se encola dos veces
    assert vb.toca_hoy() == []


def test_video_bank_aparea_por_numero_de_archivo(tmp_path, monkeypatch):
    """El humano genera en Higgsfield en orden y guarda 001.mp4, 002.mp4… Ese número
    es lo único que permite saber qué clip corresponde a qué guion."""
    from app.integrations import video_bank as vb
    assert vb.numero_de("012.mp4") == 12
    assert vb.numero_de("007 (1).mp4") == 7
    assert vb.numero_de("sin-numero.mp4") is None


def test_el_stock_gotea_sin_reventar_la_cola(tmp_path, monkeypatch):
    """El stock NO puede vivir en publish_queue: esa cola tiene tope 14 de feed y
    vence lo que lleva 14 días. Si el banco empuja más de lo que la cola drena, el
    año de contenido se vencería adentro en vez de afuera."""
    from app.integrations import video_bank as vb
    monkeypatch.setattr(vb, "_FILE", tmp_path / "video-bank.json")

    encoladas = []
    fake_pq = SimpleNamespace(
        MAX_PENDING_FEED=2,
        pending_count=lambda lane=None: len(encoladas),
        enqueue=lambda image, caption="", source="", kind="post": (
            encoladas.append(image) or {"id": "x"}),
    )
    monkeypatch.setitem(__import__("sys").modules, "app.integrations.publish_queue", fake_pq)
    # `from . import publish_queue` resuelve por atributo del paquete cuando el módulo
    # real ya se importó (otro test lo hace): sin esto el falso se ignora y el drenaje
    # mide contra la cola de verdad.
    import app.integrations as _pkg
    monkeypatch.setattr(_pkg, "publish_queue", fake_pq, raising=False)

    for i in range(4):
        vb.agregar(f"Nazareno de frente, plano medio, dice el gancho {i} en 9:16 realista")
        vb.marcar_listo(i + 1, f"/media/hf-{i+1:03d}.mp4")
    # Todas con fecha de hoy o antes: la cola es el único freno.
    d = vb._load()
    for it in d["items"]:
        it["publicar_el"] = "2020-01-01"
    vb._save(d)

    assert vb.drenar(max_por_corrida=5)["encoladas"] == [1, 2]   # frena en el tope
    assert len(encoladas) == 2
    r = vb.drenar(max_por_corrida=5)
    assert r["encoladas"] == [] and r["cola_llena"] is True      # y no insiste
    assert vb.resumen()["por_estado"]["listo"] == 2              # el resto espera turno


def test_la_identidad_de_nazareno_se_pega_en_codigo(monkeypatch):
    """El primer lote salió con 0 de 20 prompts conteniendo alguna ancla de
    NAZARENO_IDENTITY, y dos decían "dark brown hair" cuando es castaño CLARO.
    Pedirle a un LLM que reproduzca 500 caracteres exactos en 156 piezas es pedirle
    que no derive: saldrían 156 personas distintas."""
    from app.integrations import video_bank as vb
    from app.agents.tiktok_creator import NAZARENO_IDENTITY

    item = {"prompt": "Vertical 9:16 video, medium shot of a young Argentine man with short "
                      "dark brown hair, light olive skin, sitting in a small cafe with warm "
                      "window light, holding a tablet. Camera slowly pushes in."}
    p = vb.prompt_final(item)

    assert NAZARENO_IDENTITY.strip() in p            # la identidad EXACTA, no parafraseada
    assert "dark brown hair" not in p.lower()        # y sin la contradicción del modelo
    assert "young argentine man" not in p.lower()
    assert "small cafe" in p and "pushes in" in p    # la escena sobrevive entera
    assert "9:16" in p

    # Sin escena tampoco se rompe: queda al menos la identidad.
    assert NAZARENO_IDENTITY.strip() in vb.prompt_final({"prompt": ""})


def test_vertical_agro_no_cae_en_manufactura():
    """El rubro de Sumiagro dice "herramientas para agro, construcción e industria":
    la palabra "industria" matcheaba manufactura y la demo mostraba una conversación
    de piezas a plano. El alias de agro/herramientas tiene que ganar."""
    from app.integrations.lead_demo import _CONVOS, _vertical_for

    assert _vertical_for("herramientas para agro, construcción e industria") == "repuestos"
    assert _vertical_for("repuestos y service de maquinaria") == "repuestos"
    assert _vertical_for("industria metalúrgica") == "manufactura"    # no se rompió
    assert _CONVOS["repuestos"][0]["from"] == "them"                  # arranca el cliente


def test_pendiente_resuelto_se_reabre_no_se_duplica(tmp_path, monkeypatch):
    """El id es sha1(area:titulo): un pendiente RESUELTO que el agente volvía a
    reportar entraba como ítem nuevo CON EL MISMO id (dos filas, misma clave).
    Ahora se reabre el mismo — y recién pasado el período de gracia, para que
    cerrar a la mañana no lo resucite el brief de la noche."""
    from datetime import datetime, timedelta, timezone
    from app.integrations import backlog as bk

    monkeypatch.setattr(bk, "_FILE", tmp_path / "backlog.json")
    t = "confirmar el número de WhatsApp antes de mandar la demo al cliente"

    item = bk.abrir("humano", t, origen="test")
    assert item and item["estado"] == "abierto"
    assert bk.resolver(item["id"], "lo confirmé por teléfono con el cliente") is True
    assert bk.abiertos("humano") == []

    # Re-reporte inmediato: cuenta la re-aparición pero NO revive.
    again = bk.abrir("humano", t, origen="test2")
    assert again["id"] == item["id"] and again["estado"] == "resuelto"
    assert again["veces"] == 2
    assert len(bk._load()["items"]) == 1                  # no duplicó

    # Pasada la gracia, el agente sí lo reabre.
    viejo = (datetime.now(timezone.utc) - timedelta(days=bk.REABRIR_TRAS_DIAS + 1)).isoformat()
    data = bk._load(); data["items"][0]["resuelto_at"] = viejo; bk._save(data)
    reab = bk.abrir("humano", t, origen="test3")
    assert reab["estado"] == "abierto" and reab["evidencia_previa"]
    assert len(bk._load()["items"]) == 1
    assert [i["id"] for i in bk.abiertos("humano")] == [item["id"]]


def test_un_cobro_real_manda_sobre_el_mrr_devengado(monkeypatch):
    """Entraba plata al negocio (un anticipo, un pago único) y el panel seguía
    mostrando el mes en rojo: la serie de ingresos sólo miraba el MRR devengado
    de clientes activos, y el libro de pagos no tocaba ninguna métrica."""
    from app.integrations import clients_store as cs, finance_store as fs

    meses = fs._recent_months(12)
    este, anterior = meses[-1], meses[-2]

    monkeypatch.setattr(fs, "_cobros_por_mes", lambda n: {este: 300.0})
    monkeypatch.setattr(fs, "expenses_by_month", lambda months=12: {este: 77.0})
    monkeypatch.setattr(fs, "expenses_by_category", lambda month=None: {})
    monkeypatch.setattr(cs, "mrr_usd", lambda: 0.0)
    monkeypatch.setattr(cs, "mrr_usd_for_month", lambda m: 0.0)

    s = fs.finance_summary()
    assert s["cobrado_mes_usd"] == 300.0
    assert s["ingresos_mes_usd"] == 300.0
    assert s["profit_month_usd"] == 223.0            # 300 cobrado − 77 de gastos
    assert s["revenue_series"][-1] == 300.0
    assert s["mrr_usd"] == 0.0                       # el devengado sigue siendo 0
    # Un mes sin cobros cargados cae al devengado, como antes del libro de pagos.
    monkeypatch.setattr(cs, "mrr_usd_for_month", lambda m: 40.0 if m == anterior else 0.0)
    assert fs.finance_summary()["revenue_series"][-2] == 40.0


def test_lo_contestado_le_llega_al_agente_aunque_este_cerrado(tmp_path, monkeypatch):
    """Contestar ahora CIERRA el pendiente. Si el bloque que va al prompt sólo
    listara los abiertos, la respuesta del dueño desaparecería y el agente
    volvería a pedir lo mismo — que es el problema que se quiso arreglar."""
    from app.integrations import backlog as bk

    monkeypatch.setattr(bk, "_FILE", tmp_path / "backlog.json")
    it = bk.abrir("humano", "decidir si publicamos los 3 videos de esta semana", origen="social")
    assert "PENDIENTES ABIERTOS" in bk.bloque("humano")

    assert bk.resolver(it["id"], "si, publicalos") is True
    assert bk.abiertos("humano") == []                 # desaparece de la pantalla

    b = bk.bloque("humano")                            # pero NO del prompt del agente
    assert "YA CONTESTADO" in b
    assert "si, publicalos" in b
    assert "decidir si publicamos los 3 videos" in b
    assert not b.startswith("\n")

    # Y con otro pendiente abierto conviven las dos secciones.
    bk.abrir("humano", "confirmar el numero de whatsapp del cliente nuevo", origen="ventas")
    b2 = bk.bloque("humano")
    assert "PENDIENTES ABIERTOS" in b2 and "YA CONTESTADO" in b2
