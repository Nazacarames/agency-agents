"""
reel_study — Gemini MIRA los reels del competidor y destila prompts/lecciones.

El sector video es el más flojo del sistema; @ai._kid (Claura) es la referencia
que el algoritmo empuja. Business Discovery nos da el media_url de sus reels
(API oficial, sin scraping) → se bajan los top no estudiados → Gemini 2.5 Pro
(Vertex, misma auth que Veo/nano) los mira DE VERDAD (imagen + audio + texto en
pantalla) y devuelve: estructura, estilo visual, por qué retiene, y prompts
listos (Veo 3.1 / imagen / guión) adaptados a Automiq.

Salidas:
- data/reel-study.md → inyectado a los agentes de contenido vía playbook_block.
- data/reel-study-report-<fecha>.md → informe completo (drive_sync lo sube).
- Alerta Discord (canal social) con el resumen.

Cron semanal (lunes 06:30, antes de la mesa redonda). Estado (ids ya estudiados)
en data/reel-study.json. Best-effort: sin auth de Vertex o sin reels → no-op.
"""
from __future__ import annotations

import base64
import json
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Dict, List

import httpx

from ..config import get_settings
from ..log import get_logger
from .jsonstore import write_json_atomic

log = get_logger("reel_study")

_DATA = Path(__file__).resolve().parent.parent.parent / "data"
_STATE = _DATA / "reel-study.json"
_DIGEST = _DATA / "reel-study.md"
_HANDLE = "ai._kid"
_MAX_VIDEO_MB = 18          # límite inline de Gemini ~20MB; margen
_MODELS = ("gemini-2.5-pro", "gemini-2.5-flash")

_PROMPT = """Sos director creativo de Automiq (agencia de automatización con IA; público:
dueños de pymes argentinas). Este reel es de @{handle}, un competidor cuyo contenido el
algoritmo empuja fuerte. Caption: "{caption}". Métricas: {likes} likes, {comments} comentarios.

MIRÁ el video completo (imagen + audio + texto en pantalla) y devolvé en español
rioplatense, en markdown con estos títulos exactos:

## Qué hace ({permalink})
Estructura con timestamps (hook 0-3s / desarrollo / CTA), texto en pantalla clave, y
estilo visual concreto: encuadre, ritmo de cortes, colores, tipografía, voz/música.

## Por qué retiene
La mecánica, en criollo, en 3-4 bullets.

## Para robar (adaptado a Automiq)
- **Prompt Veo 3.1** (clip 8s, 9:16, con la estética de este reel pero escena nuestra):
- **Prompt imagen** (tapa de carrusel con la misma energía):
- **Guión nuestro** (hook 1ª persona con número + 3 beats + CTA comment-gate con keyword):
- **Lección de edición** (1 línea accionable para nuestros shorts):"""


def _discover(limit: int = 25) -> List[Dict]:
    """Reels del competidor vía Business Discovery (media_url incluido)."""
    s = get_settings()
    if not (s.meta_page_token and s.ig_business_id):
        return []
    fields = (f"business_discovery.username({_HANDLE}){{media.limit({limit})"
              f"{{id,media_type,media_url,like_count,comments_count,caption,permalink}}}}")
    url = (f"https://graph.facebook.com/v21.0/{s.ig_business_id}"
           f"?fields={urllib.parse.quote(fields)}"
           f"&access_token={urllib.parse.quote(s.meta_page_token)}")
    try:
        r = json.load(urllib.request.urlopen(url, timeout=60))
    except Exception as e:
        log.warning("reel_discover_failed", error=str(e)[:200])
        return []
    media = ((r.get("business_discovery") or {}).get("media") or {}).get("data") or []
    vids = [m for m in media if m.get("media_type") == "VIDEO" and m.get("media_url")]
    vids.sort(key=lambda m: m.get("like_count", 0), reverse=True)
    return vids


