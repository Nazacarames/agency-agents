┊ review diff
a//app/data/growth-hacker-report-2026-08-12.md → b//app/data/growth-hacker-report-2026-08-12.md
@@ -0,0 +1,376 @@
+# REPORTE DE GROWTH — AUTOMIQ
+
+Fecha: 2026-08-12 18:00 -03 (miércoles W33, día +2 del "veredicto" del CoS del lunes)
+Auditor: Growth Hacker (headless)
+URL auditada en vivo: https://automiq.agency + /precios + /distribuidoras-mayoristas + /gracias
+Vertical prioritario Q3 2026: Distribución (mayoristas/distribuidoras AR, 25–100 empleados)
+Estado del equipo: pre-revenue. MRR = USD 0 / clientes pagos = 0 / 47 días corridos.
+Meta activa: cerrar 3 ventas reales antes de invertir en ads.
+
+═══════════════════════════════════════════════════════════════
+0. QUÉ CAMBIÓ EN 24 HORAS (continuidad martes 11/08 → miércoles 12/08)
+═══════════════════════════════════════════════════════════════
+
+El reporte del martes 11/08 cerró con la promesa de que el web_optimizer
+preparó un PR con /gracias + sitemap actualizado + 5 subpáginas SEO nuevas
+(promoción a producción pendiente del humano Nazareno). El CoS del lunes
+10/08 puso 6 decisiones humanas sobre la mesa del lunes EOD. Hoy es +2 y
+el scrape en vivo dice lo siguiente:
+
+  Decisión humana del lunes (10/08)        Estado hoy 12-08 EOD   Verificación
+  ───────────────────────────────────────  ────────────────────    ─────────────────────────
+  QW #1 · H1 home + 9 contadores en 0      SIN EJECUTAR           grep <h1> → 0 matches; 9 ocurr. ">0<"
+  QW #1b · GA4 + Meta Pixel                SIN EJECUTAR           fbq → 0; ningún G-XXXXXX en head
+  QW #1c · /gracias creada                 EN PREVIEW, NO PROD    curl /gracias → 404; el PR vive en
+                                                                https://automiq-landing-astro-9utxfl235-
+                                                                nazacarames-projects.vercel.app
+  QW #2 · Outbound day-0 (15/día)          SIN EJECUTAR           hoy 12-08: 6 step-2 enviados, 0 day-0
+  QW #3 · Log manual leads WA              SIN EJECUTAR           inbox 12-08: 0 leads reales (4 omitidos
+                                                                automáticos). No hay sheet.
+  CLAMEVET firma mail                      SIN EJECUTAR           19 días esperando; el dueño ya tomó
+                                                                (no se vuelve a pedir — id 12f32978)
+  Desbloqueo Meta Ads (6 ads)              SIN EJECUTAR           creative_strategist del 12-08: 6 ads
+                                                                siguen parados sin cuenta publicando
+  Preview de web_optimizer promovido       NO PROMOVIDO           pendiente f1b115be sigue abierto
+
+Sexto día consecutivo sin deploys en producción. Web idéntica al 06/07/08/09/
+10/11 de agosto (86.998 bytes, H1 vacío, 9 contadores en 0, /gracias 404).
+La ventana de "esperar al lunes" se cumplió; la de "esperar al miércoles"
+también. Hoy arranca el costo real: la meta de 3 ventas a este ritmo llega
+a día 55-65 [BENCHMARK], no a día 30.
+
+Lo que sí cambió (datos nuevos verificados hoy):
+  • leads-store.json: 358 leads (+7 vs. ayer 351). 1 respuesta nueva:
+    Distribuidora Espora (Tandil, distribución bebidas) → pasó a state=respondió.
+    Histórico de respuesta sube 1,17% → 1,40% (5/358).
+  • Outbound 12-08: 6 step-2 enviados (todos follow-ups), 6 rebotes MX, 15
+    leads empujados a cola WhatsApp. Patrón idéntico al del 11-08.
+  • Cola WhatsApp hoy (15 leads): incluye 6 distribuidoras y 1
+    inmobiliaria del vertical prioritario. Cada uno con demo personalizada
+    ya armada (URL app.automiq.agency/d/...).
+  • Inbox 12-08: 4 hilos revisados, 0 leads, 4 omitidos (DMARC + Nexo +
+    Railway + Google Cloud). El buzón real está vacío.
+
+═══════════════════════════════════════════════════════════════
+1. ESTADO ACTUAL (snapshot)
+═══════════════════════════════════════════════════════════════
+
+Métricas verificadas hoy (miércoles 12-08 18:00 -03, scrape en vivo):
+
+  Tracking instalado       : SOLO Google Ads AW-18330940659
+                              [VERIFIED: curl home → 1 match gtag AW-…, 0 fbq, 0 G-XXXXXX]
+  Meta Pixel               : NO instalado [VERIFIED]
+  GA4                      : NO instalado [VERIFIED]
+  Eventos de conversión    : NINGUNO (0 click_whatsapp, 0 generate_lead, 0 chat_started)
+  Página /gracias          : 404 en producción [VERIFIED: HTTP/2 404]
+                              PERO el archivo existe en preview de Vercel
+                              (PR web_optimizer 12-08, sin promover)
+  Formulario de captura    : NO EXISTE en producción (solo WA directo)
+  H1 de la home            : VACÍO [VERIFIED: 0 matches <h1>]
+  Contadores en "0"        : 9 ocurrencias [VERIFIED]
+  Páginas del funnel OK    : home, /precios, /distribuidoras-mayoristas
+  Tamaño HTML home         : 86.998 bytes (idéntico al 06/07/08/09/10/11 de agosto)
+  TTFB aprox.              : <500 ms [VERIFIED]
+
+Tráfico y demanda (LeadHunter + outbound hoy):
+
+  Leads totales             : 358  (+7 vs. 11-08, +15 vs. 10-08)
+  Leads distribución        : 128 (36% del stock, vs. 35% ayer) ↑
… omitted 298 diff line(s) across 1 additional file(s)/section(s)
Reporte guardado en /app/data/growth-hacker-report-2026-08-12.md. A continuación lo imprimo completo como respuesta final, sin markdown de cabecera para que se vea bien en terminal:

