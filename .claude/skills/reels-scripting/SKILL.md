---
name: reels-scripting
description: "Reglas de guion para reels/TikToks de Automiq: hook en 3s, 2 puntos máximo, 30-45s, caption espejo, trigger de comentario, QA de 95/100. Usar al escribir cualquier guion de video corto. Corre headless: el material de referencia viene INYECTADO en el prompt (playbook, espía, baúl de ganchos) — no scrapees nada ni esperes input de un usuario."
metadata:
  version: 2.0.0
---

# Guion de Reels/TikToks — Automiq

Corrés headless: NO hay usuario para preguntarle, NO scrapees reels (las IPs de datacenter están bloqueadas) y NO necesitás herramientas externas. Tu referencia es el material que ya viene inyectado en el prompt: el playbook de competencia, el visual scout, el espía y el BAÚL DE GANCHOS. Usalos.

## Referencia (en vez de scrapear)

1. Elegí del BAÚL DE GANCHOS o de los hooks del playbook la estructura que mejor calce con el tema.
2. Copiá la ESTRUCTURA (largo del hook, ritmo, dónde va la demo), no las palabras.
3. Nunca inventes métricas de referencia; si citás un dato del playbook, citalo tal cual.

## Reglas del guion (no negociables)

### Hook (0-3s)
- Nunca abrir con "yo". Abrí con "esto", "vos", un dato o un nombre.
- Formatos probados: "Esto cambió X para siempre" / flip negativo ("X no sirve si no...") / pregunta de dolor concreto / resultado primero (mostrar el bot contestando ANTES de explicar).
- El hook crea curiosidad o corta el patrón en 3 segundos. Texto grande en pantalla desde el frame 0.

### Cuerpo
- Español rioplatense hablado natural (vos, decí, mirá). Frases cortas. Una idea por video.
- **2 puntos clave máximo, no 3.** 30-45 segundos total leído en voz alta.
- Nunca declares la conclusión: que los hechos la digan.
- La demo del bot NUNCA sola y pelada: sobrepuesta abajo (card), inset o cutaway mientras la persona habla ("mirá lo que contesta acá abajo").
- Nada de "link en bio": usá trigger de comentario.

### Trigger de comentario
- UNA palabra en mayúsculas (BOT, DEMO, GUIA). Directamente relacionada con lo prometido. Sin comillas ni puntuación.

### CTA
- "Comentá [PALABRA] y te mando [cosa específica]". Corto, sin relleno.

### Caption
- Espeja el guion (hook + promesa + CTA + hashtags de nicho: #automatizacionIA #pymesarg — nunca #fyp/#parati). Guion y caption se actualizan juntos.

## Estructura del entregable

```
# Reel: [título]
## Hook (0-3s)
[palabras exactas]
## Punto 1 ([inicio]-[fin]s)
[palabras exactas + qué se ve en pantalla]
## Punto 2 ([inicio]-[fin]s)
[palabras exactas + qué se ve en pantalla]
## CTA ([inicio]-[fin]s)
[palabras exactas con "Comentá [PALABRA]"]
## Caption
[espejo del guion]
## Trigger
[PALABRA] → [qué desbloquea]
## Notas visuales
[cortes, b-roll, carteles, dónde entra la demo]
```

## QA (gate de 95/100)

Antes de entregar, puntuá el guion contra las reglas y corregí TODA violación. Chequeos típicos: abre con "yo" · 3 puntos en vez de 2 · declara la conclusión · trigger de varias palabras · +45s leído en voz alta · caption no espeja el guion · demo pelada a pantalla completa. No entregues nada por debajo de 95.
