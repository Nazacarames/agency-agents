#!/usr/bin/env bash
# Listar los servicios de Render del workspace.
# Requiere: $RENDER_API_KEY en el environment (o pasarla directo).
#
# Uso:
#   export RENDER_API_KEY=***
#   ./scripts/list_render_services.sh
# o
#   RENDER_API_KEY=*** ./scripts/list_render_services.sh
set -euo pipefail

KEY="${RENDER_API_KEY:-}"
if [ -z "$KEY" ]; then
  echo "Error: RENDER_API_KEY no configurada" >&2
  echo "  export RENDER_API_KEY=***" >&2
  exit 1
fi

curl -fsS "https://api.render.com/v1/services?limit=20" \
  -H "Authorization: Bearer ${KEY}" \
  -H "Accept: application/json" | python -m json.tool 2>/dev/null || \
  curl -fsS "https://api.render.com/v1/services?limit=20" \
  -H "Authorization: Bearer ${KEY}" \
  -H "Accept: application/json"
