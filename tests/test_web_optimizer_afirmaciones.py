"""El web_optimizer no sube previews con prueba social inventada (2026-10-06:
2 de 5 previews traían clientes de fantasía y porcentajes de resultados)."""
from app.agents.web_optimizer import afirmaciones_nuevas

BASE = {"src/pages/index.astro": ["<h1>Agentes de IA</h1>", "<p>Hola</p>"]}


def _con(*nuevas):
    return {"src/pages/index.astro": BASE["src/pages/index.astro"] + list(nuevas)}


def test_frena_resultados_y_clientes_inventados():
    for linea in ('<span>+<span class="count" data-to="23">23</span>% en cierres</span>',
                  '<b>+47 empresas</b> atendidas en LATAM',
                  '<p>Los nombres son de fantasía</p>',
                  '<li>recupera 20-40% más que el apriete</li>',
                  '<h2>Quiénes nos eligen</h2>'):
        assert afirmaciones_nuevas(BASE, _con(linea)), linea


def test_deja_pasar_lo_que_describe_al_agente():
    for linea in ('<span>Responde en menos de 2 min, a cualquier hora</span>',
                  '<p>Primer agente en 2 a 4 semanas, del orden de USD 5.000</p>',
                  '.bar { width: 50%; height: calc(var(--h) * 1%); }'):
        assert not afirmaciones_nuevas(BASE, _con(linea)), linea


def test_solo_mira_lo_agregado():
    """Lo que ya estaba publicado no bloquea: la decisión fue de una persona."""
    ya = {"src/pages/index.astro": ["<p>+30% de recuperación</p>"]}
    assert not afirmaciones_nuevas(ya, ya)