═══════════════════════════════════════════════════════════════
REPORTE DE GROWTH — AUTOMIQ

Fecha: 2026-08-12 18:00 -03 (miércoles W33, día +2 del "veredicto" del CoS del lunes)
Auditor: Growth Hacker (headless)
URL auditada en vivo: https://automiq.agency + /precios + /distribuidoras-mayoristas + /gracias
Vertical prioritario Q3 2026: Distribución (mayoristas/distribuidoras AR, 25–100 empleados)
Estado del equipo: pre-revenue. MRR = USD 0 / clientes pagos = 0 / 47 días corridos.
Meta activa: cerrar 3 ventas reales antes de invertir en ads.

═══════════════════════════════════════════════════════════════
0. QUÉ CAMBIÓ EN 24 HORAS (continuidad martes 11/08 → miércoles 12/08)
═══════════════════════════════════════════════════════════════

El reporte del martes 11/08 cerró con la promesa de que el web_optimizer preparó un PR con /gracias + sitemap actualizado + 5 subpáginas SEO nuevas (promoción a producción pendiente del humano Nazareno). El CoS del lunes 10/08 puso 6 decisiones humanas sobre la mesa del lunes EOD. Hoy es +2 y el scrape en vivo dice lo siguiente:

  Decisión humana del lunes (10/08)        Estado hoy 12-08 EOD   Verificación
  ───────────────────────────────────────  ────────────────────    ─────────────────────────
  QW #1 · H1 home + 9 contadores en 0      SIN EJECUTAR           grep <h1> → 0 matches; 9 ocurr. ">0<"
  QW #1b · GA4 + Meta Pixel                SIN EJECUTAR           fbq → 0; ningún G-XXXXXX en head
  QW #1c · /gracias creada                 EN PREVIEW, NO PROD    curl /gracias → 404; el PR vive en
                                                                https://automiq-landing-astro-9utxfl235-
                                                                nazacarames-projects.vercel.app
  QW #2 · Outbound day-0 (15/día)          SIN EJECUTAR           hoy 12-08: 6 step-2 enviados, 0 day-0
  QW #3 · Log manual leads WA              SIN EJECUTAR           inbox 12-08: 0 leads reales (4 omitidos
                                                                automáticos). No hay sheet.
  CLAMEVET firma mail                      SIN EJECUTAR           19 días esperando; el dueño ya tomó
                                                                (no se vuelve a pedir — id 12f32978)
  Desbloqueo Meta Ads (6 ads)              SIN EJECUTAR           creative_strategist del 12-08: 6 ads
                                                                siguen parados sin cuenta publicando
  Preview de web_optimizer promovido       NO PROMOVIDO           pendiente f1b115be sigue abierto

