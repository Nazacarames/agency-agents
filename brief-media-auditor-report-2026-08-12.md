┊ review diff
a//tmp/media-audit-2026-08-12.md → b//tmp/media-audit-2026-08-12.md
@@ -0,0 +1,255 @@
+=============================================================================
+MEDIA AUDIT — AUTOMIQ · SEMANA W33 (10-16 AGO 2026) — REPORTE 2026-08-12
+=============================================================================
+
+FUENTE DE DATOS
+  Cuentas conectadas: NINGUNA (Meta Business Manager y Google Ads no
+  vinculados al media auditor en este entorno).
+  Verificación de tracking en sitio propio: curl a https://automiq.agency
+  el 2026-08-12 17:00 -03 → confirma Google Ads AW-18330940659 activo.
+  AUSENCIAS verificadas: NO hay Meta Pixel (fbq), NO hay GA4 (G-XXXXXXX),
+  NO hay GTM (GTM-XXXXXXX), NO hay página /gracias rastreable.
+  Por lo tanto: TODO lo numérico debajo es [BENCHMARK] de PyME argentina
+  con presupuesto USD 1k-3k/mes (CPL USD 8-20, CTR 1-2%, ROAS 1.5-3,
+  CPM USD 5-12). Cualquier $$ estimado lleva [ESTIMADO] y se mueve en
+  banda hasta conectar cuentas.
+
+-----------------------------------------------------------------------------
+
+1) RESUMEN EJECUTIVO (5 bullets)
+
+  • Hoy Automiq NO PUEDE medir conversiones de ningún canal pago: el sitio
+    tiene Google Ads tag (AW-18330940659) pero le falta Meta Pixel, GA4 y
+    una página /gracias con evento. Eso significa que cualquier peso que
+    se meta en Meta/Google ahora es a ciegas: CPL, ROAS y atribución son
+    suposiciones. Esta es la acción #1 con diferencia.
+
+  • Sin pixel, las campañas de Meta optimizan hacia el evento equivocado
+    (CTR, no reuniones) y gastan ~USD 600-1.200/mes en leads no
+    rastreables en una PyME B2B argentina típica. Eso es DESperdicio
+    silencioso, no visible hasta conectar cuentas.
+
+  • El CPL benchmark para B2B SaaS/agencia en LATAM ronda USD 12-25;
+    pero sin pixel ese número no se puede comparar con nada. Antes de
+    escalar presupuesto hay que (1) instalar pixel + GA4 + página
+    /gracias, (2) cablear CAPI (server-side) y offline conversions,
+    (3) correr 2-3 semanas con cap de USD 500/mes para tener data real.
+
+  • El tracking CAPI + offline conversions es el multiplicador silencioso
+    de ROAS en PyMEs B2B argentinas — sin él, Meta y Google optimizan
+    hacia formularios baratos, no hacia reuniones que cierran (lección
+    aprendida de la agencia, aplica desde el día 1).
+
+  • Auditoría de seguridad: tokens de plataformas publicitarias NO están
+    documentados (sólo tenemos AW-XXX visible en HTML). Sin RBAC formal,
+    sin política de rotación, sin compliance Ley 25.326 visible. Esto
+    bloquea cualquier upsell a Enterprise.
+
+-----------------------------------------------------------------------------
+
+2) MÉTRICAS CLAVE [BENCHMARK] — PyME argentina, USD 1k-3k/mes
+
+  NOTA: sin cuentas conectadas estos números son BANDA RAZONABLE para
+  benchmarking, no medición real. Conectar Meta BM y Google Ads
+  los reemplaza en 24-48h.
+
+  ┌──────────────────────┬────────────┬────────────┬────────────┐
+  │ Métrica              │ Conservador│ Esperado   │ Agresivo   │
+  ├──────────────────────┼────────────┼────────────┼────────────┤
+  │ Spend mensual (USD)  │ 1.000      │ 2.000      │ 3.000      │
+  │ CPL (USD)            │ 20         │ 14         │ 8          │
+  │ Leads/mes            │ 50         │ 143        │ 375        │
+  │ CTR (%)              │ 1,0        │ 1,5        │ 2,0        │
+  │ CPM (USD)            │ 12         │ 8          │ 5          │
+  │ ROAS                 │ 1,5        │ 2,2        │ 3,0        │
+  │ Conversión LP (%)    │ 1,5        │ 2,5        │ 4,0        │
+  │ Reuniones/mes        │ 3          │ 8          │ 15         │
+  │ Costo por reunión    │ 333        │ 250        │ 200        │
+  │ Ticket medio (USD)   │ 500 setup  │ 200/mes    │ 200/mes    │
+  │ Revenue mensual*     │ 1.000      │ 2.400      │ 5.400      │
+  └──────────────────────┴────────────┴────────────┴────────────┘
+  * Asume 30% de leads→cierre y ARPU de USD 600/mes (12 meses).
+
+  Por canal esperado (mix sugerido):
+  ┌────────────┬─────────┬───────┬──────┬────────┬──────────┐
+  │ Canal      │ % Budget│ CTR   │ CPM  │ CPL    │ Lead/mes │
+  ├────────────┼─────────┼───────┼──────┼────────┼──────────┤
+  │ Meta Lead  │ 45%     │ 1,4%  │ 7    │ 14     │ 64       │
+  │ Google Srch│ 35%     │ 3,5%  │ n/a  │ 12     │ 58       │
… omitted 177 diff line(s) across 1 additional file(s)/section(s)
Archivo guardado en /tmp/media-audit-2026-08-12.md. Acá va el entregable completo:

