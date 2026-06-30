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


# Foto de Nazareno (talking) en el volume, servida en /media. Veo la anima (image-to-video).
NAZA_TALKING_PATH = "/media/de18bc9748b44b2397bef59b4c5a1e8b.jpg"

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
            "de Espana, frases repetidas, eco, manos deformes, dedos extra")


def nazareno_veo_prompt(frase: str, escena: str = "en una oficina moderna luminosa") -> str:
    """Prompt de Veo para Nazareno hablando: acento porteño + frase única + anti-repetición."""
    return (
        f"Primer plano de un joven argentino de Buenos Aires hablando a camara, carismatico y "
        f"cercano, {escena}. Habla en espanol rioplatense con marcado ACENTO PORTENO ARGENTINO "
        f"(tono canchero, cercano). Dice UNA SOLA VEZ, sin repetir, con naturalidad: "
        f"\"{frase.strip()}\". Gesticula con una mano, sonrie, leve movimiento de camara tipo vlog. "
        f"Video vertical 9:16 realista, estilo creador de contenido. "
        f"Audio: solo esa frase una vez, sin loops ni frases repetidas."
    )


TIKTOK_INSTRUCTIONS = """
# TikTok Creator — Automiq · marca personal de "Nazareno"

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

`VEO_FRASE: <la frase EXACTA que dice Nazareno en el hook, corta, en español argentino>`
`VEO_ESCENA: <escena en una línea: dónde está, qué hace, en español>`

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
    claude_code_skill = "marketing-redes"
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
            "dueños de PyME argentinas. Cerrá con los bloques VEO_FRASE/VEO_ESCENA (del guión "
            "principal) y, si hay demo de chatbot, el bloque CHAT_NEGOCIO."
            + official_site_directive()
        )

    def post_process(self, response_text: str, ctx: AgentContext) -> str:
        text = response_text or ""
        text = self._add_nazareno_clip(text)      # Veo 3.1 Fast (hook hablado)
        text = self._add_chatbot_mockup(text)      # WhatsApp realista (prueba)
        text = self._add_nazareno_still(text)      # thumbnail (fallback visual)
        return super().post_process(text, ctx)

    # ── Clip de Nazareno con Veo 3.1 Fast ──
    def _add_nazareno_clip(self, text: str) -> str:
        try:
            from ..integrations import veo_video
            from ..config import get_settings
            if not text or not veo_video.enabled():
                return text
            mf = re.search(r"^[\s>*`\-]*VEO_FRASE\s*[:：]\s*(.+)$", text, re.IGNORECASE | re.MULTILINE)
            me = re.search(r"^[\s>*`\-]*VEO_ESCENA\s*[:：]\s*(.+)$", text, re.IGNORECASE | re.MULTILINE)
            if not mf:
                return text
            frase = mf.group(1).strip().strip('"').strip("“”")
            escena = (me.group(1).strip() if me else "en una oficina moderna luminosa")
            s = get_settings()
            base = (s.public_base_url or "").rstrip("/")
            img = f"{base}{NAZA_TALKING_PATH}" if base else None
            res = veo_video.generate_and_wait(
                nazareno_veo_prompt(frase, escena), image_url=img,
                aspect_ratio="9:16", negative_prompt=_VEO_NEG, timeout_s=300, poll=12)
            b64 = res.get("b64")
            if not b64:
                return text
            import base64
            d = Path(__file__).resolve().parent.parent.parent / "data" / "images"
            d.mkdir(parents=True, exist_ok=True)
            fname = f"naza_{uuid.uuid4().hex}.mp4"
            (d / fname).write_bytes(base64.b64decode(b64))
            block = (f"\n\n---\n\n## 🎥 Clip de Nazareno (Veo 3.1 Fast)\n\n"
                     f"Frase: *\"{frase}\"*\n\n`/media/{fname}` — clip 9:16 listo para el hook/cierre.\n")
            return text.rstrip() + block
        except Exception:
            return text

    # ── Mockup de chatbot (WhatsApp realista) ──
    def _add_chatbot_mockup(self, text: str) -> str:
        try:
            from ..integrations import chat_mockup
            if not text:
                return text
            mn = re.search(r"^[\s>*`\-]*CHAT_NEGOCIO\s*[:：]\s*(.+)$", text, re.IGNORECASE | re.MULTILINE)
            if not mn:
                return text
            negocio = mn.group(1).strip()
            msgs = []
            for m in re.finditer(r"^[\s>*`\-]*(them|bot)\s*\|\s*([0-9:]{3,5})\s*\|\s*(.+)$",
                                 text, re.IGNORECASE | re.MULTILINE):
                msgs.append({"from": m.group(1).lower(), "time": m.group(2).strip(),
                             "text": m.group(3).strip()})
            if len(msgs) < 2:
                return text
            url = chat_mockup.render_whatsapp(negocio, msgs[:8])
            if not url:
                return text
            block = (f"\n\n---\n\n## 💬 Demo de chatbot — {negocio} (mockup realista)\n\n"
                     f"![chatbot {negocio}]({url})\n")
            return text.rstrip() + block
        except Exception:
            return text

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
        except Exception:
            return text
