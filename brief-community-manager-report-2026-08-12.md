┊ review diff
a//app/data/community-manager-report-2026-08-12.md → b//app/data/community-manager-report-2026-08-12.md
@@ -0,0 +1,119 @@
+# CM Automiq — Reporte 2026-08-12 (miércoles, 15:30 -03)
+
+## 1) Resumen de la corrida
+
+- Comentarios nuevos detectados por el vigía: **0**
+- Gates automáticos matcheados: **0**
+- Estado del vigía (`comment-watch.json`): sembrado con 1 comment_id histórico (`18125909227735198`)
+- Significa: el feed está entre publicaciones o no llegó interacción todavía. **No hay nada para responder HOY.**
+- Acción: aprovecho la corrida para dejar armado el **mapa de respuestas de W34**, así cuando entren comentarios con las keywords que content_creator y social_media plantaron, el CM no arranca desde cero.
+
+## 2) Verificación del gate automático (regla de la lección "5+ keywords activas")
+
+Leí `app/integrations/comment_watch.py` línea 26:
+
+```python
+_GATE_WORDS = re.compile(r"\b(demo|story|guia|guía|prompt|checklist|info|quiero)\b", re.IGNORECASE)
+```
+
+**El sistema SOLO auto-clasifica como 🔥 gate si el comentario matchea una de estas 8 palabras exactas.** Todo lo demás queda como comentario normal (sin auto-DM, sin marca de prioridad). Verifiqué las keywords que el equipo plantó en las piezas de W34 y el resultado es crítico:
+
+| Keyword plantada en la pieza | Matchea regex del vigía? | Gate automático | Acción del CM |
+|---|---|---|---|
+| FERRETERA (idea 1, content_creator) | NO | NO | **CM MANUAL** |
+| DEPÓSITO (idea 2, content_creator) | NO | NO | **CM MANUAL** |
+| CHEQUERA (lun post alt, social_media) | NO | NO | **CM MANUAL** |
+| 30DÍAS (jueves surreal alt) | NO | NO | **CM MANUAL** |
+| CTACTE (variante) | NO | NO | **CM MANUAL** |
+| 23:47 (varias piezas) | NO | NO | **CM MANUAL** |
+| VENCIDA (lun alt) | NO | NO | **CM MANUAL** |
+| LUNES (W34 encolado) | NO | NO | **CM MANUAL** |
+| 4700 (W34 encolado) | NO | NO | **CM MANUAL** |
+| REPOSICIÓN (W34 encolado) | NO | NO | **CM MANUAL** |
+| AGOSTO (W34 encolado) | NO | NO | **CM MANUAL** |
+| 6AM (W34 encolado) | NO | NO | **CM MANUAL** |
+| 1047 / PLANILLA / RUTA / DEPÓSITO / AGUINALDO / REPARTO / CIERRE (W33 histórica) | NO (DEPÓSITO es la única que podría matchear si alguien la escribe, pero la regex busca `\b(demo\|story\|...)\b` — DEPÓSITO no está) | NO | **CM MANUAL** |
+| "demo" (en el cuerpo de algunas captions) | SÍ | sí, pero solo si el comentario es exactamente "demo" | edge case |
+
+**Conclusión crítica**: las 14+ keywords activas en las piezas de W34 NO tienen gate automático. Si alguien comenta y el sistema solo lo cuenta como comentario normal sin marca de prioridad, **el CM tiene que responder manualmente o el lead se enfría**. Por la lección aprendida del 2026-08-11, esto era exactamente lo que había que verificar.
+
+NOTA_PARA(content_creator): [objetivo] confirmar si el auto-DM por comment-gate está conectado al webhook de Instagram o si solo es el vigía cada 2h · [dato] el regex de `comment_watch.py:26` solo matchea 8 palabras (demo/story/guia/guía/prompt/checklist/info/quiero) y las 14+ keywords que plantaste en W34 (FERRETERA/DEPÓSITO/CHEQUERA/etc.) no entran en esa lista · [porqué] sin gate automático funcionando, cada comentario con keyword de W34 depende de que el CM responda a mano en las próximas 2h o se pierde como lead.
+
+## 3) Mapa de respuestas W34 (preparado, listo para usar cuando entren comentarios)
+
+### Pieza 1 — content_creator · Idea 1 (editorial, surfa -3,8% PyME)
+- **CTA de la pieza**: "Comentá FERRETERA y te mando por DM los 3 lugares donde una distribuidora típica pierde plata sin notarlo."
+- **Pieza se publica**: lunes 18/8 8:30 (reservado por social_media)
+
+| Si el comentario es… | Tipo | Respuesta pública sugerida | Acción |
+|---|---|---|---|
+| Solo "FERRETERA" | Gate MANUAL (no matchea regex) | "Te lo mando por DM, dale. Contame el rubro y la zona así te paso los 3 lugares ajustados." | DM con mini-auditoría (formato W33). Tag lead tibio. |
+| "FERRETERA me pasó" / "tengo 30 facturas así" / adjunta captura propia del caos | **ALTA INTENCIÓN — NO gate** | "Uff, mirá. Eso tiene arreglo, te lo juro. Te paso mi WhatsApp directo y lo vemos en 15 min." | Escalar a Comercial <2h con nombre + URL del comentario + tag "distribución". |
+| Comentario crítico con la pieza (ej: "eso no le pasa a todas") | Engagement | Responder con el dato duro (CAME -3,8% / 7 meses en baja) + pregunta para profundizar. | Ninguna. |
+| 🔥 / "buenísimo" / emoji solo | Bajo valor | Like + emoji reply. | Ninguna. |
+| Ofensivo o spam | Filtro | Ocultar + reportar. | Ninguna. |
+
+### Pieza 2 — content_creator · Idea 2 (demo chat Corralón García)
+- **CTA de la pieza**: "Comentá DEPÓSITO y te mando por DM una demo del bot cargando los pedidos de TU distribuidora."
+- **Pieza se publica**: miércoles 20/8 12:30
+
+| Si el comentario es… | Tipo | Respuesta pública sugerida | Acción |
+|---|---|---|---|
+| Solo "DEPÓSITO" | Gate MANUAL | "Dale, te paso la demo por DM. Mandame el nombre de tu distribuidora y la zona." | DM con demo grabada. Tag lead tibio. |
+| Comparte pedido propio del mayoreo (ej: "yo tengo clientes que me piden 'lo de siempre'") | **ALTA INTENCIÓN** | "Mirá, ese caso es pan comido para el bot. Te paso mi WhatsApp y lo charlamos." | Escalar a Comercial <2h. |
+| Pregunta técnica ("pero el ERP que tengo es Tango, ¿sirve?") | Pregunta real | "Sí, conectamos con Tango/Bejerman/lo que tengas. Te paso un ejemplo armado con tu caso." | DM con respuesta técnica o derivar a delivery_pm si es duda de implementación. |
+| 🔥 / "qué bueno" | Bajo valor | Like + emoji reply. | Ninguna. |
+
+### Pieza 3 — content_creator · Idea 3 (carrusel BTS distribuidora de Munro)
+- **CTA de la pieza**: "Link en bio · o escribinos por DM"
+- **Pieza se publica**: viernes 22/8 19:00
+- **Tipo**: BTS, sin comment-gate agresivo
+
+| Si el comentario es… | Tipo | Respuesta pública sugerida | Acción |
+|---|---|---|---|
+| "yo tengo una distribuidora de X en Z" | **LEAD DIRECTO** | "Buenísimo. Mandame el nombre y la zona por DM y te armo la demo con tu caso." | DM + tag "lead distribución" + pasar a Comercial. |
+| Pregunta sobre Nazareno o el equipo | Engagement | Responder con nombre real + rol + breve historia. | Ninguna. |
+| Duda sobre ERP o integración | Pregunta técnica | Responder con la lista de ERPs soportados o derivar a delivery_pm. | Según complejidad. |
+| 🔥 / "hermoso laburo" | Bajo valor | Like + "Gracias, dale." | Ninguna. |
+
… omitted 41 diff line(s) across 1 additional file(s)/section(s)
Report guardado. Acá va el entregable completo del CM para hoy:

