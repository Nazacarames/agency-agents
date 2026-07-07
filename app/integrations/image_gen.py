"""
image_gen — generación de imágenes para el contenido.

Pipeline: un MODELO de imagen genera el FONDO (ilustración/foto), y si se pide un
texto, lo COMPONEMOS encima con Pillow usando una fuente real (Anton) → texto
exacto y legible (el modelo pone la imagen, el código pone las letras; los modelos
deforman "24/7" → "2417").

Provider primario: **Google Imagen 4 vía Vertex AI** (misma credencial que Veo,
calidad muy superior a MiniMax). Fallback automático a **MiniMax image-01** si
Vertex no está configurado o falla. Se controla con `image_provider` en config.

La imagen final se guarda en el volume (`data/images/`) y se devuelve una URL
local estable (`/media/<archivo>.jpg`) servida por la app.

Best-effort: si algo falla devuelve [] y el contenido sale sin imagen.
"""
from __future__ import annotations

import io
import random
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

# Rotación de PLANO (aprendido mirando Tiendanube/Shopify/MercadoLibre 2026-07-05:
# rotan el encuadre; nosotros repetíamos "persona centrada" → feed monótono). Se
# elige uno al azar por imagen → mismo sujeto/escena, encuadre distinto = variedad.
# Sin pantallas/UI legibles (los modelos las deforman; el chat lo compone Pillow aparte).
_SHOTS = [
    "Wide establishing shot: the person small within the frame, the real workspace filling most of it.",
    "Tight macro close-up of the hands at work (handling product, packing a box, using tools), shallow depth of field.",
    "Candid over-the-shoulder from behind, the person facing their work, the room deep and in context.",
    "Close-up of the face mid-action, warm interior light mixed with cool window light, shallow depth of field.",
    "Low-angle three-quarter shot in the real location, cinematic warm-and-cool lighting, authentic cluttered background.",
    "Medium profile shot at their workbench or counter, natural side light, real depth behind them.",
]


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


def _nano_banana(prompt: str, aspect_ratio: str, n: int) -> List[bytes]:
    """Genera con Nano Banana Pro (Gemini 3 Pro Image) vía Vertex — muy superior a
    Imagen 4 en fidelidad al prompt (mantiene la escena/acción, no se va a estudio).
    Reusa la auth de service account de veo_video (location 'global')."""
    import base64
    from . import veo_video
    s = get_settings()
    if not s.google_service_account_json:
        return []
    token = veo_video._token()
    project = veo_video._project()
    model = getattr(s, "nano_image_model", "gemini-3-pro-image")
    url = (f"https://aiplatform.googleapis.com/v1/projects/{project}"
           f"/locations/global/publishers/google/models/{model}:generateContent")
    body = {
        "contents": [{"role": "user", "parts": [{"text": prompt[:2000]}]}],
        "generationConfig": {"responseModalities": ["TEXT", "IMAGE"],
                             "imageConfig": {"aspectRatio": aspect_ratio or "1:1"}},
    }
    out: List[bytes] = []
    with httpx.Client(timeout=180) as c:
        for _ in range(max(1, min(n, 4))):
            r = c.post(url, json=body, headers={"Authorization": f"Bearer {token}"})
            r.raise_for_status()
            parts = (((r.json().get("candidates") or [{}])[0]).get("content", {}) or {}).get("parts", [])
            for p in parts:
                if "inlineData" in p:
                    out.append(base64.b64decode(p["inlineData"]["data"]))
                    break
    return out


def _vertex_imagen(prompt: str, aspect_ratio: str, n: int) -> List[bytes]:
    """Genera imágenes con Google Imagen 4 (Vertex AI). Devuelve bytes crudos.
    Reusa la auth de service account de veo_video (mismo token cloud-platform)."""
    from . import veo_video
    s = get_settings()
    if not s.google_service_account_json:
        return []
    token = veo_video._token()
    project = veo_video._project()
    location = veo_video._location()
    model = getattr(s, "vertex_image_model", "imagen-4.0-generate-001")
    url = (f"https://{location}-aiplatform.googleapis.com/v1/projects/{project}"
           f"/locations/{location}/publishers/google/models/{model}:predict")
    body = {
        "instances": [{"prompt": prompt[:1900]}],
        "parameters": {
            "sampleCount": max(1, min(n, 4)),
            "aspectRatio": aspect_ratio or "1:1",
            "personGeneration": "allow_adult",
        },
    }
    with httpx.Client(timeout=180) as c:
        r = c.post(url, json=body, headers={"Authorization": f"Bearer {token}"})
        r.raise_for_status()
        preds = (r.json().get("predictions") or [])
        out = []
        for p in preds:
            b64 = p.get("bytesBase64Encoded")
            if b64:
                import base64
                out.append(base64.b64decode(b64))
        return out