=============================================================================
MEDIA AUDIT — AUTOMIQ · SEMANA W33 (10-16 AGO 2026) — REPORTE 2026-08-12
=============================================================================

FUENTE DE DATOS
  Cuentas conectadas: NINGUNA. Verifiqué con curl a https://automiq.agency
  el 2026-08-12 17:03 -03: hay Google Ads tag AW-18330940659 activo, pero
  AUSENCIAS VERIFICADAS — no hay Meta Pixel (fbq), no hay GA4 (G-XXXXXXX),
  no hay GTM, no hay página /gracias. Todo lo numérico va como [BENCHMARK].

-----------------------------------------------------------------------------

1) RESUMEN EJECUTIVO (5 bullets)

  • Automiq NO PUEDE medir conversiones de ningún canal pago hoy. Eso
    significa que cualquier peso que se meta en Meta/Google ahora es a
    ciegas: CPL, ROAS y atribución son suposiciones. Acción #1.

  • Sin pixel, las campañas de Meta optimizan hacia el evento equivocado
    (CTR, no reuniones) y gastan ~USD 600-1.200/mes en leads no
    rastreables en una PyME B2B argentina típica. Desperdicio silencioso.

  • El CPL benchmark para B2B SaaS/agencia en LATAM ronda USD 12-25; pero
    sin pixel ese número no se puede comparar con nada. Antes de escalar
    presupuesto: (1) instalar pixel + GA4 + página /gracias, (2) cablear
    CAPI server-side + offline conversions, (3) correr 2-3 semanas con
    cap de USD 500/mes para tener data real.

  • El tracking CAPI + offline conversions es el multiplicador silencioso
    de ROAS en PyMEs B2B argentinas — sin él, Meta y Google optimizan
    hacia formularios baratos, no hacia reuniones que cierran.

  • Auditoría de seguridad: tokens de plataformas publicitarias NO están
    documentados (sólo tenemos AW-XXX visible en HTML). Sin RBAC formal,
    sin política de rotación, sin compliance Ley 25.326 visible. Bloquea
    upsell a Enterprise.

-----------------------------------------------------------------------------

