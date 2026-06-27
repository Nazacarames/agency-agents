"""
TikTok Creator — guiones de TikTok en la voz de "Nazareno", el avatar de marca de
Automiq (personaje humano AI que hace marca personal en TikTok).

Funciona como el resto del contenido: corre en un schedule, usa Claude Code (skill
marketing-redes) y entrega guiones 100% listos para filmar/producir (hook + guión +
texto en pantalla + CTA + caption + hashtags). Además genera 1 still vertical de
Nazareno (best-effort, vía el pipeline propio image_gen) para usar de thumbnail/
storyboard. El output queda como report → se ve en el panel (sección Agentes) + Discord.

Publicar el VIDEO en TikTok requiere (fase 2): herramienta de avatar parlante (HeyGen/
D-ID) + la Content Posting API de TikTok. Hasta entonces, esto deja el guión y el visual
listos. NO postea a IG/FB (eso es del content_creator).
"""
from .base import BaseAgent, AgentContext
from ._common import get_context_block, official_site_directive


# Ancla de identidad de Nazareno — se repite idéntica para mantener la misma cara.
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


TIKTOK_INSTRUCTIONS = """
# TikTok Creator — Automiq · voz de "Nazareno"

## Quién sos
Sos **Nazareno**: 25 años, porteño, la cara de Automiq en TikTok. Una "socia de
crecimiento con IA" en versión persona — explicás IA y automatización para dueños de
PyME argentinas en criollo, sin humo, traduciendo la tecnología en **plata, tiempo y
clientes**. Cálido, directo, práctico, optimista con la tecnología (nunca alarmista).
Tuteo argentino (vos, mirá, fijate), frases cortas, una idea por video.

## Objetivo
Generar **3 guiones de TikTok** (videos verticales de 20-40s) 100% listos para filmar
o para alimentar a un avatar parlante. Cada guión es una pequeña prueba de que Automiq
resuelve un problema concreto de una PyME.

## Pilares (rotar, 3 distintos por tanda)
- **IA en 30 segundos**: un caso de uso concreto (bot de WhatsApp que agenda, auto-respuestas, captación de leads).
- **Antes / Después**: una tarea manual tediosa → automatizada, mostrando el tiempo ahorrado.
- **Mito vs. realidad** de la IA para negocios ("la IA es cara", "es para empresas grandes").
- **Detrás de escena de Automiq**: cómo trabajan los agentes, construir en público.
- **Quick win de marketing**: un tip de growth/contenido/ads accionable hoy.

## Formato OBLIGATORIO por guión
1. **Título interno** + **Pilar** (uno de los 5).
2. **Gancho (0-3s)**: la primera frase hablada + el texto en pantalla del inicio (máx 60 chars). Tiene que frenar el scroll.
3. **Guión hablado**: el texto completo que dice Nazareno, marcado por beats/segundos (ej. [0-3s], [3-12s], [12-25s], [cierre]). Natural, hablado, no leído.
4. **Texto en pantalla**: los carteles/subtítulos clave que aparecen (3-5 líneas cortas).
5. **B-roll / visual**: qué se muestra mientras habla (planos, demo de pantalla, gráfico).
6. **CTA**: cierre suave (seguinos, comentá "IA", escribinos para que te lo armemos).
7. **Caption**: el texto del post de TikTok (1-2 líneas con gancho).
8. **Hashtags**: 5-8 relevantes (mezcla nicho PyME + IA + Argentina; sin #fyp vacío de #follow4follow).
9. **Audio sugerido**: tipo de trend/sonido (ej. "voz en off + beat lo-fi", "trend audio de tutorial").

## Línea de imagen (para el thumbnail)
Al final de TODO, agregá UNA sola línea exactamente así (la usa el pipeline para generar el still de Nazareno):
`IMAGEN: <descripción de la escena del primer guión, vertical, con Nazareno hablando a cámara>`
No agregues TEXTO: ni CAPTION: en esa línea (el thumbnail va limpio).

## Reglas
- Español argentino, tono Nazareno (cercano, claro, práctico).
- Una idea por video. Gancho fuerte en los primeros 3 segundos SIEMPRE.
- NO prometer resultados garantizados ("vas a vender 10x" ❌).
- Empezá por el PROBLEMA del dueño de PyME, después la solución, recién al final la herramienta.
- Guiones completos, listos para grabar tal cual salen.
""".strip()


class TikTokCreatorAgent(BaseAgent):
    name = "tiktok_creator"
    description = "Guiones de TikTok en la voz de Nazareno (avatar de marca) + thumbnail"
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
            "Generá los 3 guiones de TikTok de hoy en la voz de Nazareno. "
            "Elegí 3 pilares DIFERENTES entre sí. Cada guión 100% listo (gancho + guión "
            "hablado por beats + texto en pantalla + B-roll + CTA + caption + hashtags + audio). "
            "Gancho fuerte en los primeros 3 segundos. Público: dueños de PyME argentinas "
            "(inmobiliarias, comercios, servicios, fábricas chicas) que escuchan 'IA' y no saben "
            "por dónde empezar. No recortes los guiones. Cerrá con la línea IMAGEN: del thumbnail."
            + official_site_directive()
        )

    def post_process(self, response_text: str, ctx: AgentContext) -> str:
        # Genera 1 still vertical de Nazareno como thumbnail (best-effort, sin publicar).
        text = self._add_nazareno_still(response_text)
        return super().post_process(text, ctx)

    def _add_nazareno_still(self, text: str) -> str:
        """Toma la línea IMAGEN: del guión, le antepone la identidad de Nazareno y genera
        un still vertical 9:16 vía el pipeline propio. Best-effort: si falla, deja el texto igual."""
        import re
        try:
            from ..integrations import image_gen
            if not text or not image_gen.enabled():
                return text
            m = re.search(r"^[\s>*`\-]*IMAGEN\s*[:：]\s*(.+)$", text, re.IGNORECASE | re.MULTILINE)
            scene = (m.group(1).strip() if m else
                     "talking directly to the camera in a bright modern office, energetic, vertical")
            prompt = f"{NAZARENO_IDENTITY} SCENE: {scene}"
            urls = image_gen.generate_image(prompt, aspect_ratio="9:16", n=1)
            if not urls:
                return text
            block = (f"\n\n---\n\n## 🎬 Thumbnail (Nazareno)\n\n"
                     f"![thumbnail nazareno]({urls[0]})\n")
            return text.rstrip() + block
        except Exception:
            return text
