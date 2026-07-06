---
name: image
description: "Cómo pedir imágenes en el pipeline de Automiq: la línea IMAGEN: con prompt + TEXTO + FORMATO + ESTILO + CAPTION, los 6 estilos visuales y cuándo usar cada uno, la regla de cero texto dentro de la imagen, y el carrusel. Usar siempre que el entregable incluya imágenes para redes o ads."
metadata:
  version: 3.0.0
---

# Imágenes — pipeline Automiq

Vos NO generás la imagen ni llamás a ninguna herramienta. Escribís líneas `IMAGEN:` y el sistema hace el resto (Nano Banana genera el fondo; Pillow compone el titular con tipografía real). Tu trabajo es dar una ESCENA/CONCEPTO específico y elegir bien el ESTILO.

## La línea (una sola línea física, campos con `|`)

```
IMAGEN: <prompt EN INGLÉS del fondo> | TEXTO: <titular corto ES> | SUBTEXTO: <bajada opcional> | FORMATO: <post|historia> | ESTILO: <foto|banner|tipografico|ilustracion|3d|minimal> | CAPTION: <caption completo del post>
```

- El CAPTION es lo que se publica de verdad (hook + cuerpo + CTA + hashtags). Saltos de línea dentro del caption = secuencia literal `\n`, NUNCA Enter.
- Carrusel (máx 1 por corrida): `CARRUSEL: <placa 1> || <placa 2> || <placa 3> | ESTILO: <uno para todas> | CAPTION: ...`

## Los 6 estilos (OBLIGATORIO variar — nunca dos seguidas del mismo)

| Estilo | Qué es | Cuándo |
|---|---|---|
| `foto` | Editorial del rubro: maker real en su depósito/reparto/mostrador, luz natural, plano variado | Historia humana, caso, detrás de escena. La base — pero ya no la única |
| `banner` | Pieza de ad: producto/objeto héroe o fondo potente + aire para el titular | Anuncio de feature, oferta, pieza paid |
| `tipografico` | Fondo color block/gradiente audaz casi vacío; el TITULAR gigante ES la imagen | Dato duro, frase filosa, contrarian. TEXTO obligatorio y corto |
| `ilustracion` | Editorial con textura/grano/risografía, humor o calidez, escenas del rubro | Conceptos: caos→orden, tiempo recuperado, el celular que no para |
| `3d` | Objeto clay/soft-3D del rubro sobre fondo limpio de color, look juguete premium | Features, metáforas de producto |
| `minimal` | UN objeto + muchísimo aire + color inesperado, luz dura | Pattern-interrupt para frenar el scroll |

Elegí por la idea: dato duro → `tipografico` · concepto → `ilustracion` · feature → `banner`/`3d` · historia humana → `foto`.

## Reglas duras

1. **CERO texto dentro de la imagen**: el generador deforma letras y números. Nada de capturas de chat, dashboards, carteles, infografías, "mito vs realidad" como gráfico. El titular lo compone el sistema encima. Pedí `no text, no letters, no numbers, no UI` en el prompt.
2. **TEXTO no siempre**: ~1 de cada 3 piezas va SIN titular (dejá TEXTO vacío) cuando la imagen habla sola; el copy vive en el CAPTION. En `tipografico` nunca lo omitas.
3. **Prompt específico del rubro argentino** (distribuidoras, depósitos, reparto), en inglés, describiendo escena/concepto — no abstracciones ("businessman with laptop") ni clichés IA (robots, cerebros, hologramas, 3D azul genérico).
4. No perfecciones luz/lente: un refinador automático (image-prompt-engineer) lo eleva a nivel pro según el estilo. Vos dale la escena y el estilo correcto.
5. FORMATO: `post` para piezas fuertes, `historia` para efímeras (ratio sano 1 post : 2-3 historias).

## Ejemplos

```
IMAGEN: warehouse owner loading crates into a van at dawn, golden light | TEXTO: Pedidos que se cierran solos | FORMATO: post | ESTILO: foto | CAPTION: ...
IMAGEN: single cardboard box centered on a bold coral background, hard light, lots of empty space | TEXTO: Tu depósito atiende solo | FORMATO: post | ESTILO: minimal | CAPTION: ...
IMAGEN: risograph illustration of a business owner buried under chat bubbles turning into neat ordered boxes | FORMATO: historia | ESTILO: ilustracion
IMAGEN: deep navy to royal blue gradient, subtle film grain, almost empty | TEXTO: 40% de pedidos sin responder | SUBTEXTO: La IA los contesta en 3 segundos | FORMATO: post | ESTILO: tipografico | CAPTION: ...
```
