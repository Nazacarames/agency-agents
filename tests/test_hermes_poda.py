"""La poda de state.db: Hermes sólo poda sesiones terminadas y las headless nunca
se cierran (2026-10-06: 1.592 de 1.592 con ended_at vacío)."""
import sqlite3
import time


def test_cierra_solo_las_sesiones_viejas_y_abiertas(tmp_path, monkeypatch):
    from app.clients import hermes
    monkeypatch.setattr(hermes, "_HERMES_HOME", tmp_path)
    con = sqlite3.connect(tmp_path / "state.db")
    con.execute("CREATE TABLE sessions (id TEXT, started_at REAL, ended_at REAL, end_reason TEXT)")
    ahora = time.time()
    con.executemany("INSERT INTO sessions VALUES (?,?,?,?)", [
        ("vieja_abierta", ahora - 90 * 86400, None, None),
        ("vieja_cerrada", ahora - 90 * 86400, ahora - 89 * 86400, "agent_close"),
        ("nueva_abierta", ahora - 5 * 86400, None, None),
    ])
    con.commit()
    con.close()

    assert hermes.cerrar_sesiones_viejas(60) == 1
    con = sqlite3.connect(tmp_path / "state.db")
    filas = dict(con.execute("SELECT id, end_reason FROM sessions").fetchall())
    assert filas == {"vieja_abierta": "headless_sin_cerrar", "vieja_cerrada": "agent_close",
                     "nueva_abierta": None}


def test_sin_base_no_falla(tmp_path, monkeypatch):
    from app.clients import hermes
    monkeypatch.setattr(hermes, "_HERMES_HOME", tmp_path)
    assert hermes.cerrar_sesiones_viejas(60) == 0