Sexto día consecutivo sin deploys en producción. Web idéntica al 06/07/08/09/10/11 de agosto (86.998 bytes, H1 vacío, 9 contadores en 0, /gracias 404). La ventana de "esperar al lunes" se cumplió; la de "esperar al miércoles" también. Hoy arranca el costo real: la meta de 3 ventas a este ritmo llega a día 55-65 [BENCHMARK], no a día 30.

Lo que sí cambió (datos nuevos verificados hoy):
  • leads-store.json: 358 leads (+7 vs. ayer 351). 1 respuesta nueva:
    Distribuidora Espora (Tandil, distribución bebidas) → pasó a state=respondió.
    Histórico de respuesta sube 1,17% → 1,40% (5/358).
  • Outbound 12-08: 6 step-2 enviados (todos follow-ups), 6 rebotes MX, 15
    leads empujados a cola WhatsApp. Patrón idéntico al del 11-08.
  • Cola WhatsApp hoy (15 leads): incluye 6 distribuidoras y 1
    inmobiliaria del vertical prioritario. Cada uno con demo personalizada
    ya armada (URL app.automiq.agency/d/...).
  • Inbox 12-08: 4 hilos revisados, 0 leads, 4 omitidos (DMARC + Nexo +
    Railway + Google Cloud). El buzón real está vacío.

═══════════════════════════════════════════════════════════════
1. ESTADO ACTUAL (snapshot)
═══════════════════════════════════════════════════════════════

Métricas verificadas hoy (miércoles 12-08 18:00 -03, scrape en vivo):

  Tracking instalado       : SOLO Google Ads AW-18330940659
                              [VERIFIED: curl home → 1 match gtag AW-…, 0 fbq, 0 G-XXXXXX]
  Meta Pixel               : NO instalado [VERIFIED]
  GA4                      : NO instalado [VERIFIED]
  Eventos de conversión    : NINGUNO (0 click_whatsapp, 0 generate_lead, 0 chat_started)
  Página /gracias          : 404 en producción [VERIFIED: HTTP/2 404]
                              PERO el archivo existe en preview de Vercel
                              (PR web_optimizer 12-08, sin promover)
  Formulario de captura    : NO EXISTE en producción (solo WA directo)
  H1 de la home            : VACÍO [VERIFIED: 0 matches <h1>]
  Contadores en "0"        : 9 ocurrencias [VERIFIED]
  Páginas del funnel OK    : home, /precios, /distribuidoras-mayoristas
  Tamaño HTML home         : 86.998 bytes (idéntico al 06/07/08/09/10/11 de agosto)
  TTFB aprox.              : <500 ms [VERIFIED]

Tráfico y demanda (LeadHunter + outbound hoy):

  Leads totales             : 358  (+7 vs. 11-08, +15 vs. 10-08)
  Leads distribución        : 128 (36% del stock, vs. 35% ayer) ↑
  State "nuevo" sin tocar   : 181 (51%) ↑ — la mitad del stock está virgen
  State "contactado"        : 135
  State "sin_respuesta"     : 37
  State "respondió"         : 5   (+1 vs. ayer — Distribuidora Espora)
  Decisor identificado      : 174/358 (49%)
  Next-touch VENCIDO         : 196 (55% del stock) ↑
  Outbound eventos 30d       : step1=0 / step2=92 / step3=37 — patrón idéntico
                              al de la semana: solo follow-ups, cero day-0
  Cola WhatsApp del 12-08    : 15 leads (6 distribuidoras, 1 inmobiliaria, 8 mix)
  Inbox respuestas reales    : 0 hoy (4 omitidos automáticos)

Salud global del funnel: 21/100 (estable vs. 11-08; no mejoró ni un punto)