═══════════════════════════════════════════════════════════════════
CM AUTOMIQ — REPORTE 2026-08-12 (miércoles, 15:30 -03)
═══════════════════════════════════════════════════════════════════

1) RESUMEN DE LA CORRIDA
- Comentarios nuevos: 0
- Gates automáticos: 0
- Estado del vigía (comment-watch.json): sembrado con 1 comment_id histórico
- No hay nada para responder hoy. Aprovecho la corrida para dejar armado el mapa de respuestas de W34 (lección aprendida: cuando hay 0/0, el valor del CM es preparar, no responder).

2) VERIFICACIÓN DEL GATE AUTOMÁTICO (clave del día)

Leí app/integrations/comment_watch.py línea 26:

  _GATE_WORDS = re.compile(r"\b(demo|story|guia|guía|prompt|checklist|info|quiero)\b", re.IGNORECASE)

El sistema SOLO marca 🔥 si el comentario matchea una de esas 8 palabras. Resultado contra las keywords plantadas en W34:

| Keyword plantada | Matchea regex? | Gate automático |
|---|---|---|
| FERRETERA (idea 1 content) | NO | MANUAL |
| DEPÓSITO (idea 2 content) | NO | MANUAL |
| CHEQUERA (lun post alt) | NO | MANUAL |
| 30DÍAS, CTACTE, 23:47, VENCIDA (variantes alt) | NO | MANUAL |
| LUNES, 4700, REPOSICIÓN, AGOSTO, 6AM (W34 encolado) | NO | MANUAL |
| 1047, PLANILLA, RUTA, AGUINALDO, REPARTO, CIERRE (W33 histórica) | NO | MANUAL |