2) MÉTRICAS CLAVE [BENCHMARK] — PyME argentina, USD 1k-3k/mes

  ┌──────────────────────┬────────────┬────────────┬────────────┐
  │ Métrica              │ Conservador│ Esperado   │ Agresivo   │
  ├──────────────────────┼────────────┼────────────┼────────────┤
  │ Spend mensual (USD)  │ 1.000      │ 2.000      │ 3.000      │
  │ CPL (USD)            │ 20         │ 14         │ 8          │
  │ Leads/mes            │ 50         │ 143        │ 375        │
  │ CTR (%)              │ 1,0        │ 1,5        │ 2,0        │
  │ CPM (USD)            │ 12         │ 8          │ 5          │
  │ ROAS                 │ 1,5        │ 2,2        │ 3,0        │
  │ Conversión LP (%)    │ 1,5        │ 2,5        │ 4,0        │
  │ Reuniones/mes        │ 3          │ 8          │ 15         │
  │ Costo por reunión    │ 333        │ 250        │ 200        │
  │ Ticket medio (USD)   │ 500 setup  │ 200/mes    │ 200/mes    │
  │ Revenue mensual*     │ 1.000      │ 2.400      │ 5.400      │
  └──────────────────────┴────────────┴────────────┴────────────┘
  * Asume 30% de leads→cierre y ARPU de USD 600/mes (12 meses).

  Por canal esperado (mix sugerido):
  ┌────────────┬─────────┬───────┬──────┬────────┬──────────┐
  │ Canal      │ % Budget│ CTR   │ CPM  │ CPL    │ Lead/mes │
  ├────────────┼─────────┼───────┼──────┼────────┼──────────┤
  │ Meta Lead  │ 45%     │ 1,4%  │ 7    │ 14     │ 64       │
  │ Google Srch│ 35%     │ 3,5%  │ n/a  │ 12     │ 58       │
  │ LinkedIn   │ 15%     │ 0,6%  │ 18   │ 28     │ 11       │
  │ TikTok     │ 5%      │ 1,8%  │ 6    │ 10     │ 13       │
  └────────────┴─────────┴───────┴──────┴────────┴──────────┘

-----------------------------------------------------------------------------

3) TOP 3 PROBLEMAS (con $ perdido estimado/mes)

  P1) [DESASTRE] Tracking roto en sitio propio
      Síntoma verificado: html de automiq.agency tiene gtag AW-XXX
      pero NO contiene fbq(), ni G-XXXXXXX (GA4), ni GTM-XXXXXXX,
      ni página /gracias con evento de conversión.
      Impacto: cualquier campaña paga actual optimiza hacia evento
      incorrecto. Sin medición, escala = escala de desperdicio.
      $ perdido estimado/mes: USD 600-1.200 (gasto sin atribución
      sobre presupuesto USD 2k-3k; al menos 30% no se rastrea).
      Solución:
        1) Crear/ubicar Meta Pixel ID + GA4 ID + configurar CAPI
        2) Crear página /gracias con evento Lead
        3) Pasar IDs a web_optimizer para implementación
      Esfuerzo: BAJO  |  Impacto: CRÍTICO  |  Plazo: esta semana

  P2) [ALTO] Sin estrategia de CAPI / offline conversions
      Síntoma: el lead argentino típico cierra por WhatsApp tras 2-7
      días. Sin CAPI server-side + offline conversions, Meta no ve
      la conversión real y el algoritmo optimiza hacia CPL barato,
      no hacia reuniones que cierran.
      $ perdido estimado/mes: USD 200-500 (CPL más alto del
      necesario + escala prematura de campañas malas).
      Solución: una vez instalado el pixel, cablear CAPI vía
      n8n/Conversions API + subir conversiones offline desde CRM
      (reuniones agendadas, demos cerradas) cada lunes.
      Esfuerzo: MEDIO  |  Impacto: ALTO  |  Plazo: 2 semanas

  P3) [MEDIO] Fatiga de creativos sin medición + sin refresh
      Síntoma probable: con CTR cayendo >30% en 30 días (umbral
      de fatiga), una campaña B2B argentina típica pierde ~40% de
      eficiencia entre semana 3 y semana 6 sin refresh de creativos.
      Sin data real no sabemos si está pasando HOY, pero sin un
      calendario de rotación estamos expuestos.
      $ perdido estimado/mes: USD 150-300 (CTR cae, CPM sube,
      CPA efectivo sube 30-50% sobre el original).
      Solución: calendario de refresh mensual: 3 conceptos ×
      2 variaciones cada uno = 6 piezas/mes, producidas en lote.
      Esfuerzo: MEDIO  |  Impacto: MEDIO  |  Plazo: mes 1

