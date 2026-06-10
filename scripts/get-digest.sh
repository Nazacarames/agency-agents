#!/usr/bin/env bash
# get-digest.sh — Obtiene el digest SHA256 de una imagen en GHCR
# Uso: ./get-digest.sh <owner> <repo> <commit-sha>
set -euo pipefail

OWNER="$1"
REPO="$2"
SHA="$3"

# Intentar con docker inspect (si la imagen está en cache local)
DIGEST=$(docker inspect "ghcr.io/${OWNER}/${REPO}:sha-${SHA}" \
  --format='{{index .RepoDigests 0}}' 2>/dev/null | cut -d'@' -f2)

if [ -z "$DIGEST" ]; then
  # Fallback: buscar en GHCR API
  echo "Obteniendo digest via GHCR API..." >&2
  VERSIONS=$(curl -sS \
    -H "Authorization: Bearer $GITHUB_TOKEN" \
    -H "Accept: application/vnd.github.v3+json" \
    "https://api.github.com/users/${OWNER}/packages/container/${REPO}/versions?per_page=10" 2>/dev/null)

  DIGEST=$(echo "$VERSIONS" | python3 -c "
import sys, json
data = json.load(sys.stdin) if sys.stdin.read() else []
" 2>/dev/null || python3 -c "
import sys, json
data = json.load(sys.stdin)
sha = '$SHA'
for v in data:
    tags = v.get('metadata', {}).get('container', {}).get('tags', [])
    if any(sha in t for t in tags):
        print(v['name'])
        sys.exit(0)
print('', end='')
" 2>/dev/null <<< "$VERSIONS")
fi

echo "$DIGEST"
if [ -z "$DIGEST" ]; then
  exit 1
fi