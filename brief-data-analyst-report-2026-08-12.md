Tengo todo lo que necesito. Armo el reporte.

================================================================
REPORTE DATA ANALYST — Automiq
Semana 32 (W32) 2026-08-05 → 2026-08-12
================================================================

TITULARES (los 5 números que importan esta semana)

 1. Leads 7d: +22 (329 → 351) vs +50 la semana previa → -56% WoW. 
 La captura semanal se desaceleró a la mitad.
 2. Días en cero: 3 de los últimos 7 (09, 10 y 11/08) → leadhunter 
 dejó de entregar durante 3 jornadas consecutivas y volvió recién hoy (+8).
 3. Conversión lead→cliente: 0/351 (0,00%) sostenido · 48/48 días 
 con 0 clientes activos. El KPI de captura dejó de ser señal de salud.
 4. Profit mensual: -US$ 33 (vs -US$ 10,99 en julio) → expenses 
 +200% (de US$ 10,99 a US$ 33, categoría infra). revenue $0.
 5. MRR: US$ 0 · 0 clientes · 48 días consecutivos. Cuello de botella 
 confirmado en EJECUCIÓN outbound, no en captura.

================================================================
TENDENCIAS

QUÉ CRECE
 · Acumulado de leads: 42 → 351 en 48 días (sube monotónicamente, 
 no decrece). La MÁQUINA de captura funciona.
 · Expense infra: jul US$ 10,99 → ago US$ 33. Subió un renglón 
 concreto (probable cambio de plan/hosting). Hay que mirar a qué.

QUÉ CACA / SE ESTANCA
 · Ritmo de captura: 7d previo +50 leads, 7d actual +22. 
 El promedio diario cayó de 7,1 a 3,1 leads/día.
 Patrón: 2 cosechas grandes (lun 04/08 +8 y jue 07/08 +7) seguidas 
 de 3 días en cero (sáb-dom-lun 09-11/08). Ritmo intermitente, no 
 diario como prometió el agente.
 · Captura diaria: 15/47 días con delta=0 en la serie. Casi 1 de cada 3 
 días no entra nada. La promesa "10 leads/día" no se sostiene.

QUÉ ESTÁ PLANO
 · MRR / clientes activos: 0. Plano desde el 25/06. Ya no es novedad.
 · Profit: plano en -US$ 33 desde el 09/08 (4 días sin moverse).

================================================================
ALERTAS (atención ya)

 · 🔴 [LEADHUNTER STALLED] 09-10-11/08 tres ceros consecutivos. 
 Patrón IDENTICO al del 2026-07-02 al 07 (3 ceros seguidos). 
 No es la primera vez. Hipótesis probable: dependencia de un 
 orquestador externo (cron/scheduler) que cae en fines de semana 
 largo, no de un token vencido (eso ya quedó descartado por la 
 lección del 2026-08-10). Acción: comparar horario de los ceros 
 con el cron del leadhunter para ver si la ventana se está perdiendo.
 · 🔴 [BURNOUT FINANCIERO] expenses +200% en 30 días sin revenue. 
 El runway implícito con esta cadencia se va a acabar. Hoy el 
 costo mensual es ínfimo (US$ 33), pero la pendiente importa más 
 que el: si la línea de infra sigue subiendo sin clientes 
 activos, en 2-3 meses deja de ser "muebles de oficina" y pasa 
 a ser "la hipoteca" del fundador.
 · 🟡 [STAGNATION 72H] leads estancados en 343 del 09 al 11/08. 
 72 horas sin sumar UN SOLO lead. Si se repite una vez más, no 
 es ruido: es señal de que el pipeline de captura se cortó en seco.
 · 🟡 [DUMMY RATIO] leads→cliente 0,00% con n=351. Ya lleva 4+ 
 semanas en cero. Esto NO es un KPI de negocio: es un termómetro 
 de ACTIVIDAD operativa. Lo que falta medir son contactos humanos 
 hechos, respuestas, reuniones agendadas.

