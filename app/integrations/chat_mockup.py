"""
chat_mockup — genera screenshots REALISTAS de chats (WhatsApp) renderizados con
código (Pillow), no con un modelo de imagen.

Por qué así: los modelos de imagen (MiniMax/Veo) deforman el texto y la UI → no
sirven para una "demo de chatbot". Acá dibujamos la interfaz nosotros → texto
exacto en español, burbujas, tildes de leído, header, input bar = idéntico a un
screenshot real de WhatsApp. Listo para intercalar en un TikTok (1080x1920, 9:16).

Uso:
    render_whatsapp("Inmobiliaria López", [
        {"from": "them", "text": "Hola, vi el depto de Palermo, sigue disponible?", "time": "21:14"},
        {"from": "bot",  "text": "¡Hola! Sí, sigue disponible 🙌 ¿Querés que te agende una visita?", "time": "21:14"},
        {"from": "them", "text": "Dale, mañana a la tarde", "time": "21:15"},
        {"from": "bot",  "text": "Listo ✅ Te agendé para mañana 17:00. Te llega el recordatorio por acá.", "time": "21:15"},
    ])  -> "/media/<file>.jpg"

Best-effort: si algo falla devuelve None.
"""
from __future__ import annotations

import io
import re
import textwrap
import uuid
from pathlib import Path
from typing import Dict, List, Optional

# DMSans no tiene glyphs de emoji → saldrían como cuadritos (tofu) y delatarían el
# mockup. Los quitamos (un chat sin emojis se ve real igual). Rango amplio de
# pictográficos/emoji + variation selectors.
_EMOJI = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF"
    "\U00002190-\U000021FF\U00002B00-\U00002BFF\U0000FE00-\U0000FE0F\U0000200D]+",
    flags=re.UNICODE,
)


def _clean(text: str) -> str:
    """Quita emojis (la fuente no los renderiza) y espacios sobrantes."""
    return re.sub(r"\s{2,}", " ", _EMOJI.sub("", text or "")).strip()

from ..log import get_logger

log = get_logger("chat_mockup")

_FONTS = Path(__file__).resolve().parent.parent / "assets" / "fonts"
_FONT = _FONTS / "DMSans.ttf"

# Paleta WhatsApp (modo claro clásico, el más reconocible)
_BG = (236, 229, 221)            # fondo cremita del chat
_HEADER = (0, 128, 105)          # verde header moderno (#008069)
_BUBBLE_THEM = (255, 255, 255)   # entrante (blanco)
_BUBBLE_BOT = (220, 248, 198)    # saliente (verde clarito #DCF8C6)
_TEXT = (17, 27, 33)
_META = (120, 132, 138)          # timestamp gris
_CHECK = (52, 183, 241)          # doble tilde azul (leído)
_INPUT_BG = (255, 255, 255)


def _images_dir() -> Path:
    d = Path(__file__).resolve().parent.parent.parent / "data" / "images"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _font(size: int):
    from PIL import ImageFont
    return ImageFont.truetype(str(_FONT), size)


def _wrap(draw, text: str, font, max_w: int) -> List[str]:
    """Envuelve respetando palabras según el ancho real en px."""
    words = text.split()
    if not words:
        return [""]
    lines, cur = [], words[0]
    for w in words[1:]:
        if draw.textlength(cur + " " + w, font=font) <= max_w:
            cur += " " + w
        else:
            lines.append(cur); cur = w
    lines.append(cur)
    return lines


def _draw_checks(draw, x: int, y: int, scale: float = 1.0):
    """Dibuja la doble tilde de 'leído' (azul) estilo WhatsApp."""
    c = _CHECK
    w = int(9 * scale)
    def tick(ox):
        draw.line([(ox, y + int(5*scale)), (ox + int(4*scale), y + int(9*scale))], fill=c, width=2)
        draw.line([(ox + int(4*scale), y + int(9*scale)), (ox + int(11*scale), y)], fill=c, width=2)
    tick(x); tick(x + int(6*scale))


