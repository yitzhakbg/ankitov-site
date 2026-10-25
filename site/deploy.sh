#!/usr/bin/env bash
# Deploy ankitov.org static site to Cloudflare Workers (Worker: white-rice-9fa6).
#
# The site is a Worker with static assets (wrangler.jsonc: assets.directory=".",
# custom domains ankitov.org + www.ankitov.org) — NOT a Cloudflare Pages project.
# The old `wrangler pages deploy --project-name=ankitov-org` command here was
# stale and would create an orphan Pages project without updating the live site.
#
# Auth: wrangler is not OAuth-authed on this machine; pass the API token via
# CLOUDFLARE_API_TOKEN (stored in macOS Keychain as
# Cloudflare_AnkiTov_Dual_Entity_Token), e.g.:
#   CLOUDFLARE_API_TOKEN=$(security find-generic-password \
#     -s Cloudflare_AnkiTov_Dual_Entity_Token -w) ./deploy.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# --- T-188 orphaned-word gate (pre-deploy, runs BEFORE anything else) --------
# Refuses to deploy while scripts/check-orphans.py reports findings.
# Override for the owner only: ./deploy.sh --force-orphans (loud warning).
FORCE_ORPHANS=0
if [ "${1:-}" = "--force-orphans" ]; then
  FORCE_ORPHANS=1
  shift
fi

echo "=== Orphaned-word gate (T-188) ==="
if python3 scripts/check-orphans.py; then
  echo "Orphan gate: clean."
else
  GATE_RC=$?
  if [ "$FORCE_ORPHANS" -eq 1 ]; then
    echo "" >&2
    echo "⚠️  ORPHAN OVERRIDE ACTIVE (--force-orphans): deploying with" >&2
    echo "⚠️  orphaned last-line words. This degrades the live site's" >&2
    echo "⚠️  typography. Fix doctrine: text-wrap: pretty + <span class=\"nb\">" >&2
    echo "⚠️  spans — NEVER bare &nbsp; (Chromium breaks at nbsp under" >&2
    echo "⚠️  text-wrap:pretty)." >&2
    echo "" >&2
  else
    echo "" >&2
    if [ "$GATE_RC" -eq 1 ]; then
      echo "✋ Deploy REFUSED: orphaned-word gate found orphans (exit 1)." >&2
    else
      echo "✋ Deploy REFUSED: orphaned-word gate could not run (exit $GATE_RC)." >&2
      echo "   The gate fails CLOSED — fix the environment or override:" >&2
      echo "   ./deploy.sh --force-orphans" >&2
    fi
    exit "$GATE_RC"
  fi
fi

echo "=== Deploying AnkiTov Organization site to Cloudflare Workers ==="
echo "Worker: white-rice-9fa6 (ankitov.org, www.ankitov.org)"
echo "Directory: $SCRIPT_DIR"

if ! command -v wrangler >/dev/null 2>&1 && ! npx --yes wrangler --version >/dev/null 2>&1; then
  echo "Error: Wrangler CLI is required for Cloudflare deployment."
  echo "Please ensure Node.js is installed, or run 'npm install -g wrangler'."
  exit 1
fi

if [ -z "${CLOUDFLARE_API_TOKEN:-}" ]; then
  echo "Error: CLOUDFLARE_API_TOKEN is not set."
  echo "Get it from the Keychain:"
  echo "  export CLOUDFLARE_API_TOKEN=\$(security find-generic-password -s Cloudflare_AnkiTov_Dual_Entity_Token -w)"
  exit 1
fi

echo "Running wrangler deploy..."
echo "⚠️  REMINDER: pre-launch, ankitov.org serves the waiting overlay (waiting/)."
echo "⚠️  Deploying the real site requires the launch green-light: repo variable SITE_LAUNCH_ENABLED=true."
npx wrangler deploy

echo "=== Deployment command executed ==="
echo "Verify live status at https://ankitov.org"
