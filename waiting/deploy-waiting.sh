#!/usr/bin/env bash
# Publish the ankitov.org WAITING page (replaces any live site content).
# Usage: CLOUDFLARE_API_TOKEN=$(security find-generic-password \
#          -s Cloudflare_AnkiTov_Dual_Entity_Token -w) ./deploy-waiting.sh
set -euo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[ -n "${CLOUDFLARE_API_TOKEN:-}" ] || { echo "Set CLOUDFLARE_API_TOKEN (see header)"; exit 1; }
npx wrangler deploy --name white-rice-9fa6 --assets . --compatibility-date 2026-10-19
npx wrangler triggers deploy --config ../site/wrangler.jsonc
echo "Waiting page live on ankitov.org + www.ankitov.org"