def _minimax_image(prompt: str, aspect_ratio: str, n: int) -> List[bytes]:
    """Genera imágenes con MiniMax image-01 (fallback). Devuelve bytes crudos."""
    s = get_settings()
    body = {
        "model": getattr(s, "image_model", "image-01"),
        "prompt": prompt[:1500],
        "aspect_ratio": aspect_ratio or "1:1",
        "response_format": "url",
        "n": max(1, min(n, 4)),
    }
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
        out = []
        for u in urls:
            try:
                out.append(c.get(u, timeout=90).content)
            except Exception as e:
                log.warning("image_download_failed", error=str(e)[:150])
        return out


def generate_image(prompt: str, aspect_ratio: str = "1:1", n: int = 1,
                   text: Optional[str] = None, subtitle: Optional[str] = None,
                   kind: str = "photo", hero_text: bool = False) -> List[str]:
    """Genera n imágenes (con texto compuesto si se pide) y devuelve URLs locales.
    Provider primario Vertex Imagen 4; fallback automático a MiniMax.

    kind="photo" (default) → foto editorial de una persona en su entorno real.
    kind="banner" → banner/gráfico para ad (producto/ícono/fondo con espacio para
    titular); NO fuerza persona ni entorno.
    kind="art" → ilustración/3D/pieza de diseño: el prompt refinado ya trae el estilo;
    acá sólo se refuerza el no-text (sin sufijo fotográfico ni rotación de plano).
    En todos los casos el texto lo compone Pillow.
    """
    s = get_settings()
    if not enabled() or not (prompt or "").strip():
        return []
    full_prompt = prompt.strip()
    if kind == "banner":
        # Banner de ad: composición gráfica/producto, no necesariamente una persona.
        full_prompt += (". Modern ADVERTISING BANNER / graphic composition: bold, clean, "
                        "high-contrast, brand-forward, premium editorial design. May feature a "
                        "product, a single strong icon/graphic, or a striking background — with "
                        "generous CLEAN EMPTY SPACE reserved for a headline. Navy (#0F1B33) base "
                        "with royal blue (#2563EB) accents. Absolutely NO text, letters, words, "
                        "numbers, captions, watermark or logos (they are composited later). "
                        "Leave clear negative space for the headline.")
    elif kind == "art":
        # Ilustración/3D/tipográfico: el estilo viene completo del refinador; sólo
        # reforzamos el no-text y el aire para el titular.
        full_prompt += (". Absolutely NO text, letters, words, numbers, captions, "
                        "watermark, logos or UI (any headline is composited later). "
                        "Keep clean negative space near one edge for a headline.")
    else:
        # SIEMPRE prohibir texto: los modelos dibujan letras/números deformes e ilegibles.
        # El texto real lo compone Pillow por encima. Negativo fuerte y repetido.
        full_prompt += (". IMPORTANT: real ENVIRONMENTAL photography — the actual location "
                        "(warehouse, depot, storefront, street) must fill the frame and be clearly "
                        "visible around the person. This is NOT a studio portrait: no seamless "
                        "backdrop, no plain gray/white studio background, no fashion catalog look. "
                        "Absolutely NO text, letters, words, numbers, captions, watermark, no brand "
                        "logos on clothing, no UI, no chat bubbles, no screenshots, no charts. "
                        "Plain work clothing. Pure photographic imagery.")
        # Rotar el encuadre (anti-repetición): misma escena, plano/luz distinta cada vez.
        full_prompt += " FRAMING: " + random.choice(_SHOTS)

    provider = getattr(s, "image_provider", "nano")
    # Cadena de fallback: el provider elegido primero, después los demás.
    _chain = {
        "nano":   [("nano", _nano_banana), ("vertex", _vertex_imagen), ("minimax", _minimax_image)],
        "vertex": [("vertex", _vertex_imagen), ("minimax", _minimax_image)],
        "minimax": [("minimax", _minimax_image)],
    }.get(provider, [("nano", _nano_banana), ("vertex", _vertex_imagen), ("minimax", _minimax_image)])
    raws: List[bytes] = []
    used = ""
    for name, fn in _chain:
        try:
            raws = fn(full_prompt, aspect_ratio or "1:1", n)
        except Exception as e:
            log.warning("image_provider_failed", provider=name, error=str(e)[:200])
            raws = []
        if raws:
            used = name
            break
    if not raws:
        return []

    out: List[str] = []
    for raw in raws:
        if text:
            raw = _overlay_text(raw, text, subtitle, hero=hero_text) or raw
        else:
            # Instagram SÓLO acepta JPEG (PNG → "Only photo or video can be
            # accepted as media type"). Normalizamos todo a JPEG.
            raw = _to_jpeg(raw) or raw
        fname = f"{uuid.uuid4().hex}.jpg"
        (_images_dir() / fname).write_bytes(raw)
        local_url = f"/media/{fname}"
        out.append(local_url)
        _notify_discord(local_url, text, subtitle)
    log.info("image_gen_ok", generated=len(out), with_text=bool(text), provider=used)
    return out


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
        # break_long_words=False: una palabra larga ("DISTRIBUIDORA") no se corta al
        # medio — si no entra, el loop achica la fuente hasta que entre entera.
        lines = textwrap.wrap(text, width=per_line, break_long_words=False,
                              break_on_hyphens=False) or [text]
        widest = max(draw.textlength(ln, font=font) for ln in lines)
        line_h = size * 1.12
        total_h = line_h * len(lines)
        if widest <= max_w and total_h <= max_h:
            return font, lines, line_h
        size -= 6
    font = ImageFont.truetype(str(font_path), min_size)
    return font, textwrap.wrap(text, width=max(6, int(max_w / max(draw.textlength('M', font=font), 1))),
                               break_long_words=False, break_on_hyphens=False) or [text], min_size * 1.12


