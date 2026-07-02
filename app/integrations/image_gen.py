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
    # SIEMPRE prohibir texto: MiniMax dibuja letras/números deformes e ilegibles.
    # El texto real lo compone Pillow por encima. Negativo fuerte y repetido.
    full_prompt += (". IMPORTANT: photographic/illustrated scene only, absolutely NO text, "
                    "no letters, no words, no numbers, no captions, no watermark, no logos, "
                    "no UI, no chat bubbles, no screenshots, no charts. Pure imagery.")
    if text:
        # además dejar espacio limpio abajo para la banda de texto compuesta
        full_prompt += " Leave clean empty space at the bottom for a text banner."
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
                else:
                    # Instagram SÓLO acepta JPEG (PNG → "Only photo or video can be
                    # accepted as media type"). Normalizamos todo a JPEG.
                    raw = _to_jpeg(raw) or raw
                fname = f"{uuid.uuid4().hex}.jpg"
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


def _grad_band(img, W: int, band_h: int, top: bool = False) -> None:
    """Degradé navy → transparente para legibilidad (abajo, o arriba si top)."""
    from PIL import Image, ImageDraw
    band = Image.new("RGBA", (W, band_h), (0, 0, 0, 0))
    bd = ImageDraw.Draw(band)
    for y in range(band_h):
        t = (1 - y / band_h) if top else (y / band_h)
        a = int(225 * t ** 0.8)
        bd.line([(0, y), (W, y)], fill=(_NAVY[0], _NAVY[1], _NAVY[2], a))
    img.alpha_composite(band, (0, 0 if top else img.size[1] - band_h))


def _draw_lines(draw, lines, font, line_h, y, W, pad, align="center", color=None):
    """Dibuja líneas con sombra. Devuelve la y final."""
    for ln in lines:
        w = draw.textlength(ln, font=font)
        x = pad if align == "left" else (W - w) / 2
        draw.text((x + 2, y + 2), ln, font=font, fill=(0, 0, 0, 110))
        draw.text((x, y), ln, font=font, fill=color or _WHITE)
        y += line_h
    return y


