#!/usr/bin/env bash
# Turnkey Railway wiring for Sentinel-Next (friendly-acceptance).
# Usage:
#   export RAILWAY_API_TOKEN='your-account-token'   # https://railway.com/account/tokens
#   ./scripts/railway-fix.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ -z "${RAILWAY_API_TOKEN:-}" && -z "${RAILWAY_TOKEN:-}" ]]; then
  echo "❌ Set RAILWAY_API_TOKEN (Account token from https://railway.com/account/tokens)"
  exit 1
fi

command -v railway >/dev/null || { echo "❌ install railway CLI"; exit 1; }
command -v python3 >/dev/null

FRONT_URL="${FRONT_URL:-https://balanced-enchantment-production-bca7.up.railway.app}"
BACK_URL="${BACK_URL:-https://sentinel-next-back-production.up.railway.app}"
SECRET_KEY="${SECRET_KEY:-$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')}"

echo "▶ Linking project…"
# Try known project name from dashboard; fall back to interactive list
railway link --project friendly-acceptance --environment production --json 2>/dev/null \
  || railway link --json

echo "▶ Backend service: sentinel-next-back"
railway service link sentinel-next-back 2>/dev/null || railway link --service sentinel-next-back --json

echo "▶ Setting backend variables…"
railway variable set \
  "CORS_ORIGINS=[\"${FRONT_URL}\"]" \
  "SECRET_KEY=${SECRET_KEY}" \
  "DEMO_MODE=false" \
  "SKIP_AI_WARMUP=true" \
  "HOSTNAME=0.0.0.0"

# Variable references (Postgres / Redis) — via GraphQL if CLI can't
echo "▶ Tip: if DATABASE_URL/REDIS_URL missing, add Variable Reference in UI (Postgres + Redis)."

echo "▶ Redeploy backend…"
railway up --service sentinel-next-back --detach -c 2>/dev/null || railway redeploy --service sentinel-next-back -y 2>/dev/null || true

echo "▶ Frontend service: balanced-enchantment"
railway link --service balanced-enchantment --json 2>/dev/null || true

railway variable set \
  "NEXT_PUBLIC_API_URL=${BACK_URL}/api/v1" \
  "NEXT_PUBLIC_WS_URL=wss://${BACK_URL#https://}/ws/events" \
  "HOSTNAME=0.0.0.0" \
  "PORT=8080"

echo "▶ Redeploy frontend…"
railway up --service balanced-enchantment --detach -c 2>/dev/null || railway redeploy --service balanced-enchantment -y 2>/dev/null || true

echo ""
echo "✅ Done. Verify:"
echo "  curl -s ${BACK_URL}/health"
echo "  curl -sI ${FRONT_URL}/ | head -5"
echo "  Login: salon@vaitai.ai / salon"
echo ""
echo "⚠ On EACH service → Settings → Config-as-code path:"
echo "  sentinel-next-back     → railway.backend.toml"
echo "  balanced-enchantment   → railway.frontend.toml"
