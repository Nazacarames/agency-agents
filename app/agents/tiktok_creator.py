"""
TikTok Creator — marca personal de "Nazareno" (avatar de Automiq) en TikTok.

Reescrito 2026-06-30 sobre el playbook de marca personal (Caleb Ralston aplicado +
formatos virales 2026). Ver vault: Automiq/Marca/Estrategia-Marca-Personal-Nazareno.

Cada tanda entrega 3 guiones en formatos que NO parecen anuncios (construir en
público, error/mito, micro-caso, etc.) con la fórmula gancho→tensión→prueba→remate→CTA.
Además, automáticamente:
  - genera el CLIP de Nazareno hablando con **Veo 3.1 Fast** (acento porteño, frase
    única, anti-repetición) para el hook/cierre, y
  - renderiza un **mockup de chatbot de WhatsApp** (idéntico a real, texto exacto vía
    Pillow) para la "prueba" — porque Veo no puede mostrar UIs reales.
El output queda como report (panel + Discord). El armado final del video (Veo + mockup
+ subtítulos) y el auto-posteo a TikTok son la fase siguiente (TikTok requiere aprobar
la app). NO postea a IG/FB (eso es del content_creator).
"""
import re
import uuid
from pathlib import Path

from .base import BaseAgent, AgentContext
from ._common import get_context_block, official_site_directive
from ..log import get_logger

log = get_logger("tiktok_creator")


# Fotos canónicas de Nazareno (en /media). Se pasan como REFERENCE IMAGES a Veo 3.1
# (referenceType=asset) → misma cara en todas las escenas, sin importar el lugar.
NAZA_REFERENCE_PATHS = [
    "/media/de18bc9748b44b2397bef59b4c5a1e8b.jpg",  # hablando a cámara
    "/media/e01a2f7651334c97a262e70f826ab9f6.jpg",  # headshot
]
NAZA_TALKING_PATH = NAZA_REFERENCE_PATHS[0]  # compat

# Lugares HABITUALES de grabación (set fijo, se rotan; descripciones consistentes y
# con fondo NÍTIDO para que no quede efecto retrato).
NAZA_LUGARES = {
    "oficina": ("en la oficina moderna de su agencia: pared azul navy, escritorio con un "
                "monitor que muestra paneles, una planta, ventana con luz natural de día"),
    "casa": ("en el living de su departamento en Buenos Aires: sofá, biblioteca con libros "
             "y plantas, una lámpara cálida, luz natural de una ventana"),
    "cafe": ("en un café porteño: mesa de madera, una taza de café, interior cálido con "
             "madera y luz suave de la ventana"),
    "escritorio": ("sentado en su escritorio con una laptop y un monitor con dashboards, "
                   "estilo creador de contenido, luz natural"),
}
NAZA_LUGAR_DEFAULT = "oficina"

# Ancla de identidad de Nazareno — se repite idéntica para mantener la misma cara (thumbnails).
NAZARENO_IDENTITY = (
    "Nazareno, a 25-year-old Argentine man from Buenos Aires, with a warm, confident, "
    "friendly and approachable presence. Exact same face every time: oval face with a soft "
    "defined jawline, fair-to-light-olive skin, short modern textured LIGHT BROWN hair "
    "(castano claro), neatly groomed short light-brown stubble beard, warm hazel-brown eyes, "
    "defined natural eyebrows, straight nose, genuine bright friendly smile with white teeth. "
    "Slim athletic build. Modern smart-casual wardrobe in brand navy blue and white: a navy "
    "blazer over a plain white t-shirt. Young, sharp, likeable entrepreneur vibe. "
    "Photorealistic editorial photograph, shot on a 50mm lens, soft natural cinematic lighting, "
    "shallow depth of field, crisp realistic skin texture, high-end 8k quality."
)

_VEO_NEG = ("subtitulos, texto en pantalla, acento neutro, acento mexicano, acento espanol "
            "de Espana, frases repetidas, eco, pronunciacion incorrecta, voz robotica, "
            "fondo desenfocado, bokeh, profundidad de campo, efecto retrato, manos deformes, dedos extra")


