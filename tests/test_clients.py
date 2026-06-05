"""
Tests del cliente Discord (mockeados — sin red).
"""
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def test_discord_webhook_requires_url():
    from app.config import Settings
    from app.clients.discord import DiscordError, DiscordWebhook

    s = Settings(discord_webhook_url="")
    with pytest.raises(DiscordError, match="DISCORD_WEBHOOK_URL"):
        DiscordWebhook(s)


def test_discord_send_success():
    from app.config import Settings
    from app.clients.discord import DiscordEmbed, DiscordWebhook

    s = Settings(discord_webhook_url="https://discord.com/api/webhooks/123/abc")
    client = DiscordWebhook(s)

    mock_resp = MagicMock()
    mock_resp.status_code = 204
    mock_resp.content = b""
    mock_resp.json.return_value = {}

    with patch.object(client._client, "post", return_value=mock_resp) as mock_post:
        client.send("hola", username="tester")

        # Verificar que se llamó con el payload correcto
        call_args = mock_post.call_args
        url = call_args.args[0]
        body = call_args.kwargs["json"]
        assert "webhooks/123/abc" in url
        assert body["content"] == "hola"
        assert body["username"] == "tester"


def test_discord_send_embed():
    from app.config import Settings
    from app.clients.discord import DiscordEmbed, DiscordWebhook

    s = Settings(discord_webhook_url="https://discord.com/api/webhooks/123/abc")
    client = DiscordWebhook(s)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = b'{"id": "123"}'
    mock_resp.json.return_value = {"id": "123"}

    with patch.object(client._client, "post", return_value=mock_resp):
        embed = DiscordEmbed(
            title="Test",
            description="Contenido",
            color=0xFF0000,
            footer="footer text",
        )
        result = client.send("", embed=embed)
        assert result["id"] == "123"


def test_discord_truncates_long_content():
    from app.config import Settings
    from app.clients.discord import DiscordWebhook

    s = Settings(discord_webhook_url="https://discord.com/api/webhooks/123/abc")
    client = DiscordWebhook(s)

    mock_resp = MagicMock()
    mock_resp.status_code = 204
    mock_resp.content = b""

    with patch.object(client._client, "post", return_value=mock_resp) as mock_post:
        long_text = "x" * 5000
        client.send(long_text)
        body = mock_post.call_args.kwargs["json"]
        # Discord limit es 2000 chars
        assert len(body["content"]) <= 2000
