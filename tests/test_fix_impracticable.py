"""El fix del juez que pide pauta NO debe grabarse como leccion.

Gemini no conoce la restriccion de presupuesto cero: mira una pieza organica y
concluye que le falta distribucion paga. Si eso entra al almacen de lecciones, el
agente lo reinyecta en cada corrida y termina pidiendo pauta en el backlog `humano`
(pasaron ocho pedidos entre 2026-08-29 y 2026-09-08).
"""
from unittest.mock import patch

from app.integrations import text_judge as tj


def _gate(top_fix, avg=40):
    """Corre qa_gate con un veredicto fijo y devuelve (resultado, lecciones grabadas).

    Se parchea `record_outcome` sobre el modulo real y NO sys.modules: qa_gate hace
    `from . import memory_store`, que resuelve por atributo del paquete antes que por
    sys.modules. Parchear sys.modules anda en aislamiento y deja de andar apenas otro
    test importo memory_store primero — y entonces el test escribe lecciones DE VERDAD.
    """
    grabadas = []

    with patch.object(tj, "enabled", return_value=True), \
         patch.object(tj, "judge", return_value={"avg": avg, "top_fix": top_fix}), \
         patch.object(tj, "_anotar_score", return_value=""), \
         patch("app.integrations.memory_store.record_outcome",
               side_effect=lambda a, t: grabadas.append((a, t))):
        return tj.qa_gate("social_media", "social", "payload", hold_below=1), grabadas


def test_el_fix_que_pide_pauta_no_se_aprende():
    for fix in ("Conseguir presupuesto de pauta para distribucion",
                "Invertir en publicidad paga en Meta",
                "Boostear el post para ampliar alcance",
                "Complementar con Google Ads"):
        res, grabadas = _gate(fix)
        assert grabadas == [], f"se grabo como leccion un fix impracticable: {fix}"
        assert "no se guard" in res["line"], f"no se reporto el descarte para: {fix}"


def test_un_fix_normal_si_se_aprende():
    res, grabadas = _gate("El cierre es debil: falta una pregunta que obligue a responder")
    assert len(grabadas) == 1, "un fix accionable tiene que grabarse como leccion"
    assert "Fix aplicado a futuras corridas" in res["line"]


def test_el_score_no_se_toca():
    """Se descarta la leccion, NO el freno: una pieza floja sigue frenada."""
    res, _ = _gate("Conseguir presupuesto de pauta", avg=12)
    sin_fix, _ = _gate("El texto no se entiende", avg=12)
    assert res["avg"] == sin_fix["avg"] == 12
    # sin hold_below: el umbral real (HOLD_BELOW=50) tiene que frenar igual.
    # record_outcome va parcheado aunque este caso no deberia grabar: un test NUNCA
    # escribe en el store de verdad (ya paso: dejo 2 lecciones inventadas).
    with patch.object(tj, "enabled", return_value=True), \
         patch.object(tj, "judge", return_value={"avg": 12, "top_fix": "pauta"}), \
         patch.object(tj, "_anotar_score", return_value=""), \
         patch("app.integrations.memory_store.record_outcome") as rec:
        frenado = tj.qa_gate("social_media", "social", "x")
    assert frenado["publish_ok"] is False, "el freno por score bajo tiene que seguir operando"
    rec.assert_not_called()


if __name__ == "__main__":
    test_el_fix_que_pide_pauta_no_se_aprende()
    test_un_fix_normal_si_se_aprende()
    test_el_score_no_se_toca()
    print("ok")
