# keep-alive.yml — GitHub Actions cron para mantener el service despierto
# en Render plan Free (que hiberna despues de 15 min sin trafico).

# SETUP (una sola vez, despues de crear el service):
#   1. Ir a https://github.com/Nazacarames/agency-agents/settings/variables/actions
#   2. New repository variable:
#        Name:  RENDER_SERVICE_URL
#        Value: https://automiq-agents.onrender.com  (la URL real del service)
#   3. Save

# TEST manual:
#   Ir a Actions tab -> "Keep Render Service Alive" -> Run workflow
#   En pocos segundos deberia ver "OK - service is alive" o el HTTP code

# NOTA: Render Free hiberna tras 15 min sin requests. El cron de GitHub
# Actions puede tener hasta 10 min de delay entre runs programados, asi
# que el margen no es 100% seguro pero reduce las hibernaciones drasticamente.
# Si ves que el service hiberna igual, considerar:
#   - UptimeRobot (free, mas confiable)
#   - Render plan Starter ($7/mes, sin hibernacion)