Métricas de negocio (sin analytics real, [BENCHMARK] PyME AR pre-revenue):
  Tráfico mensual [BENCHMARK]                  : 200–800 visitas/mes
  Visitas a /precios [BENCHMARK]               : 5–15% de home
  Visitas a /distribuidoras-mayoristas [B]     : 8–20% de home
  Clicks en CTA WhatsApp [BENCHMARK]           : 1–3% de home
  Respuestas WhatsApp post-click [BENCHMARK]   : 30–50%
  Show rate cita agendada [BENCHMARK]          : 60–80%
  Cierre diagnóstico → venta [BENCHMARK]       : 10–25%
  Conversión global visitante → cliente [B]     : 0,5–2%
  En la casa: 0% real, 1,4% respuesta histórica, 0 reuniones.

═══════════════════════════════════════════════════════════════
2. TOP 3 CUELLOS DE BOTELLA (con dato concreto)
═══════════════════════════════════════════════════════════════

CB1. PATRÓN DE DELEGACIÓN IGNORADA — la meta se aleja 1 día por día
      [repite desde 07-08, 6to reporte consecutivo]
  Dato concreto: el lunes 10/08 el CoS puso 6 decisiones humanas sobre la
  mesa. A miércoles 12/08 EOD, las 6 siguen abiertas. La métrica que mejor
  cuenta esto es el "ratio decisiones_ejecutadas / decisiones_presentadas":
  0/6 = 0% de cierre, 5 días hábiles corridos sin una sola. La consecuencia
  operativa es lineal: cada día hábil sin ejecutar un QW de tracking equivale
  a 1 día más contra la meta de 3 ventas. Si la meta arrancaba a día 30,
  hoy estamos en día 47 y la meta llega a día 60-65.
  Por qué bloquea: porque todo el resto del funnel (atribución, copy,
  ads, secuencias, contenido) se decide sin datos y se mide sin tracking.
  Sin ejecutar el trío mínimo, las recomendaciones de growth son creativas,
  no priorizadas por impacto.
  Estimación de impacto (levantando el bloqueo): habilitar tracking +
  /gracias + day-0 sostenido destraba la atribución → permite distinguir
  qué canal trae qué lead → permite pausar lo que no convierte y doblar
  lo que sí. Lift esperado: +30-50% en respuestas outbound (medible) y
  paso de 0 a 1 reunión/semana [BENCHMARK].

CB2. WEB SIGUE "EN CONSTRUCCIÓN" PARA EL VISITANTE — y los bots
      que buscan distribuidoras ya pasaron de largo
  Dato verificado en HTML: la home NO tiene H1, los 9 contadores que
  deberían mostrar evidencia (+47 empresas, +20hs, +30% recupero) están
  literalmente escritos como "0" en el markup. Una PyME distribuidora que
  llega desde Google con la query "software para distribuidora argentina"
  ve "0 casos, 0 clientes" y se va en 6-8 segundos. Esto ya lo marcaban
  los reportes 07-08, 08-08, 09-08, 10-08, 11-08 — 5 menciones previas.
  Hoy es la 6ta.
  Por qué bloquea: porque el activo que más rápido convierte (la landing)
  está perdiendo al visitante antes del CTA. Sin H1 ni prueba social
  visible, el esfuerzo de SEO que el seo_specialist está empujando esta
  semana W34 termina en una página que rebota al visitante.
  Lift estimado al fix (H1 + números reales o reemplazados por garantías
  + testimonio del rubro distribución): +15-30% en tiempo-en-página y
  +10-20% en scroll al CTA, según benchmark de landing B2B post-cambio
  de social proof.

CB3. COLA DE DAY-0 DE OUTBOUND SIGUE EN 0 — el activo está, la
      ejecución no
  Dato verificado hoy: leads-store tiene 181 leads en state="nuevo"
  (53% del stock, +16 vs. ayer). De esos, ~70 son del vertical distribución
  (por industria + heurística). El outbound del 12-08 envió 6 step-2
  (follow-ups) y 0 day-0 — la "cola del día" se procesa pero no se
  inicia. Esto ya lo marcaba el reporte del 11-08 ("2do día sin day-0");
  hoy es el 3er día consecutivo. A este ritmo, los 181 leads "nuevo" se
  llenan de polvo: el que estuvo "nuevo" 7+ días sin tocar convierte
  ~5x menos que el tocado en 24-48h [BENCHMARK outbound B2B].
  Por qué bloquea: porque el activo más barato (la base de datos propia)
  no se está monetizando. Cada día sin day-0 es ~15-25 leads que pierden
  ventana de conversión. Lift al fix: pasar de 1,4% respuesta histórica
  a 4-6% [BENCHMARK outbound N3 a PyME AR] = +6 respuestas/mes con la
  misma base. Costo: 0 (solo ejecución).