def _grad_band(img, W: int, band_h: int, top: bool = False,
               max_a: int = 225, gamma: float = 0.8) -> None:
    """Degradé navy → transparente para legibilidad (abajo, o arriba si top)."""
    from PIL import Image, ImageDraw
    band = Image.new("RGBA", (W, band_h), (0, 0, 0, 0))
    bd = ImageDraw.Draw(band)
    for y in range(band_h):
        t = (1 - y / band_h) if top else (y / band_h)
        a = int(max_a * t ** gamma)
        bd.line([(0, y), (W, y)], fill=(_NAVY[0], _NAVY[1], _NAVY[2], a))
    img.alpha_composite(band, (0, 0 if top else img.size[1] - band_h))


def _draw_tracked(draw, text: str, font, x: int, y: int, color, track: int = 4) -> None:
    """Dibuja texto con letter-spacing (para el kicker de marca)."""
    cx = x
    for ch in text:
        draw.text((cx, y), ch, font=font, fill=color)
        cx += draw.textlength(ch, font=font) + track


def _draw_lines(draw, lines, font, line_h, y, W, pad, align="center", color=None):
    """Dibuja líneas con sombra. Devuelve la y final."""
    for ln in lines:
        w = draw.textlength(ln, font=font)
        x = pad if align == "left" else (W - w) / 2
        draw.text((x + 2, y + 2), ln, font=font, fill=(0, 0, 0, 110))
        draw.text((x, y), ln, font=font, fill=color or _WHITE)
        y += line_h
    return y


