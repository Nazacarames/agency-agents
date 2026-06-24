"""
image_gen — generación de imágenes para el contenido.

Pipeline: MiniMax (`/v1/image_generation`, model `image-01`) genera el FONDO
(ilustración), y si se pide un texto, lo COMPONEMOS encima con Pillow usando una
fuente real (Anton) → texto exacto y legible. Esto es clave porque MiniMax
deforma el texto ("24/7" → "2417"): el modelo pone la imagen, el código pone las
letras.

La imagen final se guarda en el volume (`data/images/`) y se devuelve una URL
local estable (`/media/<archivo>.png`) servida por la app.

Best-effort: si algo falla devuelve [] y el contenido sale sin imagen.
"""
from __future__ import annotations

import io
import textwrap
import uuid
from pathlib import Path
from typing import List, Optional

import httpx

from ..config import get_settings
from ..log import get_logger

log = get_logger("image_gen")

_FONTS = Path(__file__).resolve().parent.parent / "assets" / "fonts"
_HEADLINE_FONT = _FONTS / "Anton-Regular.ttf"
_BODY_FONT = _FONTS / "DMSans.ttf"

# Paleta Automiq
_NAVY = (15, 27, 51)
_BLUE = (37, 99, 235)
_WHITE = (255, 255, 255)


def _images_dir() -> Path:
    d = Path(__file__).resolve().parent.parent.parent / "data" / "images"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _endpoint() -> str:
    base = (get_settings().minimax_base_url or "https://api.minimax.io/anthropic")
    root = base.split("/anthropic")[0].rstrip("/")
    return f"{root}/v1/image_generation"


def enabled() -> bool:
    s = get_settings()
    return bool(s.minimax_api_key and getattr(s, "images_enabled", True))


def generate_image(prompt: str, aspect_ratio: str = "1:1", n: int = 1,
                   text: Optional[str] = None, subtitle: Optional[str] = None) -> List[str]:
    """Genera n imágenes (con texto compuesto si se pide) y devuelve URLs locales."""
    s = get_settings()
    if not enabled() or not (prompt or "").strip():
        return []
    full_prompt = prompt.strip()
    if text:
        # que MiniMax NO escriba texto (lo ponemos nosotros) y deje espacio limpio
        full_prompt += (". Clean simple background with empty space at the bottom for a text "
                        "banner. Do NOT render any text, letters or words in the image.")
    body = {
        "model": getattr(s, "image_model", "image-01"),
        "prompt": full_prompt[:1500],
        "aspect_ratio": aspect_ratio or "1:1",
        "response_format": "url",
        "n": max(1, min(n, 4)),
    }
    try:
        with httpx.Client(timeout=180) as c:
            r = c.post(_endpoint(), json=body,
                       headers={"Authorization": f"Bearer {s.minimax_api_key}"})
            r.raise_for_status()
            data = r.json()
            br = data.get("base_resp") or {}
            if br.get("status_code") not in (0, None):
                log.warning("image_gen_api_error", status=br.get("status_code"), msg=br.get("status_msg"))
                return []
            urls = (data.get("data") or {}).get("image_urls") or []
            out: List[str] = []
            for u in urls:
                try:
                    raw = c.get(u, timeout=90).content
                except Exception as e:
                    log.warning("image_download_failed", error=str(e)[:150]); continue
                if text:
                    raw = _overlay_text(raw, text, subtitle) or raw
                fname = f"{uuid.uuid4().hex}.png"
                (_images_dir() / fname).write_bytes(raw)
                local_url = f"/media/{fname}"
                out.append(local_url)
                _notify_discord(local_url, text, subtitle)
        log.info("image_gen_ok", generated=len(out), with_text=bool(text))
        return out
    except Exception as e:
        log.warning("image_gen_failed", error=str(e)[:200])
        return []