def render_whatsapp(business_name: str, messages: List[Dict[str, str]],
                    subtitle: str = "en línea", out_name: Optional[str] = None) -> Optional[str]:
    """Renderiza un chat de WhatsApp realista (1080x1920) y devuelve la URL /media local."""
    try:
        from PIL import Image, ImageDraw
        W, H = 1080, 1920
        img = Image.new("RGB", (W, H), _BG)
        draw = ImageDraw.Draw(img)

        # ── Header ──
        head_h = 150
        draw.rectangle([0, 0, W, head_h], fill=_HEADER)
        # flecha atrás
        draw.line([(46, head_h//2), (78, head_h//2 - 22)], fill=(255,255,255), width=6)
        draw.line([(46, head_h//2), (78, head_h//2 + 22)], fill=(255,255,255), width=6)
        # avatar circular con inicial
        av_d = 90
        av_x, av_y = 100, (head_h - av_d)//2
        draw.ellipse([av_x, av_y, av_x+av_d, av_y+av_d], fill=(180, 200, 196))
        initial = (business_name.strip()[:1] or "A").upper()
        f_av = _font(46)
        iw = draw.textlength(initial, font=f_av)
        draw.text((av_x + (av_d-iw)/2, av_y + 18), initial, font=f_av, fill=(255,255,255))
        # nombre + estado
        f_name = _font(40); f_sub = _font(28)
        draw.text((av_x+av_d+28, 38), business_name[:26], font=f_name, fill=(255,255,255))
        draw.text((av_x+av_d+28, 90), subtitle, font=f_sub, fill=(220, 240, 235))

        # ── Mensajes ──
        f_msg = _font(36); f_time = _font(24)
        pad = 36
        max_bubble = int(W * 0.74)
        y = head_h + 40
        line_h = 46

        for m in messages:
            is_bot = m.get("from") == "bot"
            text = _clean(m.get("text") or "")
            time = (m.get("time") or "").strip()
            inner_w = max_bubble - 2*pad
            lines = []
            for para in text.split("\n"):
                lines += _wrap(draw, para, f_msg, inner_w) if para else [""]
            text_w = max((draw.textlength(ln, font=f_msg) for ln in lines), default=0)
            bw = int(min(max_bubble, max(text_w + 2*pad, 140)))
            bh = len(lines) * line_h + pad + 30   # + espacio para hora
            bx = (W - bw - 30) if is_bot else 30
            by = y
            fill = _BUBBLE_BOT if is_bot else _BUBBLE_THEM
            draw.rounded_rectangle([bx, by, bx+bw, by+bh], radius=28, fill=fill)
            ty = by + pad - 6
            for ln in lines:
                draw.text((bx+pad, ty), ln, font=f_msg, fill=_TEXT)
                ty += line_h
            # hora + tildes
            tw = draw.textlength(time, font=f_time)
            draw.text((bx+bw-pad-tw-(34 if is_bot else 0), by+bh-40), time, font=f_time, fill=_META)
            if is_bot:
                _draw_checks(draw, int(bx+bw-pad-26), by+bh-36, 1.4)
            y = by + bh + 24

        # ── Input bar ──
        ib_h = 110
        iy = H - ib_h
        draw.rectangle([0, iy, W, H], fill=_BG)
        draw.rounded_rectangle([28, iy+18, W-150, H-18], radius=40, fill=_INPUT_BG)
        draw.text((58, iy+44), "Escribí un mensaje", font=_font(34), fill=(150,160,165))
        # botón mic verde
        mb = 78
        draw.ellipse([W-110, iy+(ib_h-mb)//2, W-110+mb, iy+(ib_h-mb)//2+mb], fill=_HEADER)

        out = io.BytesIO()
        img.save(out, format="JPEG", quality=92)
        fname = out_name or f"chat_{uuid.uuid4().hex}.jpg"
        (_images_dir() / fname).write_bytes(out.getvalue())
        log.info("chat_mockup_ok", file=fname, msgs=len(messages))
        return f"/media/{fname}"
    except Exception as e:
        log.warning("chat_mockup_failed", error=str(e)[:200])
        return None