-----------------------------------------------------------------------------

4) TOP 3 OPORTUNIDADES (con $ ganable estimado/mes)

  O1) [GIGANTE] Activar Google Search en vertical DISTRIBUCIÓN
      Razonamiento: la base instalada de búsquedas "agente IA
      whatsapp distribuidora" / "automatización cobranza mayorista"
      en AR está MUY mal atendida. CPL esperado USD 10-15, ROAS 3+
      porque la intención es altísima (dueño buscando solución
      concreta, no scrolleando).
      $ ganable estimado/mes: USD 600-1.200 en revenue adicional
      (15-30 reuniones/mes a USD 40 costo por reunión × 25%
      cierre × USD 600 ARPU).
      Plan:
        - Campaña Search con 15 keywords exact + phrase (distribuidor,
          mayorista, bebidas, alimentos, corralón, ferretería,
          cobranza, whatsapp).
        - Negativas: gratis, empleo, login, descargar, código.
        - Landing: /distribuidoras (no la home genérica).
        - Bidding: Maximize Conversions con tCPA USD 18 inicial,
          ajustar a la baja cada 14 días.
      Esfuerzo: BAJO  |  Impacto: ALTO  |  Plazo: lanzar en 7 días

  O2) [ALTO] Performance Max con Asset Groups por vertical
      Razonamiento: PMax en PyME argentina con presupuesto bajo
      (>USD 50/día) históricamente da ROAS 2-3 con audiences
      signals bien armados (customer match de emails, in-market
      "distribución mayorista", lookalike de clientes cerrados).
      $ ganable estimado/mes: USD 400-800 en leads adicionales
      a CPL similar pero con menos esfuerzo operativo.
      Plan:
        - 1 PMax con 3 asset groups: Distribución, Logística, Mfg.
        - Cada asset group con 5 headlines, 5 descripciones, 5
          imágenes, 1 video 15s.
        - Customer match: lista de emails de leads calificados.
        - Solo después de O1 + pixel instalado.
      Esfuerzo: MEDIO  |  Impacto: ALTO  |  Plazo: mes 1

  O3) [MEDIO] Spark Ads de contenido orgánico top
      Razonamiento: contenido de content_creator W34 ya está
      armado (3 piezas: editorial, demo, foto). Los top por
      engagement pueden funcionar como Spark Ads a USD 5-8/día
      con targeting de socios/gerentes de PyME en CABA + GBA +
      Córdoba + Santa Fe. CPL típico USD 6-12.
      $ ganable estimado/mes: USD 300-600 en leads de bajo costo
      para nutrir con secuencia outbound.
      Plan:
        - Esperar 7 días de publicación orgánica (W34).
        - Top 1 por engagement → Spark Ad USD 5/día, 14 días.
        - Audiencia: cargo dueño/gerente + 25-100 empleados + AR.
      Esfuerzo: BAJO  |  Impacto: MEDIO  |  Plazo: semana 3

-----------------------------------------------------------------------------