def _notify_discord(local_url: str, text: Optional[str], subtitle: Optional[str]) -> None:
    """Espeja la imagen recién generada a Discord (best-effort, no rompe nada)."""
    s = get_settings()
    if not getattr(s, "discord_images_enabled", True) or not s.discord_configured:
        return
    try:
        from .social_publish import absolute_url
        from ..clients.discord import DiscordWebhook, DiscordEmbed
        url = absolute_url(local_url)
        if not url.startswith("http"):
            return  # sin URL pública Discord no puede mostrarla
        title = (text or "Imagen generada")[:256]
        desc = subtitle or ""
        dw = DiscordWebhook(s)
        dw.send("", embed=DiscordEmbed(title=f"🎨 {title}", description=desc,
                                       image_url=url, color=0x2563EB),
                url=s.discord_images_webhook_url or None)
        dw.close()
        log.info("image_discord_sent", url=url)
    except Exception as e:
        log.warning("image_discord_failed", error=str(e)[:200])


def _fit_font(draw, text: str, font_path: Path, max_w: int, max_h: int,
              start: int = 120, min_size: int = 28):
    """Devuelve (font, líneas) con el tamaño más grande que entra en max_w x max_h."""
    from PIL import ImageFont
    size = start
    while size >= min_size:
        font = ImageFont.truetype(str(font_path), size)
        # caracteres por línea aprox según ancho
        avg = max(draw.textlength("M", font=font), 1)
        per_line = max(6, int(max_w / avg))
        lines = textwrap.wrap(text, width=per_line) or [text]
        widest = max(draw.textlength(ln, font=font) for ln in lines)
        line_h = size * 1.12
        total_h = line_h * len(lines)
        if widest <= max_w and total_h <= max_h:
            return font, lines, line_h
        size -= 6
    font = ImageFont.truetype(str(font_path), min_size)
    return font, textwrap.wrap(text, width=max(6, int(max_w / max(draw.textlength('M', font=font), 1)))) or [text], min_size * 1.12


def _overlay_text(img_bytes: bytes, text: str, subtitle: Optional[str] = None) -> Optional[bytes]:
    """Compone un cartel (banda inferior translúcida + titular en Anton) sobre la imagen."""
    try:
        from PIL import Image, ImageDraw
        img = Image.open(io.BytesIO(img_bytes)).convert("RGBA")
        W, H = img.size
        draw = ImageDraw.Draw(img, "RGBA")

        pad = int(W * 0.06)
        max_w = W - 2 * pad
        band_h = int(H * (0.42 if subtitle else 0.34))

        # banda inferior con degradé navy → transparente (legibilidad)
        band = Image.new("RGBA", (W, band_h), (0, 0, 0, 0))
        bd = ImageDraw.Draw(band)
        for y in range(band_h):
            a = int(225 * (y / band_h) ** 0.8)
            bd.line([(0, y), (W, y)], fill=(_NAVY[0], _NAVY[1], _NAVY[2], a))
        img.alpha_composite(band, (0, H - band_h))

        # titular
        head = (text or "").strip().upper()
        font, lines, line_h = _fit_font(draw, head, _HEADLINE_FONT, max_w,
                                        int(band_h * (0.55 if subtitle else 0.72)))
        total_h = line_h * len(lines)
        sub_h = int(H * 0.05) if subtitle else 0
        y = H - band_h + (band_h - total_h - sub_h) / 2 + (band_h * 0.08)
        for ln in lines:
            w = draw.textlength(ln, font=font)
            x = (W - w) / 2
            draw.text((x + 2, y + 2), ln, font=font, fill=(0, 0, 0, 110))   # sombra
            draw.text((x, y), ln, font=font, fill=_WHITE)
            y += line_h

        # subtítulo (acento azul)
        if subtitle:
            from PIL import ImageFont
            sf, sl, slh = _fit_font(draw, subtitle.strip(), _BODY_FONT, max_w, sub_h * 1.6, start=46, min_size=20)
            for ln in sl[:2]:
                w = draw.textlength(ln, font=sf)
                draw.text(((W - w) / 2, y), ln, font=sf, fill=(_BLUE[0]+60, 150, 255, 255))
                y += slh

        # franja de marca arriba
        draw.rectangle([0, 0, W, int(H * 0.012)], fill=(_BLUE[0], _BLUE[1], _BLUE[2], 255))

        out = io.BytesIO()
        img.convert("RGB").save(out, format="PNG")
        return out.getvalue()
    except Exception as e:
        log.warning("overlay_text_failed", error=str(e)[:200])
        return None