def nazareno_veo_prompt(frase: str, lugar: str = NAZA_LUGAR_DEFAULT) -> str:
    """Prompt de Veo: misma cara (referencia) + lugar fijo + fondo nítido + dicción clara.

    `lugar` = clave de NAZA_LUGARES (oficina/casa/cafe/escritorio).
    """
    escena = NAZA_LUGARES.get(lugar, NAZA_LUGARES[NAZA_LUGAR_DEFAULT])
    return (
        f"Nazareno, un joven argentino de Buenos Aires, {escena}. "
        f"FONDO NITIDO y bien enfocado, toda la escena en foco, SIN desenfoque ni efecto "
        f"retrato, look realista de camara de celular. "
        f"Habla a camara, PAUSADO y con DICCION CLARA, en espanol rioplatense con acento "
        f"porteno argentino natural (no exagerado). Dice la frase completa UNA SOLA VEZ, sin "
        f"repetir ni trabarse: \"{frase.strip()}\". Al terminar de hablar queda en silencio "
        f"mirando a camara con una sonrisa (no agrega ni repite nada). "
        f"Gesticula levemente con una mano, leve movimiento de camara. Video vertical 9:16 realista."
    )


TIKTOK_INSTRUCTIONS = """
# TikTok Creator — Automiq · marca personal de "Nazareno"

> Tip: si querés validar hooks/tendencias del algoritmo, delegá al subagente
> `tiktok-strategist` (tool Task) antes de escribir los guiones.

## Quién sos
Sos **Nazareno**: 25 años, porteño, la cara de Automiq en TikTok. Explicás IA y
automatización para dueños de PyME argentinas en criollo, sin humo, traduciendo la
tecnología en **plata, tiempo y clientes**. Cálido, directo, práctico. Tuteo argentino
(vos, mirá, fijate, che), frases cortas, una idea por video.

## La regla de oro (NO negociable)
**Los videos NO pueden parecer anuncios.** Nada de "contratá a Automiq". Enseñás,
mostrás y construís en público. El producto (los agentes/automatizaciones de Automiq)
aparece como **PRUEBA**, jamás como pitch. La venta es consecuencia de la autoridad.

## Estrategia (Caleb Ralston aplicado)
- **Document > Create:** no inventes; mostrá lo que Automiq YA hace (un bot que contesta
  solo, un lead que entró por una automatización, un agente trabajando). Es real e inimitable.
- **Pilar líder: "construir en público"** — la historia única de Automiq (agencia con
  agentes de IA reales corriendo 24/7).
- **Métrica norte: retención.** Gancho de 3s o el video muere.

## Formatos (elegí 3 DISTINTOS por tanda)
1. **Error/Mito** ("Si seguís contestando los WhatsApp a mano, estás perdiendo plata").
2. **Micro-caso** ("Le puse un agente de IA a una inmobiliaria por 7 días. Esto pasó").
3. **Construir en público** ("Así trabajan los 12 agentes que corren mi agencia").
4. **Antes/Después** (tarea manual → automatizada, con el tiempo ahorrado).
5. **Tutorial 1 micro-skill** ("Un truco para que la IA te conteste los DMs solo").
6. **Top 3** ("3 tareas que tu negocio debería automatizar YA").

## La fórmula de cada guión
`GANCHO (0-3s, frena el scroll) → TENSIÓN (mostrá el problema/el cómo) → PRUEBA (demo real / número) → REMATE → CTA suave`

## Formato OBLIGATORIO de salida por guión
1. **Título interno** + **Formato** (uno de los 6).
2. **GANCHO (0-3s)**: la primera frase hablada + el cartel inicial (máx 60 chars).
3. **Guión hablado por beats**: [0-3s], [3-12s], [12-25s], [cierre]. Natural, hablado.
4. **Texto en pantalla**: 3-5 carteles cortos.
5. **Plano de PRUEBA**: qué captura/demo real se intercala (bot de WhatsApp, CRM, dashboard).
6. **CTA suave** (seguinos, comentá "IA", escribinos).
7. **Caption** + **Hashtags** (5-8, nicho PyME+IA+Argentina) + **Audio sugerido**.

## Bloques especiales para los assets (los lee el sistema, ponelos EXACTO)
Para el guión PRINCIPAL (el primero), agregá al final de TODO:

`VEO_FRASE: <la frase EXACTA que dice Nazareno, en español argentino, de ~20-25 palabras (que dure unos 8s hablada a ritmo normal; ni muy corta —repite— ni muy larga —se corta—). Sin siglas: escribí "inteligencia artificial", no "IA".>`
`VEO_LUGAR: <uno de: oficina | casa | cafe | escritorio>`  ← lugar habitual de grabación, rotalos entre tandas

Si el guión usa una demo de chatbot, agregá un bloque de chat así (el sistema lo
renderiza como WhatsApp real). Mensajes del cliente = `them`, del bot = `bot`:
```
CHAT_NEGOCIO: <nombre del negocio ej. Inmobiliaria López>
them | 21:14 | <mensaje del cliente>
bot | 21:14 | <respuesta del bot, natural, argentina>
them | 21:15 | <...>
bot | 21:15 | <...>
```

## Reglas
- Español argentino, una idea por video, gancho fuerte SIEMPRE.
- Empezá por el PROBLEMA del dueño de PyME; la herramienta recién al final.
- NO prometer resultados garantizados. NADA que suene a anuncio.
- Guiones completos, listos para producir.
""".strip()


