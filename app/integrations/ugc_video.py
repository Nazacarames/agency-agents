"""
ugc_video — genera videos estilo UGC (User-Generated Content) con IA: un "cliente" real
(dueño de PyME argentino) filmándose EN EL CELU contando su experiencia con un bot de IA.
Auténtico, no publicidad. Complementa la marca personal de Nazareno (que es un presentador
fijo); acá la gracia es la VARIEDAD de personas y la estética casera/creíble.

Reusa Veo (veo_video) SIN reference images a propósito → cada video una persona distinta
(como testimonios reales de clientes diferentes). Best-effort: si Veo no está, devuelve None.
"""
from __future__ import annotations

import base64
import random
import uuid
from pathlib import Path
from typing import Optional

from ..log import get_logger

log = get_logger("ugc_video")

# Personas = clientes/dueños de PyME argentinos VARIADOS (edad/género/rubro distintos →
# testimonios diversos y creíbles). El rubro ancla la escena real.
PERSONAS = [
    "una mujer de unos 42 años, dueña de un kiosco de barrio, parada en el mostrador con golosinas y la heladera de bebidas atrás",
    "un hombre de unos 50 años, dueño de una distribuidora, en su depósito con estanterías llenas de cajas y mercadería",
    "un joven de unos 30 años, dueño de una ferretería, entre estanterías con herramientas y tornillería",
    "una mujer de unos 35 años, dueña de un local de indumentaria, entre percheros con ropa",
    "un hombre de unos 45 años, dueño de un corralón de materiales, con bolsas de cemento y maderas atrás",
    "una mujer de unos 28 años, emprendedora que vende por Instagram, en su casa con los productos apilados en una mesa",
    "un hombre de unos 38 años, dueño de una rotisería, detrás del mostrador con la comida en exhibición",
    "una mujer de unos 48 años, dueña de una farmacia de barrio, detrás del mostrador con las góndolas atrás",
]

# Negativo: que NO se vea publicidad ni estudio; que se sienta grabado con el celular.
_UGC_NEG = ("aspecto de publicidad, estudio de fotografía, iluminación profesional, cámara de cine, "
            "modelo, catálogo de moda, fondo desenfocado excesivo, texto en pantalla, subtítulos, "
            "logos, manos deformes, dedos extra, acento neutro, acento mexicano, acento español de España")


def enabled() -> bool:
    try:
        from . import veo_video
        return veo_video.enabled()
    except Exception:
        return False


def ugc_veo_prompt(frase: str, persona: str) -> str:
    """Prompt de Veo con estética UGC: selfie/celu, casero, auténtico, hablado natural."""
    return (
        f"Video vertical 9:16 estilo UGC (contenido de usuario real), grabado con la cámara "
        f"frontal de un celular a la distancia del brazo, sostenido a mano con un leve temblor "
        f"natural. {persona.capitalize()}. Luz natural disponible del lugar (no profesional), "
        f"aspecto realista y casero, NADA de estética de publicidad ni estudio. "
        f"Le habla directo a la cámara como si le contara a un amigo, con naturalidad y una "
        f"sonrisa, en español rioplatense con acento porteño argentino natural. Dice la frase "
        f"completa UNA SOLA VEZ, sin repetir ni trabarse: \"{frase.strip()}\". "
        f"Gesticula con naturalidad, mira a la cámara. Se ve el lugar real de trabajo alrededor."
    )


def generate(frase: str, persona: Optional[str] = None,
             lugar_hint: Optional[str] = None) -> Optional[str]:
    """Genera un clip UGC (Veo, persona variada, sin reference). Devuelve path local o None."""
    if not enabled() or not (frase or "").strip():
        return None
    try:
        from . import veo_video, omni_video
        p = persona or random.choice(PERSONAS)
        # Omni primero (mejor dicción/acento; persona variada sin reference);
        # preview → fallback a Veo si falla o filtra.
        res = omni_video.generate_and_wait(
            ugc_veo_prompt(frase, p), negative_prompt=_UGC_NEG, timeout_s=300)
        if not res.get("b64"):
            res = veo_video.generate_and_wait(
                ugc_veo_prompt(frase, p), aspect_ratio="9:16",
                negative_prompt=_UGC_NEG, timeout_s=300, poll=12)
        b64 = res.get("b64")
        if not b64:
            return None
        d = Path(__file__).resolve().parent.parent.parent / "data" / "images"
        d.mkdir(parents=True, exist_ok=True)
        fname = f"ugc_{uuid.uuid4().hex}.mp4"
        (d / fname).write_bytes(base64.b64decode(b64))
        log.info("ugc_clip_ok", file=fname)
        return str(d / fname)
    except Exception as e:
        log.warning("ugc_generate_failed", error=str(e)[:200])
        return None