CONCLUSIÓN: las 14+ keywords activas en las piezas de W34 NO tienen gate automático. Si alguien comenta y solo se cuenta como comentario normal sin marca 🔥, el CM tiene que responder manualmente o el lead se enfría. Hoy no había interacción, pero el mapa de abajo ya está listo para que cuando entren las próximas 2h tras publicación, ningún lead se pierda.

3) MAPA DE RESPUESTAS W34 (preparado, ejecutable cuando entren comentarios)

PIEZA 1 — editorial -3,8% PyME (lun 18/8 8:30)
- CTA: "Comentá FERRETERA y te mando por DM los 3 lugares donde una distribuidora típica pierde plata sin notarlo."

| Comentario | Tipo | Respuesta pública | Acción |
|---|---|---|---|
| Solo "FERRETERA" | Gate MANUAL | "Te lo mando por DM, dale. Contame el rubro y la zona." | DM con mini-auditoría + tag lead tibio |
| "FERRETERA me pasó" / foto propia del caos | ALTA INTENCIÓN (no gate) | "Eso tiene arreglo. Te paso mi WhatsApp directo y lo vemos en 15 min." | Escalar a Comercial <2h |
| Crítica con la pieza | Engagement | Responder con dato CAME (-3,8% / 7 meses) + pregunta | Ninguna |
| 🔥 / emoji solo | Bajo valor | Like + emoji reply | Ninguna |
| Ofensivo/spam | Filtro | Ocultar + reportar | Ninguna |

PIEZA 2 — demo chat Corralón García (mié 20/8 12:30)
- CTA: "Comentá DEPÓSITO y te mando por DM una demo del bot cargando los pedidos de TU distribuidora."

| Comentario | Tipo | Respuesta pública | Acción |
|---|---|---|---|
| Solo "DEPÓSITO" | Gate MANUAL | "Dale, te paso la demo. Mandame nombre y zona." | DM + tag lead tibio |
| Comparte pedido propio del mayoreo | ALTA INTENCIÓN | "Pan comido para el bot. Te paso mi WhatsApp." | Escalar a Comercial <2h |
| Pregunta técnica ("tengo Tango, ¿sirve?") | Pregunta real | "Sí, conectamos con Tango/Bejerman. Te paso un ejemplo." | DM técnica o derivar a delivery_pm |
| 🔥 / "qué bueno" | Bajo valor | Like + emoji reply | Ninguna |

PIEZA 3 — carrusel BTS distribuidora Munro (vie 22/8 19:00)
- CTA: "Link en bio · o escribinos por DM"