class TikTokCreatorAgent(BaseAgent):
    name = "tiktok_creator"
    description = "Marca personal de Nazareno en TikTok: guiones (no-ad) + clip Veo + mockup de chatbot"
    schedule = "0 19 * * mon,wed,fri"
    timezone = "America/Buenos_Aires"
    max_tokens = 12000
    use_claude_code = True
    claude_code_skill = "marketing-redes,reels-scripting,hook-generator,stop-slop"
    claude_code_timeout = 700

    @property
    def system_prompt(self) -> str:
        return f"{get_context_block()}\n\n{TIKTOK_INSTRUCTIONS}"

    def build_user_message(self, ctx: AgentContext) -> str:
        return (
            "Generá los 3 guiones de TikTok de hoy en la voz de Nazareno, liderando con el "
            "pilar 'construir en público'. Elegí 3 FORMATOS distintos. Cada guión 100% listo "
            "con la fórmula gancho→tensión→prueba→remate→CTA. Recordá: NADA puede parecer un "
            "anuncio — enseñás y mostrás, la herramienta es la prueba, no el pitch. Público: "
            "dueños de PyME argentinas. Cerrá con los bloques VEO_FRASE/VEO_LUGAR (del guión "
            "principal) y, si hay demo de chatbot, el bloque CHAT_NEGOCIO."
            + official_site_directive()
        )

    def post_process(self, response_text: str, ctx: AgentContext) -> str:
        text = response_text or ""
        text, clip_path = self._add_nazareno_clip(text)      # Veo 3.1 Fast (hook hablado)
        text, mock_frames = self._add_chatbot_mockup(text)   # chat WhatsApp ANIMADO (frames)
        text = self._assemble_final(text, clip_path, mock_frames)  # short armado (ffmpeg)
        text = self._add_nazareno_still(text)                # thumbnail (fallback visual)
        return super().post_process(text, ctx)

    def _media_to_path(self, media_url):
        """/media/<file> -> path local en data/images."""
        if not media_url:
            return None
        fname = str(media_url).rstrip("/").split("/")[-1]
        p = Path(__file__).resolve().parent.parent.parent / "data" / "images" / fname
        return str(p) if p.exists() else None

    # ── Armado final del video (Veo + demo animada → 1 mp4) ──
    def _assemble_final(self, text: str, clip_path, mock_frames) -> str:
        try:
            from ..integrations import video_assembler
            if not clip_path:
                return text
            frames = [p for p in (mock_frames or []) if p]
            if frames:
                url = video_assembler.assemble_short_animated(clip_path, frames)
            else:
                url = video_assembler.assemble_short(clip_path, [], proof_dur=5.0)
            if not url:
                return text
            block = (f"\n\n---\n\n## 🎬 Video armado (listo para postear)\n\n"
                     f"`{url}` — short 9:16: Nazareno + chat animado (mensajes llegando), "
                     f"ensamblado automático.\n")
            text = text.rstrip() + block
            text = self._maybe_upload_youtube(text, self._media_to_path(url))
            text = self._enqueue_ig_reel(text, url)
            text = self._maybe_post_tiktok(text, self._media_to_path(url), url)
            return text
        except Exception as e:
            log.warning("tiktok_assemble_failed", error=str(e)[:300])
            return text

    def _enqueue_ig_reel(self, text: str, video_url: str) -> str:
        """Publica el short como REEL de Instagram EN EL MOMENTO (junto con la subida
        a YouTube/TikTok — decisión del usuario: los videos salen todos juntos y no
        esperan el turno diario del feed). Se registra en Publicaciones sin tocar el
        tope 1/día de posts."""
        try:
            from ..integrations import social_publish as sp, publish_queue as pq
            if not sp.ig_enabled():
                return text
            mc = re.search(r"^[\s>*`\-]*Caption\s*[:：]\s*(.+)$", text, re.IGNORECASE | re.MULTILINE)
            caption = (mc.group(1).strip() if mc else "IA y automatización para PyMEs 🇦🇷")
            res = sp.publish_instagram_reel(video_url, caption)
            pq.record_published(image=video_url, caption=caption, target="instagram",
                                result=res, source="tiktok_creator", kind="reel")
            if res.get("ok"):
                link = res.get("permalink") or ""
                return text.rstrip() + f"\n\n## 🎞️ Publicado como Reel de Instagram\n\n{link}\n"
            log.warning("tiktok_reel_publish_failed", error=str(res.get('error',''))[:200])
            return text.rstrip() + f"\n\n> ⚠️ El reel de IG falló: {str(res.get('error',''))[:140]}\n"
        except Exception as e:
            log.warning("tiktok_reel_enqueue_failed", error=str(e)[:200])
            return text

    def _maybe_post_tiktok(self, text: str, video_path, video_url: str) -> str:
        """Sube el short a TikTok vía FILE_UPLOAD (no necesita dominio verificado).
        En sandbox queda PRIVADO (SELF_ONLY) hasta que la app pase la revisión."""
        try:
            from ..config import get_settings
            from ..integrations.tiktok_client import get_tiktok_client
            s = get_settings()
            if not video_path or not getattr(s, "tiktok_configured", False):
                return text
            tc = get_tiktok_client(s)
            if not tc.status().get("connected"):
                return text
            mc = re.search(r"^[\s>*`\-]*Caption\s*[:：]\s*(.+)$", text, re.IGNORECASE | re.MULTILINE)
            caption = (mc.group(1).strip() if mc else "IA y automatización para PyMEs 🇦🇷")
            res = tc.post_video_file_upload(Path(str(video_path)).read_bytes(), caption)
            pid = (res.get("data") or {}).get("publish_id")
            priv = "SELF_ONLY" if s.tiktok_sandbox else "PUBLIC_TO_EVERYONE"
            try:
                from ..integrations import publish_queue as pq
                pq.record_published(image=video_url, caption=caption, target="tiktok",
                                    result={"ok": True, "id": pid, "privacy": priv},
                                    source="tiktok_creator", kind="reel")
            except Exception as e:
                log.warning("tiktok_publog_failed", error=str(e)[:200])
            extra = " (PRIVADO — sandbox, hasta pasar la revisión de la app)" if s.tiktok_sandbox else ""
            return text.rstrip() + f"\n\n## 🎵 Subido a TikTok{extra}\n\npublish_id: `{pid}`\n"
        except Exception as e:
            log.warning("tiktok_post_failed", error=str(e)[:300])
            return text.rstrip() + f"\n\n> ⚠️ TikTok falló: {str(e)[:140]}\n"

    def _maybe_upload_youtube(self, text: str, video_path) -> str:
        """Sube el short a YouTube si youtube_autoupload está activo (default: privado)."""
        try:
            from ..config import get_settings
            from ..integrations import youtube_client as yt
            s = get_settings()
            if not video_path or not getattr(s, "youtube_autoupload", False) or not yt.enabled():
                return text
            # título = primer Caption del guión, o fallback
            mc = re.search(r"^[\s>*`\-]*Caption\s*[:：]\s*(.+)$", text, re.IGNORECASE | re.MULTILINE)
            base_title = (mc.group(1).strip() if mc else "Automiq · IA para tu negocio")
            title = (base_title[:90] + " #Shorts")
            desc = (f"{base_title}\n\nIA y automatización para PyMEs argentinas. "
                    f"Seguime para más: @automiqia\n\n#Shorts #IA #automatizacion #pymes #argentina")
            tags = ["IA", "automatizacion", "inteligencia artificial", "pymes", "argentina",
                    "whatsapp", "negocios", "shorts"]
            res = yt.upload_video(str(video_path), title, desc, tags)
            # Registrar en Publicaciones del panel (sin tocar el tope 1/día de IG/FB).
            try:
                from ..integrations import publish_queue as pq
                pq.record_published(
                    image=f"/media/{Path(str(video_path)).name}", caption=title,
                    target="youtube",
                    result={"ok": True, "id": res.get("id"), "permalink": res.get("url"),
                            "privacy": res.get("privacy")},
                    source="tiktok_creator")
            except Exception as e:
                log.warning("tiktok_publog_failed", error=str(e)[:200])
            block = (f"\n\n## 📺 Subido a YouTube ({res.get('privacy')})\n\n"
                     f"{res.get('url')}\n")
            return text.rstrip() + block
        except Exception as e:
            log.warning("tiktok_youtube_upload_failed", error=str(e)[:300])
            return text

    # ── Clip de Nazareno con Veo 3.1 Fast ──
    def _add_nazareno_clip(self, text: str):
        """Devuelve (texto, path_local_del_clip | None)."""
        try:
            from ..integrations import veo_video
            from ..config import get_settings
            if not text or not veo_video.enabled():
                return text, None
            mf = re.search(r"^[\s>*`\-]*VEO_FRASE\s*[:：]\s*(.+)$", text, re.IGNORECASE | re.MULTILINE)
            ml = re.search(r"^[\s>*`\-]*VEO_LUGAR\s*[:：]\s*(\w+)", text, re.IGNORECASE | re.MULTILINE)
            if not mf:
                return text, None
            frase = mf.group(1).strip().strip('"').strip("“”")
            lugar = (ml.group(1).strip().lower() if ml else NAZA_LUGAR_DEFAULT)
            if lugar not in NAZA_LUGARES:
                lugar = NAZA_LUGAR_DEFAULT
            s = get_settings()
            base = (s.public_base_url or "").rstrip("/")
            refs = [f"{base}{p}" for p in NAZA_REFERENCE_PATHS] if base else None
            res = veo_video.generate_and_wait(
                nazareno_veo_prompt(frase, lugar), reference_image_urls=refs,
                aspect_ratio="9:16", negative_prompt=_VEO_NEG, timeout_s=300, poll=12)
            b64 = res.get("b64")
            if not b64:
                return text, None
            import base64
            d = Path(__file__).resolve().parent.parent.parent / "data" / "images"
            d.mkdir(parents=True, exist_ok=True)
            fname = f"naza_{uuid.uuid4().hex}.mp4"
            fpath = d / fname
            fpath.write_bytes(base64.b64decode(b64))
            block = (f"\n\n---\n\n## 🎥 Clip de Nazareno (Veo 3.1 Fast)\n\n"
                     f"Frase: *\"{frase}\"*\n\n`/media/{fname}` — clip 9:16 listo para el hook/cierre.\n")
            return text.rstrip() + block, str(fpath)
        except Exception as e:
            log.warning("tiktok_veo_clip_failed", error=str(e)[:300])
            return text, None

    # ── Demo de chatbot (WhatsApp ANIMADO: mensajes que van llegando) ──
    def _add_chatbot_mockup(self, text: str):
        """Devuelve (texto, [paths_locales_de_los_frames] | None)."""
        try:
            from ..integrations import chat_mockup
            if not text:
                return text, None
            mn = re.search(r"^[\s>*`\-]*CHAT_NEGOCIO\s*[:：]\s*(.+)$", text, re.IGNORECASE | re.MULTILINE)
            if not mn:
                return text, None
            negocio = mn.group(1).strip()
            msgs = []
            for m in re.finditer(r"^[\s>*`\-]*(them|bot)\s*\|\s*([0-9:]{3,5})\s*\|\s*(.+)$",
                                 text, re.IGNORECASE | re.MULTILINE):
                msgs.append({"from": m.group(1).lower(), "time": m.group(2).strip(),
                             "text": m.group(3).strip()})
            if len(msgs) < 2:
                return text, None
            # Frames de la animación (mensaje a mensaje + "escribiendo…").
            frame_urls = chat_mockup.render_whatsapp_frames(negocio, msgs[:8])
            if not frame_urls:
                # fallback: mockup estático
                url = chat_mockup.render_whatsapp(negocio, msgs[:8])
                if not url:
                    return text, None
                frame_urls = [url]
            last = frame_urls[-1]
            block = (f"\n\n---\n\n## 💬 Demo de chatbot — {negocio} (animada, {len(frame_urls)} frames)\n\n"
                     f"![chatbot {negocio}]({last})\n")
            paths = [p for p in (self._media_to_path(u) for u in frame_urls) if p]
            return text.rstrip() + block, paths or None
        except Exception as e:
            log.warning("tiktok_mockup_failed", error=str(e)[:300])
            return text, None

    # ── Thumbnail (still de Nazareno) ──
    def _add_nazareno_still(self, text: str) -> str:
        try:
            from ..integrations import image_gen
            if not text or not image_gen.enabled():
                return text
            m = re.search(r"^[\s>*`\-]*IMAGEN\s*[:：]\s*(.+)$", text, re.IGNORECASE | re.MULTILINE)
            scene = (m.group(1).strip() if m else
                     "talking directly to the camera in a bright modern office, energetic, vertical")
            urls = image_gen.generate_image(f"{NAZARENO_IDENTITY} SCENE: {scene}",
                                            aspect_ratio="9:16", n=1)
            if not urls:
                return text
            block = (f"\n\n---\n\n## 🖼️ Thumbnail (Nazareno)\n\n![thumbnail nazareno]({urls[0]})\n")
            return text.rstrip() + block
        except Exception as e:
            log.warning("tiktok_thumbnail_failed", error=str(e)[:300])
            return text
