"""La skill de jailbreak no puede quedar al alcance de los agentes.

`godmode` viene con hermes-agent y se describe sola: "Jailbreak LLMs:
Parseltongue, GODMODE, ULTRAPLINIAN", con tag `safety-bypass`. Vive en el
volumen y no en el repo, así que una actualización del paquete la puede volver a
dejar: por eso la purga corre en cada sync y no una sola vez a mano.
"""
from app.integrations import skills_sync


def test_la_purga_borra_godmode(tmp_path):
    peligrosa = tmp_path / "red-teaming" / "godmode"
    peligrosa.mkdir(parents=True)
    (peligrosa / "SKILL.md").write_text("jailbreak", encoding="utf-8")
    buena = tmp_path / "cold-email"
    buena.mkdir()
    (buena / "SKILL.md").write_text("ok", encoding="utf-8")

    borradas = skills_sync._purgar_prohibidas(tmp_path)

    assert "godmode" in borradas
    assert not peligrosa.exists()
    assert buena.exists(), "no puede llevarse puestas las skills buenas"


def test_la_purga_encuentra_la_skill_anidada(tmp_path):
    """Está bajo red-teaming/, no en la raíz: hay que buscar recursivo."""
    hondo = tmp_path / "a" / "b" / "obliteratus"
    hondo.mkdir(parents=True)
    assert "obliteratus" in skills_sync._purgar_prohibidas(tmp_path)
    assert not hondo.exists()


def test_sin_nada_que_borrar_no_falla(tmp_path):
    assert skills_sync._purgar_prohibidas(tmp_path) == []


def test_un_directorio_inexistente_no_rompe(tmp_path):
    assert skills_sync._purgar_prohibidas(tmp_path / "no-existe") == []


def test_godmode_esta_en_la_lista():
    assert "godmode" in skills_sync.SKILLS_PROHIBIDAS