================================================================
CAUSAS PROBABLES + ACCIONES

 Hallazgo A — captura cae 56% WoW sin caída de clientes
 Causa probable: depende menos de capacidad y más de 
 disponibilidad/disparo de la herramienta. El volumen absoluto 
 sigue subiendo (+22 leads en la semana), pero el ritmo diario 
 es la mitad. La métrica diaria enmascara la desaceleración.
 Acción para el dueño: validar el lunes 18/08 que la corrida 
 del leadhunter esté pasando por el scheduler correcto. Si vuelve 
 a fallar en sábado-domingo, es el patrón y no un glitch.

 Hallazgo B — profit mensual -US$ 33, jun/jul casi cero
 Causa probable: salto discreto del 02/08 (-$5 → -$13 → -$33) 
 coincide con la apertura de la fila infra. Hoy no hay forma de 
 saber si es un cargo extraordinario (anual, prorrateado) o 
 recurrente. Sin revenue, cada línea de expense importa.
 Acción: pedir al dueño una captura de qué se pagó en infra 
 estos últimos 30 días. Sin eso, no se sabe si el costo es 
 creciente o constante.

 Hallazgo C — seguimos contando leads en vez de medir outbound
 Causa probable: durante 4+ semanas la única métrica de "actividad" 
 fue leads/día. Con 0 clientes, ese contador perdió señal hace 
 rato. Lo que importa AHORA es: ¿cuántos emails/messages de día 0 
 realmente salieron? ¿cuántos contactos humanos hubo? ¿se agendó 
 alguna reunión?
 Acción para el Chief: redefinir el KPI diario de la semana que 
 viene a uno de EJECUCIÓN (no captura). Sugerencia: 
 "contactos outbound/día" + "respuestas recibidas/semana".

================================================================
PARA EL CHIEF — 2 COSAS QUE EL CIERRE DEL DÍA DEBERÍA MIRAR

 1. ¿Por qué 09-10-11/08 fueron ceros puros? Si el leadhunter corrió 
 y devolvió 0, es un problema del upstream (sitios accesibles, 
 web_extract funcionando). Si NO corrió, es el scheduler. 
 Misma decisión que la del 2026-07-02: tenemos que saber cuál.
 2. Definir el KPI de actividad de la semana. Con 0 clientes y 
 351 leads acumulados, contar leads es teatro. La pregunta real 
 es: ¿se está moviendo el funnel humano? Si el lunes 18 sigue 
 sin haber respuestas, no es problema de Automiq, es problema 
 de si la máquina de outbound está corriendo.

================================================================
COLABORACIÓN

 NOTA_PARA(chief_of_staff): [objetivo] validar el patrón de ceros 
 del finde · [dato] 09-10-11/08 fueron 3 ceros consecutivos en 
 leads, idéntico al del 02-04/07; el scheduler/cron podría estar 
 cayendo en finde · [porqué] si se confirma, lo que se arregla 
 es la programación, no el agente; cambia la siguiente decisión de 
 arquitectura.

 LECCIÓN: cuando MRR=0 y clientes=0 hace ≥4 semanas, leads/día 
 deja de ser KPI de salud — pasa a ser termómetro de ACTIVIDAD 
 operativa. El KPI que falta es "contactos humanos hechos / 
 respuestas obtenidas / reuniones agendadas", no "leads brutos". 
 (repite la del 2026-08-10: ya van dos semanas donde la conclusión 
 es la misma — urge migrar la métrica).

================================================================
PENDIENTES (ninguno nuevo — la lista actual ya cubre lo accionable)

 Hoy no agrego pendientes nuevos. Lo único accionable que detecté 
 (cambio de infra no documentado, patrón de ceros en finde) requiere 
 información que sólo el dueño tiene o acceso al scheduler que no me 
 corresponde. Si esto se sostiene una semana más, escalo.

================================================================
RESUELTOS

 RESUELTO(21555268): el reporte del 2026-08-10 identificó que 
 leadhunter entregaba un resumen en lugar del reporte por techo de 
 turnos. Hoy el dato volvió a la serie diaria (351 leads, +8 hoy), 
 confirmando que la captura está normalizada. Cierro la nota, no 
 la reabro. Evidencia: la serie tiene 48 puntos consistentes y el 
 delta diario de los últimos 14 días discrimina correctamente entre 
 ceros y entregas.

================================================================
NOTA FINAL

 El negocio está donde estaba hace 7 días: 0 clientes, 0 MRR, 
 351 leads en el freezer. Lo que MOVIÓ la aguja esta semana no 
 fueron los leads (siguieron entrando, más lento) sino la 
 decisión de cambiar el KPI. A partir de la semana que viene, 
 medir leads brutos sin medir outbound es mirar el velocímetro 
 con el auto apagado.

 → owners: Nazareno + chief_of_staff
 → próximo análisis: jueves 14/08 18:30 ART (mitad de W33, 
 primer corte con la nueva métrica si la definen antes)
