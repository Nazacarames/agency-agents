"""
Tools de Hermes del pack `automiq`.

Estas tools se registran en Hermes al arrancar y están disponibles para
todos los agentes del pack. Cubren las necesidades concretas de Automiq:
- web_search: búsqueda web (Serper si hay key, DuckDuckGo fallback)
- scrape_url: HTTP scrape de una URL
- validate_site: extrae email + teléfono con prefijo +54
- notify_discord: manda un embed a Discord

Hermes las descubre si viven en `~/.hermes/tools/` o si el launcher las
registra programáticamente.
"""
from .web_search import web_search
from .scrape_url import scrape_url
from .validate_site import validate_site
from .notify_discord import notify_discord

ALL_TOOLS = {
    "web_search": web_search,
    "scrape_url": scrape_url,
    "validate_site": validate_site,
    "notify_discord": notify_discord,
}

__all__ = ["ALL_TOOLS", "web_search", "scrape_url", "validate_site", "notify_discord"]