def _overlay_text(img_bytes: bytes, text: str, subtitle: Optional[str] = None) -> Optional[bytes]:
    """Compone el titular sobre la imagen con 1 de 4 layouts (elegido por hash del
    texto → determinístico pero VARIADO entre piezas, para que el feed no sea
    siempre la misma banda inferior centrada): banda | esquina | tarjeta | franja."""
    try:
        import zlib
        from PIL import Image, ImageDraw
        img = Image.open(io.BytesIO(img_bytes)).convert("RGBA")
        W, H = img.size
        draw = ImageDraw.Draw(img, "RGBA")

        pad = int(W * 0.06)
        head = (text or "").strip().upper()
        variant = ("banda", "esquina", "tarjeta", "franja")[zlib.crc32(head.encode("utf-8")) % 4]
        sub_color = (_BLUE[0] + 60, 150, 255, 255)

        if variant == "banda":
            # clásico: banda inferior, titular centrado
            max_w = W - 2 * pad
            band_h = int(H * (0.42 if subtitle else 0.34))
            _grad_band(img, W, band_h)
            font, lines, line_h = _fit_font(draw, head, _HEADLINE_FONT, max_w,
                                            int(band_h * (0.55 if subtitle else 0.72)))
            sub_h = int(H * 0.05) if subtitle else 0
            y = H - band_h + (band_h - line_h * len(lines) - sub_h) / 2 + (band_h * 0.08)
            y = _draw_lines(draw, lines, font, line_h, y, W, pad)
            if subtitle:
                sf, sl, slh = _fit_font(draw, subtitle.strip(), _BODY_FONT, max_w,
                                        sub_h * 1.6, start=46, min_size=20)
                _draw_lines(draw, sl[:2], sf, slh, y, W, pad, color=sub_color)

        elif variant == "esquina":
            # titular alineado abajo-izquierda con barra vertical azul
            max_w = int(W * 0.78)
            band_h = int(H * (0.46 if subtitle else 0.38))
            _grad_band(img, W, band_h)
            font, lines, line_h = _fit_font(draw, head, _HEADLINE_FONT, max_w - pad,
                                            int(band_h * 0.55), start=100)
            sub_h = int(H * 0.05) if subtitle else 0
            total = line_h * len(lines) + sub_h
            y0 = H - pad - total
            draw.rectangle([pad - int(W * 0.02), y0, pad - int(W * 0.008), y0 + total],
                           fill=(_BLUE[0], _BLUE[1], _BLUE[2], 255))
            y = _draw_lines(draw, lines, font, line_h, y0, W, pad + int(W * 0.01), align="left")
            if subtitle:
                sf, sl, slh = _fit_font(draw, subtitle.strip(), _BODY_FONT, max_w - pad,
                                        sub_h * 1.5, start=42, min_size=20)
                _draw_lines(draw, sl[:2], sf, slh, y, W, pad + int(W * 0.01),
                            align="left", color=sub_color)

        elif variant == "tarjeta":
            # tarjeta navy translúcida centrada con borde azul (estilo quote)
            card_w = int(W * 0.86)
            font, lines, line_h = _fit_font(draw, head, _HEADLINE_FONT,
                                            card_w - 2 * pad, int(H * 0.30), start=100)
            sub_h = int(H * 0.05) if subtitle else 0
            card_h = int(line_h * len(lines) + sub_h + pad * 1.8)
            x0, y0 = (W - card_w) // 2, (H - card_h) // 2
            card = Image.new("RGBA", (card_w, card_h), (_NAVY[0], _NAVY[1], _NAVY[2], 205))
            img.alpha_composite(card, (x0, y0))
            draw.rectangle([x0, y0, x0 + card_w, y0 + card_h], outline=(_BLUE[0], _BLUE[1], _BLUE[2], 255), width=3)
            y = y0 + pad * 0.9
            y = _draw_lines(draw, lines, font, line_h, y, W, pad)
            if subtitle:
                sf, sl, slh = _fit_font(draw, subtitle.strip(), _BODY_FONT, card_w - 2 * pad,
                                        sub_h * 1.5, start=42, min_size=20)
                _draw_lines(draw, sl[:2], sf, slh, y, W, pad, color=sub_color)

        else:  # franja: titular ARRIBA a la izquierda con subrayado azul
            max_w = W - 2 * pad
            band_h = int(H * (0.42 if subtitle else 0.34))
            _grad_band(img, W, band_h, top=True)
            font, lines, line_h = _fit_font(draw, head, _HEADLINE_FONT, max_w,
                                            int(band_h * 0.55), start=100)
            y = _draw_lines(draw, lines, font, line_h, pad * 1.1, W, pad, align="left")
            underline_w = min(int(draw.textlength(lines[-1], font=font)), max_w)
            draw.rectangle([pad, y + 6, pad + max(underline_w, int(W * 0.2)), y + 6 + int(H * 0.008)],
                           fill=(_BLUE[0], _BLUE[1], _BLUE[2], 255))
            if subtitle:
                sf, sl, slh = _fit_font(draw, subtitle.strip(), _BODY_FONT, max_w,
                                        int(H * 0.08), start=42, min_size=20)
                _draw_lines(draw, sl[:2], sf, slh, y + int(H * 0.03), W, pad,
                            align="left", color=sub_color)

        # franja de marca arriba (salvo layout franja, que ya tiene peso arriba)
        if variant != "franja":
            draw.rectangle([0, 0, W, int(H * 0.012)], fill=(_BLUE[0], _BLUE[1], _BLUE[2], 255))

        out = io.BytesIO()
        # JPEG: Instagram no acepta PNG en su API de publicación.
        img.convert("RGB").save(out, format="JPEG", quality=90)
        return out.getvalue()
    except Exception as e:
        log.warning("overlay_text_failed", error=str(e)[:200])
        return None


def _to_jpeg(img_bytes: bytes) -> Optional[bytes]:
    """Convierte cualquier imagen a JPEG (RGB). IG sólo acepta JPEG."""
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
        out = io.BytesIO()
        img.save(out, format="JPEG", quality=90)
        return out.getvalue()
    except Exception as e:
        log.warning("to_jpeg_failed", error=str(e)[:200])
        return None