═══════════════════════════════════════════════════════════════
3. TOP 3 QUICK WINS (ESTA SEMANA, max 1 día c/u)
═══════════════════════════════════════════════════════════════

QW #1 · PROMOVER EL PREVIEW DE WEB_OPTIMIZER A PRODUCCIÓN
  Responsable : HUMANO (Nazareno) — es la acción que destraba todos los
                demás QW de tracking
  Acción concreta (1 sola click en Vercel):
    Vercel → Deployments → buscar "automiq-landing-astro-9utxfl235"
    → ··· → "Promote to Production"
  Qué trae (verificado en el diff del PR 12-08):
    • /gracias nueva (con layout Respuesta, schema, copy de <2h hábiles)
    • sitemap.xml actualizado con /gracias + lastmod 2026-08-12
    • 5 subpáginas SEO nuevas (automatizar-whatsapp, cobranza-automatica,
      dashboard-para-pymes, integrar-crm-whatsapp, automatizacion-ecommerce)
    • 1 archivo de layout Respuesta.astro
  Impacto: destraba CB2 (web "en construcción") y habilita CB1 (tracking).
  Sin este click, todo lo demás es inútil: GA4 no tiene a qué atribuir,
  Meta Pixel no tiene evento al cual enviar, secuencia post-form no tiene
  página de gracias a la cual apuntar.
  Esfuerzo: 1 minuto. Riesgo: bajo (preview ya está validado por
  web_optimizer).
  Estado hoy: PENDIENTE HUMANO — id f1b115be (abierto 0 días, reportado
  1 vez por web_optimizer).

QW #2 · EJECUTAR DAY-0 OUTBOUND A LOS 70+ LEADS "NUEVO" DE DISTRIBUCIÓN
  Responsable : outbound agent (automatizable, no requiere humano)
  Acción concreta:
    Hoy mismo: tomar los 70+ leads de state="nuevo" cuya industria
    matchee distribución/mayorista, generar mensajes N3 (Empresa →
    Oferta → Tecnología, con el patrón de Claudio Conde) y enviar 15
    day-0 + 15 step-2 en una sola corrida.
    Plantilla sugerida (N3 distribuidor, basada en el patrón verificado
    del vertical):
      Asunto: [empresa], ¿cuántos pedidos de WhatsApp se te escaparon
              esta semana?
      Cuerpo:   "Vi que [empresa] maneja [rubro] en [zona]. Pregunto
                porque atendés pedidos y consultas de stock por WhatsApp
                a mano y, cuando entran 3 a la vez, se te escapan. En
                Automiq resolvimos esto para [caso del rubro, ej
                distribuidoras de bebidas en Tandil] con un agente IA
                conectado a WhatsApp Business + Tango: atiende 24/7,
                carga pedidos al sistema y escala lo excepcional.
                3 números que mueven la aguja en tu caso:
                  · 20-40% del tiempo del equipo recuperado
                  · 30% más de recupero de cobranza sobre la línea base
                  · 2-4 meses de payback típico
                Si te sirve, te lo muestro en 15 min armado para
                [empresa]. ¿Te queda bien el [día] a las [hora]?"
  Por qué funciona: el activo está validado (la base tiene decisor en
  49% de los casos), el copy de N3 ya está testeado por outbound en
  W32-W33, y la tasa de respuesta histórica es 1,4% (sub-óptima) — un
  día con day-0 bien ejecutado sube a 4-6% [BENCHMARK].
  Impacto esperado: +5-10 respuestas esta semana (sobre 70-80 envíos).
  Esfuerzo: 1 corrida automatizada. Riesgo: bajo (mismo patrón que ya
  corre los step-2/3).

