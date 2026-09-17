"""DeepSeek salió, GLM 5.3 entró (2026-09-17).

NVIDIA dio de baja el modelo: la API devuelve **410 Gone — "the model
'deepseek-ai/deepseek-v4-pro-0813' has reached its end of life on 2026-09-14"**.
Diez agentes lo tenían configurado y fallaban sin motivo aparente.
"""
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "app"


def _py():
    for f in APP.rglob("*.py"):
        yield f, f.read_text(encoding="utf-8", errors="ignore")


def test_ningun_agente_pide_ya_deepseek():
    culpables = []
    for f, t in _py():
        for i, linea in enumerate(t.splitlines(), 1):
            l = linea.strip()
            if "deepseek" not in l.lower() or l.startswith("#"):
                continue
            # las menciones que quedan son historia en docstrings, no código
            if 'llm_provider = "deepseek"' in l or 'complete_with_provider("deepseek"' in l \
                    or "deepseek_model" in l:
                culpables.append(f"{f.name}:{i}")
    assert not culpables, culpables


def test_el_setting_de_deepseek_no_existe_mas():
    """Lo peor de dejarlo: `watchdog` leía `settings.deepseek_model` para chequear
    el catálogo. Con el setting borrado eso reventaba el watchdog entero."""
    from app.config import get_settings
    assert not hasattr(get_settings(), "deepseek_model")


def test_el_watchdog_sigue_chequeando_los_modelos_vivos():
    t = (APP / "integrations/watchdog.py").read_text(encoding="utf-8")
    assert "settings.deepseek_model" not in t
    assert "settings.glm_model" in t
    assert "settings.kimi_model" in t


# ── GLM 5.3 ──

def test_glm_apunta_al_modelo_nuevo():
    from app.config import get_settings
    assert get_settings().glm_model == "z-ai/glm-5.3"


def test_glm_va_con_esfuerzo_de_razonamiento_bajo():
    """Medido el 2026-09-17 con la misma pregunta: con max_tokens=150 devolvía
    VACÍO (el pensamiento se comía el presupuesto), con max_tokens=2000 tardaba
    89 s, y con reasoning_effort=low contestó bien en 2,9 s."""
    from app.clients.nvidia import _PROVIDER_MODEL
    _, extra = _PROVIDER_MODEL["glm"]
    assert extra.get("reasoning_effort") == "low"


def test_el_truco_de_deepseek_no_quedo_pegado_a_glm():
    """`chat_template_kwargs {"thinking": False}` apagaba el razonamiento de
    DeepSeek. Con GLM 5.3 se probó y devuelve VACÍO igual: no le aplica."""
    from app.clients.nvidia import _PROVIDER_MODEL
    _, extra = _PROVIDER_MODEL["glm"]
    assert "chat_template_kwargs" not in extra


def test_un_provider_desconocido_cae_a_glm_CON_su_configuracion():
    """El default era `("glm_model", {})` — sin el extra. Un provider mal escrito
    caía a GLM pero sin `reasoning_effort` y devolvía vacío, que es la falla más
    difícil de diagnosticar: responde 200 y no dice nada."""
    from app.clients.nvidia import _PROVIDER_MODEL, provider_model
    from app.config import get_settings
    assert provider_model("no-existe", get_settings()) == "z-ai/glm-5.3"
    t = (APP / "clients/nvidia.py").read_text(encoding="utf-8")
    assert '_PROVIDER_MODEL.get(provider, ("", {}))' not in t
    assert '_PROVIDER_MODEL.get(provider, ("glm_model", {}))' not in t


def test_los_agentes_que_usaban_deepseek_ahora_usan_glm():
    """Eran diez: chief_of_staff, creative_strategist, customer_success,
    data_analyst, delivery_pm, finance_officer, growth_hacker, media_auditor,
    más meeting_prep y outbound por llamada directa."""
    con_glm = [f.stem for f, t in _py() if 'llm_provider = "glm"' in t]
    for esperado in ("chief_of_staff", "data_analyst", "finance_officer",
                     "growth_hacker", "media_auditor", "creative_strategist"):
        assert esperado in con_glm, f"{esperado} se quedó sin backend"