def _overlay_text(img_bytes: bytes, text: str, subtitle: Optional[str] = None,
                  hero: bool = False) -> Optional[bytes]:
    """Compone el titular con tratamiento EDITORIAL en un borde (abajo, o arriba según
    hash) — NUNCA sobre el centro, donde suele estar el sujeto. Gradiente denso para
    legibilidad, barra de acento azul fina, kicker de marca, titular Anton y bajada,
    alineado a la izquierda. Sin recuadros ni bordes (eso se veía a plantilla).

    hero=True (estilo tipográfico): el titular ES la pieza — GIGANTE y centrado en el
    cuadro (el fondo viene casi vacío a propósito), sin gradiente de borde."""
    try:
        import zlib
        from PIL import Image, ImageDraw, ImageFont
        img = Image.open(io.BytesIO(img_bytes)).convert("RGBA")
        W, H = img.size
        draw = ImageDraw.Draw(img, "RGBA")

        head = (text or "").strip().upper()
        sub = (subtitle or "").strip()
        if hero:
            hf, hlines, hlh = _fit_font(draw, head, _HEADLINE_FONT, int(W * 0.86),
                                        int(H * 0.52), start=230, min_size=72)
            kf = ImageFont.truetype(str(_BODY_FONT), max(int(W * 0.026), 22))
            sf = sub_lines = None
            slh = 0
            if sub:
                sf, sub_lines, slh = _fit_font(draw, sub, _BODY_FONT, int(W * 0.8),
                                               int(H * 0.10), start=44, min_size=26)
                sub_lines = sub_lines[:2]
            kh = kf.size + int(H * 0.03)
            block_h = kh + int(hlh * len(hlines)) + (int(H * 0.02) + int(slh * len(sub_lines)) if sub_lines else 0)
            y = (H - block_h) / 2
            kw = sum(draw.textlength(ch, font=kf) + max(int(W * 0.006), 4) for ch in "AUTOMIQ")
            _draw_tracked(draw, "AUTOMIQ", kf, (W - kw) / 2, y, (150, 190, 255, 255),
                          track=max(int(W * 0.006), 4))
            y += kh
            y = _draw_lines(draw, hlines, hf, hlh, y, W, 0, align="center")
            if sub_lines:
                y += int(H * 0.02)
                _draw_lines(draw, sub_lines, sf, slh, y, W, 0, align="center",
                            color=(205, 222, 255, 255))
            out = io.BytesIO()
            img.convert("RGB").save(out, format="JPEG", quality=92)
            return out.getvalue()
        pad = int(W * 0.075)
        bar_w = max(int(W * 0.009), 6)
        x = pad + bar_w + int(W * 0.03)          # el texto arranca a la derecha de la barra
        max_w = W - x - pad
        at_bottom = (zlib.crc32(head.encode("utf-8")) % 2 == 0)

        # gradiente denso en el borde elegido (legibilidad sin sombras duras)
        _grad_band(img, W, int(H * 0.55), top=not at_bottom, max_a=238, gamma=0.9)

        # tipografía: titular Anton; kicker y bajada en DM Sans
        font, lines, line_h = _fit_font(draw, head, _HEADLINE_FONT, max_w,
                                        int(H * 0.30), start=124, min_size=52)
        kf = ImageFont.truetype(str(_BODY_FONT), max(int(W * 0.028), 24))
        sf, sub_lines, slh = None, [], 0
        if sub:
            sf, sub_lines, slh = _fit_font(draw, sub, _BODY_FONT, max_w,
                                           int(H * 0.10), start=48, min_size=28)
            sub_lines = sub_lines[:2]

        kicker = "AUTOMIQ"
        kh = kf.size + int(H * 0.028)
        title_h = int(line_h * len(lines))
        sub_gap = int(H * 0.02) if sub_lines else 0
        block_h = kh + title_h + int(slh * len(sub_lines)) + sub_gap

        y0 = (H - pad - block_h) if at_bottom else pad
        # barra de acento vertical azul (fina, elegante)
        draw.rectangle([pad, y0 + int(kh * 0.12), pad + bar_w, y0 + block_h],
                       fill=(_BLUE[0], _BLUE[1], _BLUE[2], 255))
        y = y0
        _draw_tracked(draw, kicker, kf, x, y, (150, 190, 255, 255), track=max(int(W * 0.006), 4))
        y += kh
        for ln in lines:
            draw.text((x, y), ln, font=font, fill=_WHITE)
            y += line_h
        if sub_lines:
            y += sub_gap
            for ln in sub_lines:
                draw.text((x, y), ln, font=sf, fill=(205, 222, 255, 255))
                y += slh

        out = io.BytesIO()
        # JPEG: Instagram no acepta PNG en su API de publicación.
        img.convert("RGB").save(out, format="JPEG", quality=92)
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