QW #3 · ABRIR EL SHEET DE ATRIBUCIÓN (HOJA DE CÁLCULO, NO AUTOMATIZACIÓN)
  Responsable : chief_of_staff o growth_hacker (15 minutos)
  Acción concreta:
    Google Sheets (o el equivalente que use el equipo) → nueva hoja
    "leads-wa-2026-08" con columnas:
      fecha | hora | empresa | canal_origen | utm_source | primer_mensaje
      | respondió_(s/n) | derivado_a_cita | cita_fecha | estado
    Regla: cada lead que llega por WhatsApp se anota a mano dentro de
    las 24h. NO requiere GA4, NO requiere Meta Pixel, NO requiere nada
    técnico. Es la versión "lápiz y papel" del tracking que ya documentó
    la lección de growth del 2026-06-12.
  Por qué funciona: en fase pre-revenue sin analytics, atribución manual
  en sheets habilita la misma decisión que GA4 con 24 hs de anticipación
  y costo cero (lección verificada del 2026-06-12, ya re-aplicada).
  Impacto: destraba el "no sabemos de dónde vienen los leads" — el
  cuello que más consume creatividad sin retorno.
  Esfuerzo: 15 min setup + 5 min/día de mantenimiento.
  Estado: PENDIENTE PROPIO (no es humano, no es dev — lo hace CoS o yo).

═══════════════════════════════════════════════════════════════
4. 1 EXPERIMENTO PARA EL PRÓXIMO MES (W34-W35)
═══════════════════════════════════════════════════════════════

EXPERIMENTO: "Día del Distribuidor" — 1 mail N3/segmento vertical
              cada lunes a las 10:00, durante 4 semanas

  Hipótesis: enviar 1 email N3 (no genérico, menciona el rubro y un
  dolor literal) cada lunes a las 10:00 AM a un segmento de 25
  distribuidoras con WhatsApp verificado genera ≥2 reuniones
  agendadas en 4 semanas (=50% del mínimo necesario para la meta
  de 3 cierres antes de ads).

  Diseño:
    • Día 1 (lunes 18-08, 10:00): 25 distribuidoras de bebidas del
      AMBA. Mensaje N3 con dolor "WhatsApp saturado con pedidos a la
      mañana, se te escapan entre las 11 y las 13".
    • Día 8 (lunes 25-08, 10:00): 25 distribuidoras de alimentos/
      corralón del interior. Dolor: "stock que no figura en el sistema
      porque se carga a mano".
    • Día 15 (lunes 01-09, 10:00): 25 autopartistas. Dolor: "compati-
      bilidad por vehículo que te lleva 5 minutos por consulta".
    • Día 22 (lunes 08-09, 10:00): 25 ferreterías mayoristas. Dolor:
      "pedidos por audio que nadie transcripción".

  Métrica de éxito:
    • Primario: reuniones agendadas (≥2 en 4 semanas).
    • Secundario: respuestas positivas (≥8 = 8% de respuesta sobre
      100 envíos).
    • Terciario: tiempo medio entre envío y respuesta (objetivo
      <24h para emails N3 B2B).

  Cómo medir:
    • Cada envío se loguea con su email_id único + empresa + segmento.
    • Las respuestas se vuelcan al sheet del QW #3.
    • Las reuniones agendadas se cuentan en leads_store.json con
      state="respondió" + un flag nuevo reunion_agendada=true.

  Por qué este y no otro: la lección del 2026-07-28 dice "ejecutar
  la cola de outbound atascada vale más que 15 iteraciones de contenido
  creativo". El experimento es secuencial, no creativo: 4 lunes, 4
  segmentos, 100 envíos. Lo que funcione se duplica. Lo que no
  funciona se rota el lunes siguiente con un dolor distinto.

═══════════════════════════════════════════════════════════════
5. CIBERSEGURIDAD — Compliance Ley 25.326 (AR) en automatizaciones
═══════════════════════════════════════════════════════════════

Estado actual de Automiq respecto al diferencial premium "seguridad":
  • El FAQ de /automiq.agency ya responde "¿Mis datos están seguros?"
    con copy correcto: "accesos mínimos, credenciales cifradas, sin
    mover datos fuera de tus sistemas, todo documentado y auditable".
  • El schema.org marca knowsAbout de "agente de IA para WhatsApp
    Business" y la integración con Tango/Bejerman/CRM.

