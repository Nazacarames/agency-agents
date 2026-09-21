"""El auto-archivado no puede matar una negociación abierta (2026-09-21).

Pasó: Córdoba Automatizaciones apareció marcado `descartado`. Era el cliente MÁS
avanzado que teníamos —prueba corriendo hasta el 7/10, propuesta enviada tres
días antes— y el job de archivado lo dio por frío.

El defecto es el proxy. `auto_archive` mide "frío" por `updated_at`, que sólo
cambia cuando alguien EDITA LA FICHA A MANO. Nadie edita fichas. Mientras tanto
ese lead tenía 165 conversaciones ese mes en su propio CRM: el negocio estaba
vivo y el panel no se enteraba.

Un trato descartado deja de seguirse: no lo escala el chief_of_staff, no aparece
en el pipeline y nadie lo vuelve a mirar. Es la peor forma de perder una venta,
porque no falla nada visible.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.integrations import clients_store as cs


@pytest.fixture
def store(tmp_path, monkeypatch):
    """clients_store aislado, sin tocar la base de la agencia."""
    datos = {"clients": []}

    monkeypatch.setattr(cs, "list_clients", lambda: list(datos["clients"]))

    def _update(cid, campos):
        for c in datos["clients"]:
            if c["id"] == cid:
                c.update(campos)
                return c
        return None

    monkeypatch.setattr(cs, "update_client", _update)
    return datos


def _viejo(dias=30):
    return (datetime.now(timezone.utc) - timedelta(days=dias)).isoformat()


def _cliente(**kw):
    base = {"id": "x1", "name": "Prueba", "stage": "oferta", "status": "onboarding",
            "monthly_fee": 0.0, "updated_at": _viejo()}
    base.update(kw)
    return base


def test_una_negociacion_abierta_NO_se_archiva(store):
    """El caso exacto de Córdoba Automatizaciones."""
    store["clients"] = [_cliente(id="cba", name="Cordoba Automatizaciones",
                                 stage="negociación", status="onboarding",
                                 monthly_fee=300.0)]
    r = cs.auto_archive(days=10)
    assert r["archived"] == 0, f"archivó: {r['names']}"
    assert store["clients"][0]["stage"] == "negociación"


def test_una_reunion_agendada_tampoco(store):
    store["clients"] = [_cliente(stage="reunión")]
    assert cs.auto_archive(days=10)["archived"] == 0


def test_un_prospecto_frio_SI_se_archiva(store):
    """El job tiene que seguir sirviendo para lo que se hizo: limpiar la pila de
    prospectos en `oferta` que nunca contestaron."""
    store["clients"] = [_cliente(id="frio", name="Prospecto Frío", stage="oferta")]
    r = cs.auto_archive(days=10)
    assert r["archived"] == 1
    assert store["clients"][0]["stage"] == "descartado"


def test_un_prospecto_reciente_no_se_toca(store):
    store["clients"] = [_cliente(stage="oferta", updated_at=_viejo(2))]
    assert cs.auto_archive(days=10)["archived"] == 0


def test_el_que_ya_factura_sigue_protegido(store):
    """La protección que ya existía no se pierde."""
    store["clients"] = [_cliente(stage="oferta", status="activo", monthly_fee=500.0)]
    assert cs.auto_archive(days=10)["archived"] == 0


def test_las_etapas_protegidas_existen_de_verdad():
    """Si alguien renombra una etapa, este test avisa antes de que el job vuelva
    a archivar negociaciones por no encontrar el nombre."""
    for etapa in cs.NUNCA_ARCHIVAR:
        assert etapa in cs.STAGES, f"«{etapa}» no está en STAGES"
    assert "oferta" not in cs.NUNCA_ARCHIVAR, "oferta tiene que seguir archivándose"