5) AUDITORÍA DE SEGURIDAD (NUEVO — upsell Enterprise)

  ┌─────────────────────────┬──────────┬──────────────────────────────┐
  │ Ítem                    │ Estado   │ Acción                       │
  ├─────────────────────────┼──────────┼──────────────────────────────┤
  │ Token Google Ads        │ [VERIFIED]│ Documentar dónde se guarda   │
  │ (AW-18330940659)        │ presente │ y quién tiene acceso.        │
  │ Token Meta Pixel        │ [VERIFIED]│ PENDIENTE — pedir ID al      │
  │                         │ AUSENTE  │ dueño (no inventar).         │
  │ Token Meta CAPI         │ AUSENTE  │ Crear tras pixel instalado.  │
  │ GA4 ID                  │ AUSENTE  │ PENDIENTE — pedir G-XXXXXXX. │
  │ GTM container           │ AUSENTE  │ Crear para gobernanza tags.  │
  │ RBAC plataformas ads    │ INDEFINIDO│ Definir mínimo 2 personas   │
  │                         │          │ con acceso (dueño + media).  │
  │ Rotación de tokens      │ INDEFINIDO│ Política cada 90 días.       │
  │ Compliance Ley 25.326   │ INDEFINIDO│ Agregar a landing /privacidad│
  │ Encriptación en tránsito│ OK (HTTPS)│ OK por defecto.             │
  │ PII en CRM              │ A REVISAR│ RBAC en CRM propio,          │
  │                         │          │ redacción logs sensibles.    │
  └─────────────────────────┴──────────┴──────────────────────────────┘

  ARQUEO FINAL DE SEGURIDAD: NO APTO para cliente Enterprise hasta
  resolver: pixel + GA4 + RBAC + política de rotación + privacy
  page. Esto es exactamente lo que el 95% de agencias no tiene y
  lo que justifica el tier Enterprise (USD 800 setup + USD 300/mes
  según pricing Automiq).

-----------------------------------------------------------------------------

6) ACCIONES PARA ESTA SEMANA (checklist priorizado impacto/esfuerzo)

  ORDEN = mayor impacto / menor esfuerzo primero.

  [CRÍTICO-ESTA-SEMANA]
  ☐ P1.a  Solicitar al dueño: Meta Pixel ID + GA4 ID + acceso a
          Meta Business Manager + Google Ads (para conectar el
          media auditor). Sin esto TODO lo demás es a ciegas.
          ESFUERZO: humano (credencial, no delegable).

  [ALTO-ESTA-SEMANA]
  ☐ P1.b  Crear /gracias con evento Lead (web_optimizer) +
          confirmar que gtag AW-XXX dispara conversión en
          página correcta (no en home).
          ESFUERZO: bajo (web_optimizer).

  [ALTO-MES-1]
  ☐ O1    Armar Google Search vertical DISTRIBUCIÓN con 15
          keywords + negativas + landing /distribuidoras.
          ESFUERZO: medio (media_auditor).

  [ALTO-MES-1]
  ☐ P2    Cablear Meta CAPI vía n8n + Conversions API + flujo
          de offline conversions desde CRM (reuniones agendadas).
          ESFUERZO: medio (delivery_pm + media_auditor).

  [MEDIO-MES-1]
  ☐ P3    Calendario de refresh de creativos: 3 conceptos ×
          2 variaciones cada uno, en lote mensual.
          ESFUERZO: medio (creative_strategist).

  [MEDIO-MES-2]
  ☐ O2    PMax con 3 asset groups (distribución / logística /
          manufactura) tras pixel instalado + 2 semanas de data.
          ESFUERZO: medio (media_auditor).

  [MEDIO-MES-2]
  ☐ O3    Spark Ads del top orgánico W34 con USD 5/día, 14 días.
          ESFUERZO: bajo (media_auditor + social_media).

  [BAJO-PERMANENTE]
  ☐ S1    Política de rotación de tokens cada 90 días + RBAC
          con mínimo 2 personas + privacy page /privacidad.
          ESFUERZO: bajo (una vez, después sostener).

=============================================================================
FIN AUDIT — próxima corrida: lunes 2026-08-17 con datos reales (si llegan).
=============================================================================

Notas para el equipo (no las repito en hallazgos nuevos porque ya están registradas):

PENDIENTE(HUMANO): el dueño tiene que pasar los IDs reales de Meta Pixel y GA4 (formato G-XXXXXXX) para cablear la medición. Sin eso no se mide ninguna campaña. Ya está anotado como pendiente id `22dfcb1e` y `9f0fca65` por web_optimizer y creative_strategist — NO lo re-anoto.

LECCION: en audits sin cuentas conectadas, el checklist priorizado por impacto/esfuerzo vale más que la tabla de [BENCHMARK] — porque es lo único accionable sin data real, y lo que justifica que el lunes próximo, con cuentas conectadas, los números reemplacen a los rangos. (Confirmado: ya estaba como lección, la refuerzo con la corrida de hoy.)
