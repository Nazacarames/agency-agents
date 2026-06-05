"""
Tests del cliente MiniMax (mockeados — sin red).
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def test_minimax_requires_api_key():
    from app.config import Settings
    from app.clients.minimax import MiniMaxAuthError, MiniMaxClient

    s = Settings(minimax_api_key="")
    with pytest.raises(MiniMaxAuthError, match="MINIMAX_API_KEY"):
        MiniMaxClient(s)


def test_minimax_complete_success():
    from app.config import Settings
    from app.clients.minimax import MiniMaxClient

    s = Settings(
        minimax_api_key="sk-test-123",
        minimax_model_primary="MiniMax-M3",
        minimax_model_fallbacks="MiniMax-M2.5,MiniMax-M2.5-highspeed",
    )
    client = MiniMaxClient(s)

    # Simular respuesta de la API estilo Anthropic Messages
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "model": "MiniMax-M3",
        "content": [{"type": "text", "text": "Hola, soy un agente."}],
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 100, "output_tokens": 50},
    }

    with patch.object(client._client, "post", return_value=mock_resp):
        resp = client.complete(
            system="Sos un agente",
            messages=[{"role": "user", "content": "decí hola"}],
        )
        assert resp.text == "Hola, soy un agente."
        assert resp.model == "MiniMax-M3"
        assert resp.input_tokens == 100
        assert resp.output_tokens == 50


def test_minimax_fallback_on_429():
    """Si el primary da 429, debe probar el siguiente modelo en la cadena."""
    from app.config import Settings
    from app.clients.minimax import MiniMaxClient

    s = Settings(
        minimax_api_key="sk-test-123",
        minimax_model_primary="MiniMax-M3",
        minimax_model_fallbacks="MiniMax-M2.5",
    )
    client = MiniMaxClient(s)

    # Primer intento: 429. Segundo: 200.
    rate_resp = MagicMock()
    rate_resp.status_code = 429
    rate_resp.text = "rate limited"

    ok_resp = MagicMock()
    ok_resp.status_code = 200
    ok_resp.json.return_value = {
        "model": "MiniMax-M2.5",
        "content": [{"type": "text", "text": "ok fallback"}],
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }

    with patch.object(client._client, "post", side_effect=[rate_resp, ok_resp]) as mock_post:
        resp = client.complete(
            system="test",
            messages=[{"role": "user", "content": "hola"}],
        )
        assert resp.text == "ok fallback"
        assert resp.model == "MiniMax-M2.5"
        assert mock_post.call_count == 2


def test_minimax_auth_error_no_fallback():
    """Auth errors (401/403) no deben triggerear fallback — se propagan."""
    from app.config import Settings
    from app.clients.minimax import MiniMaxAuthError, MiniMaxClient

    s = Settings(
        minimax_api_key="sk-bad",
        minimax_model_primary="MiniMax-M3",
        minimax_model_fallbacks="MiniMax-M2.5",
    )
    client = MiniMaxClient(s)

    auth_resp = MagicMock()
    auth_resp.status_code = 401
    auth_resp.text = "unauthorized"

    with patch.object(client._client, "post", return_value=auth_resp):
        with pytest.raises(MiniMaxAuthError):
            client.complete(
                system="test",
                messages=[{"role": "user", "content": "hola"}],
            )
