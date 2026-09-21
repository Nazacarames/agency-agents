"""Media publicación no es una publicación (2026-09-21).

Pasó de verdad: un post salió en Facebook y Instagram lo rechazó
("Only photo or video can be accepted as media type"). El item quedó marcado
`published` y en el panel figuraba publicado, con media publicación perdida y
nadie con motivo para enterarse.

La causa era `ok = any(...)` en `social_publish.publish`: con que UNA red
aceptara, el post entero se daba por bueno. Ahora `ok` significa *salió todo lo
que se pidió*, y `parcial` + `fallaron` dicen qué falta.
"""
import pytest

from app.integrations import publish_queue as pq, social_publish as sp


def _falso(monkeypatch, ig_ok: bool, fb_ok: bool):
    monkeypatch.setattr(sp, "publish_instagram",
                        lambda img, cap="": {"ok": ig_ok, "target": "instagram",
                                             "id": "ig1" if ig_ok else "",
                                             "error": "" if ig_ok else "media type"})
    monkeypatch.setattr(sp, "publish_facebook",
                        lambda img, cap="": {"ok": fb_ok, "target": "facebook",
                                             "id": "fb1" if fb_ok else "",
                                             "error": "" if fb_ok else "boom"})


# ── lo que devuelve publish ──

def test_si_una_red_falla_NO_es_ok(monkeypatch):
    """El bug exacto: Facebook sí, Instagram no, y daba ok=True."""
    _falso(monkeypatch, ig_ok=False, fb_ok=True)
    r = sp.publish("/media/x.jpg", "hola", ["instagram", "facebook"])
    assert r["ok"] is False
    assert r["parcial"] is True
    assert r["fallaron"] == ["instagram"]
    assert r["salieron"] == ["facebook"]


def test_si_salen_todas_es_ok(monkeypatch):
    _falso(monkeypatch, ig_ok=True, fb_ok=True)
    r = sp.publish("/media/x.jpg", "hola", ["instagram", "facebook"])
    assert r["ok"] is True
    assert r["parcial"] is False
    assert r["fallaron"] == []


def test_si_no_sale_ninguna_no_es_parcial(monkeypatch):
    """`parcial` tiene que distinguirse de `falló todo`: se arreglan distinto."""
    _falso(monkeypatch, ig_ok=False, fb_ok=False)
    r = sp.publish("/media/x.jpg", "hola", ["instagram", "facebook"])
    assert r["ok"] is False
    assert r["parcial"] is False
    assert sorted(r["fallaron"]) == ["facebook", "instagram"]


def test_una_sola_red_pedida_y_sale(monkeypatch):
    _falso(monkeypatch, ig_ok=True, fb_ok=False)
    r = sp.publish("/media/x.jpg", "hola", ["instagram"])
    assert r["ok"] is True and r["parcial"] is False


# ── cómo lo guarda la cola ──

def _store(tmp_path, monkeypatch, status="pending", result=None):
    monkeypatch.setattr(pq, "_data_dir", lambda: tmp_path)
    st = {"items": [{"id": "abc", "image": "/media/x.jpg", "caption": "hola",
                     "kind": "post", "targets": ["instagram", "facebook"],
                     "status": status, "published_at": None, "result": result,
                     "error": None, "created_at": "2026-09-21T10:00:00+00:00"}]}
    pq.save_store(st)
    return st


def test_media_publicacion_no_queda_como_published(tmp_path, monkeypatch):
    _store(tmp_path, monkeypatch)
    _falso(monkeypatch, ig_ok=False, fb_ok=True)
    pq._publish_item({"id": "abc", "image": "/media/x.jpg", "caption": "hola",
                      "kind": "post", "targets": ["instagram", "facebook"]})
    it = pq.load_store()["items"][0]
    assert it["status"] == "parcial", "volvió a decir que estaba publicado"
    assert "instagram" in (it["error"] or "")
    assert it["result"]["facebook"]["ok"] is True


def test_lo_parcial_igual_ocupa_el_cupo_del_dia(tmp_path, monkeypatch):
    """Si no contara, el próximo drenaje publicaría otra pieza encima en la red
    donde SÍ salió."""
    _store(tmp_path, monkeypatch)
    _falso(monkeypatch, ig_ok=False, fb_ok=True)
    pq._publish_item({"id": "abc", "image": "/media/x.jpg", "caption": "hola",
                      "kind": "post", "targets": ["instagram", "facebook"]})
    assert pq.published_today_count() == 1


def test_lo_que_fallo_entero_no_ocupa_cupo(tmp_path, monkeypatch):
    _store(tmp_path, monkeypatch)
    _falso(monkeypatch, ig_ok=False, fb_ok=False)
    pq._publish_item({"id": "abc", "image": "/media/x.jpg", "caption": "hola",
                      "kind": "post", "targets": ["instagram", "facebook"]})
    assert pq.load_store()["items"][0]["status"] == "failed"
    assert pq.published_today_count() == 0


# ── reintentar sin duplicar ──

def test_reintentar_lo_parcial_va_SOLO_a_la_red_que_fallo(tmp_path, monkeypatch):
    """Reintentarlo entero duplicaría el posteo donde ya salió, que es peor que
    no reintentarlo."""
    _store(tmp_path, monkeypatch, status="parcial",
           result={"instagram": {"ok": False, "error": "media type"},
                   "facebook": {"ok": True, "id": "fb1"}})
    assert pq.retry_item("abc") is True
    it = pq.load_store()["items"][0]
    assert it["targets"] == ["instagram"], f"iba a duplicar en: {it['targets']}"
    assert it["status"] == "pending"
    assert it["published_at"] is None


def test_reintentar_lo_fallido_conserva_las_dos_redes(tmp_path, monkeypatch):
    _store(tmp_path, monkeypatch, status="failed")
    assert pq.retry_item("abc") is True
    it = pq.load_store()["items"][0]
    assert it["targets"] == ["instagram", "facebook"]


def test_no_se_reintenta_lo_que_ya_salio_entero(tmp_path, monkeypatch):
    _store(tmp_path, monkeypatch, status="published")
    assert pq.retry_item("abc") is False