| Comentario | Tipo | Respuesta pública | Acción |
|---|---|---|---|
| "Yo tengo una distribuidora de X en Z" | LEAD DIRECTO | "Mandame nombre y zona por DM y te armo la demo con tu caso." | DM + tag "lead distribución" + Comercial |
| Pregunta sobre Nazareno/equipo | Engagement | Nombre real + rol + breve historia | Ninguna |
| Duda sobre ERP/integración | Pregunta técnica | Lista de ERPs soportados o derivar | Según complejidad |
| 🔥 / "hermoso laburo" | Bajo valor | Like + "Gracias, dale." | Ninguna |

PIEZA W34 ALTERNATIVA (social_media) — chequera La Matanza
- CTAs: CHEQUERA / 30DÍAS / CTACTE / 23:47 / VENCIDA

| Comentario | Tipo | Respuesta pública | Acción |
|---|---|---|---|
| "CHEQUERA" | Gate MANUAL | "Te mando el flujo por DM. Decime nombre y zona." | DM + tag lead tibio |
| Foto propia de talonario/facturas vencidas | ALTA INTENCIÓN | "Lo resolvemos en 15 min. Te paso mi WhatsApp." | Escalar a Comercial <2h |
| "30DÍAS" / "CTACTE" / "23:47" / "VENCIDA" | Gate MANUAL variante | "Te paso la demo. Contame nombre y zona." | DM + tag lead tibio |

4) OPORTUNIDADES DETECTADAS
- Hoy: ninguna (0 comentarios).
- Próxima corrida con interacción real: lunes 17/8 en adelante. Mapa ya armado.

5) PULSO DE LA COMUNIDAD
- Vacío hoy. Cuando entren los primeros comentarios de W34 voy a medir:
  * Tasa de keyword vs. comentario libre
  * Volumen de "alta intención" vs. solo keyword
  * Sentimiento sobre vertical distribución en comentarios propios y del nicho (Agentsapp, Duotach, Galo AI)

6) PENDIENTES (no repetir como hallazgo nuevo)
- 81f84889 [humano] Sigue abierto: si la idea 2 se publica con "Corralón García · Bahía Blanca" real, el CM necesita instrucción sobre cómo responder si alguien comenta "yo te conozco" o "ese es mi proveedor" — no podemos exponer datos de un cliente real.
- 9f0fca65 [web] Sin Meta Pixel + GA4 + /gracias — no impactó al CM hoy (no hubo interacción) pero si llega el primer DM con keyword no podemos medir atribución.

7) NOTAS PARA EL EQUIPO

NOTA_PARA(content_creator): [objetivo] alinear el mapeo de keywords con el regex del vigía · [dato] las 14+ keywords plantadas en W34 (FERRETERA/DEPÓSITO/CHEQUERA/30DÍAS/CTACTE/23:47/VENCIDA/LUNES/4700/REPOSICIÓN/AGOSTO/6AM) NO matchean la regex de comment_watch.py:26, que solo cubre demo/story/guia/guía/prompt/checklist/info/quiero · [porqué] o cambiamos a keywords que sí matcheen (ej: "demo" en todas, ya probó convertir) o documentamos como MANUAL en el CM para que ninguna se pierda en las próximas 2h. Sin esto, las próximas corridas con interacción real se nos cuelan leads tibios sin marca 🔥.

LECCION: cuando el equipo rota keywords para no quemar el feed (FERRETERA/DEPÓSITO/CHEQUERA en vez de "demo"), pero la regex del vigía solo matchea 8 palabras genéricas, el efecto combinado es que las keywords rotadas NO tienen gate automático y dependen 100% de respuesta manual del CM en <2h. La rotación protege el feed pero rompe el auto-DM. Hay que decidir: keywords rotadas + CM manual sólido, o keywords fijas tipo "demo" + gate automático. Hoy la casa está en la primera — lo explicito para que content_creator lo sepa al elegir las próximas piezas.

═══════════════════════════════════════════════════════════════════

Reporte guardado en /app/data/community-manager-report-2026-08-12.md (10,3 KB).