def _gemini_watch(video: bytes, prompt: str) -> str:
    """Le da el video a Gemini (Vertex) y devuelve el análisis. '' si falla."""
    from . import veo_video
    s = get_settings()
    if not s.google_service_account_json:
        return ""
    token, project = veo_video._token(), veo_video._project()
    body = {
        "contents": [{"role": "user", "parts": [
            {"inlineData": {"mimeType": "video/mp4",
                            "data": base64.b64encode(video).decode()}},
            {"text": prompt},
        ]}],
        "generationConfig": {"temperature": 0.4, "maxOutputTokens": 6000},
    }
    for model in _MODELS:
        url = (f"https://aiplatform.googleapis.com/v1beta1/projects/{project}"
               f"/locations/global/publishers/google/models/{model}:generateContent")
        try:
            with httpx.Client(timeout=420) as c:
                r = c.post(url, json=body, headers={"Authorization": f"Bearer {token}"})
            if r.status_code == 200:
                parts = (((r.json().get("candidates") or [{}])[0])
                         .get("content", {}) or {}).get("parts", [])
                text = "".join(p.get("text", "") for p in parts).strip()
                if text:
                    return text
            log.warning("gemini_watch_status", model=model, status=r.status_code,
                        detail=r.text[:200])
        except Exception as e:
            log.warning("gemini_watch_failed", model=model, error=str(e)[:150])
    return ""


def study(n: int = 2) -> Dict[str, int]:
    """Estudia los n reels top NO estudiados. Devuelve contadores."""
    try:
        st = json.loads(_STATE.read_text(encoding="utf-8"))
    except Exception:
        st = {"studied": []}
    studied = set(st.get("studied", []))
    pending = [m for m in _discover() if m["id"] not in studied][:n]
    if not pending:
        log.info("reel_study_nothing_new")
        return {"ok": True, "estudiados": 0}

    sections: List[str] = []
    for m in pending:
        try:
            with urllib.request.urlopen(m["media_url"], timeout=120) as r:
                video = r.read()
        except Exception as e:
            log.warning("reel_download_failed", id=m["id"], error=str(e)[:150])
            continue
        if len(video) > _MAX_VIDEO_MB * 1024 * 1024:
            log.info("reel_too_big", id=m["id"], mb=len(video) // (1024 * 1024))
            studied.add(m["id"])  # no reintentar cada semana
            continue
        analysis = _gemini_watch(video, _PROMPT.format(
            handle=_HANDLE, caption=(m.get("caption") or "")[:200].replace('"', "'"),
            likes=m.get("like_count", 0), comments=m.get("comments_count", 0),
            permalink=m.get("permalink", "")))
        if analysis:
            sections.append(analysis)
            studied.add(m["id"])
            log.info("reel_studied", id=m["id"], likes=m.get("like_count", 0))
            # Cosechar la "Lección de edición" al almacén de lecciones (se reinyecta
            # en cada short nuestro vía creative_learnings — retroalimentación).
            try:
                import re as _re
                from . import creative_learnings
                ml = _re.search(r"Lección de edición[^:：]*[:：]\s*\**\s*(.+)", analysis)
                if ml:
                    creative_learnings.add(ml.group(1).strip(), "reel_study", "video")
            except Exception:
                pass

    if not sections:
        return {"ok": False, "estudiados": 0}

    from ..agents._common import today_ar
    today = today_ar()
    body = f"# Estudio de reels @{_HANDLE} — {today}\n\n" + "\n\n---\n\n".join(sections)
    _DIGEST.write_text(body, encoding="utf-8")
    (_DATA / f"reel-study-report-{today}.md").write_text(body, encoding="utf-8")
    st["studied"] = list(studied)[-500:]
    write_json_atomic(_STATE, st)

    try:
        from ..clients.discord import DiscordWebhook
        s = get_settings()
        if s.discord_configured:
            dw = DiscordWebhook(s)
            dw.send_agent_output(
                agent_name="🎬 Estudio de reels (Gemini miró al competidor)",
                text=f"{len(sections)} reels de @{_HANDLE} analizados a fondo "
                     f"(video+audio+texto). Prompts y lecciones ya inyectados a los "
                     f"agentes de contenido.\n\n" + body[:1400],
                run_id="reel-study",
                url=s.discord_webhook_for("social"),
                color=0x9B59B6,
            )
            dw.close()
    except Exception as e:
        log.warning("reel_study_notify_failed", error=str(e)[:150])
    return {"ok": True, "estudiados": len(sections)}


def block() -> str:
    """Bloque para inyectar a los agentes (último estudio, capado)."""
    try:
        t = _DIGEST.read_text(encoding="utf-8").strip()
    except Exception:
        return ""
    if not t:
        return ""
    return ("\n\n=== ESTUDIO DE VIDEO DEL COMPETIDOR (Gemini MIRÓ sus reels — usá estos "
            "prompts/lecciones) ===\n" + t[:4500] + "\n=== fin estudio de video ===")