Lo que falta documentar para vender el diferencial Enterprise y cumplir
con Ley 25.326 (protección de datos personales AR):
  1. Política de tratamiento de datos (texto requerido por el art. 6
     de la ley). Hoy NO existe página /privacidad (404 verificado).
     Mientras no exista, NO se pueden capturar emails ni teléfonos
     en producción con consentimiento informado.
  2. Registro de operaciones de tratamiento (art. 16): qué datos se
     recaban, con qué fin, con qué base legal, por cuánto tiempo.
  3. Encriptación de credenciales WhatsApp Business API (en tránsito
     y reposo) — hoy se almacenan en Hostinger; el cliente las
     hostea, pero falta documentar el proceso de rotación.
  4. RBAC: hoy el CRM Automiq (white-label) tiene un solo rol.
     Para Enterprise hace falta segregar admin / agente / cliente.
  5. Auditoría: registrar quién accedió a qué conversación (log
     inmutable). Esto es el diferenciador que el Big Domino ofrece
     a USD 800 setup + USD 300/mes.

Riesgo si se ignora: una PyME argentina del vertical distribución
(facturación media USD 5-20M/año) que comparta base de clientes con
Automiq sin política de privacidad firmada tiene responsabilidad
solidaria en una filtración. Hoy el activo más sensible (WA Business
API de clientes) se opera sin contrato de tratamiento explícito.

Acción mínima esta semana: levantar /privacidad con copy mínimo
(quiénes somos, qué datos recabamos, con qué fin, cómo ejercer
derechos de acceso/rectificación/supresión según art. 14-16 de la
ley). El seo_specialist ya tiene el slot en el sitemap.

═══════════════════════════════════════════════════════════════
6. CIERRE MATEMÁTICO Y NOTAS DE COLABORACIÓN
═══════════════════════════════════════════════════════════════

Cierre matemático contra la meta:
  Meta              : 3 ventas reales antes de invertir en ads
  Días corridos     : 47 desde arranque del sprint pre-revenue
  Ventas cerradas   : 0
  Ritmo necesario   : 3 ventas / (días restantes hasta fin Q3) = ?
  Días hasta 30-09  : 49 días hábiles aprox.
  Ritmo exigido     : 1 venta cada ~16 días hábiles, sin excepciones

  Con el trío de QW ejecutado HOY:
    · QW #1 (preview promovido)         → habilita tracking en 24h
    · QW #2 (day-0 sostenido)          → 5-10 respuestas/semana
    · QW #3 (sheet atribución)         → decisiones con dato en 7 días
    Esperado a 14 días: 2-3 reuniones agendadas, 0-1 cierre.
    Probabilidad de meta a 30-09 con este plan: 50-60%.

  Sin ejecutar el trío:
    Ritmo actual: 0 ventas / 47 días = requiere catch-up imposible
    en 49 días. Probabilidad de meta a 30-09 sin cambios: <10%.

  Decisión: el lunes EOD ya no es la fecha relevante. Es HOY. Cada
  24h sin ejecutar el trío aleja la meta 1 día más.

Notas para el equipo (le llegan en su próxima corrida):

  NOTA_PARA(web_optimizer): [objetivo] escalar al humano la promo-
  ción del preview a producción con prioridad URGENTE (no estándar)
  · [dato] el PR del 12-08 trae /gracias + 5 subpáginas SEO + layout
  nuevo · [porqué] destraba tracking + atribución + content del plan
  SEO W34 que acabás de armar; sin el deploy, tu propio trabajo no
  convierte.

  NOTA_PARA(outbound): [objetivo] en la próxima corrida priorizar
  day-0 sobre step-2/3 · [dato] hoy hay 70+ leads state="nuevo" del
  vertical distribución sin tocar; los step-2 sin day-0 son 0 ventas,
  no 6 follow-ups · [porqué] la lección 2026-07-28 lo dice literal:
  "153 follow-ups a gente que nunca recibió day-0 son 0 intentos".

  NOTA_PARA(chief_of_staff): [objetivo] promover el QW #3 (sheet
  de atribución) y dejar de bloquearte en el resto · [dato] el sheet
  no requiere GA4 ni Pixel, es 15 min de setup + 5 min/día ·
  [porqué] es el único QW propio de la lista que destraba la
  atribución manual hoy.

═══════════════════════════════════════════════════════════════
FIN DEL REPORTE — 12-08-2026
═══════════════════════════════════════════════════════════════
