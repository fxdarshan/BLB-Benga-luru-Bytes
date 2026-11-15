#!/bin/sh
# Deploys the API to its Vercel project, blb-api, from this checkout.
#
# data/ isn't in git (the dataset has no stated licence), so the API is deployed from a machine
# that has it, rather than by Vercel's Git integration. Build it first if needed:
#     uv run --group ingest python -m recommender.ingest
# Run from anywhere: sh scripts/deploy-api.sh. In CI, set VERCEL_TOKEN, VERCEL_ORG_ID and
# VERCEL_PROJECT_ID instead of logging in.
set -eu
cd "$(dirname "$0")/.."

if [ ! -f data/restaurants.parquet ] || [ ! -f data/metadata.json ]; then
  echo "data/ is missing. Build it with: uv run --group ingest python -m recommender.ingest" >&2
  exit 1
fi

# requirements.txt is what Vercel installs, so it must match uv.lock.
uv export --no-dev --no-default-groups --no-hashes --no-emit-project --format requirements-txt \
  --quiet -o requirements.txt
if ! git diff --quiet -- requirements.txt; then
  echo "requirements.txt was out of date with uv.lock and has been regenerated. Commit it, then deploy." >&2
  exit 1
fi

npx --yes vercel@65.16.0 deploy --prod --yes ${VERCEL_TOKEN:+--token "$VERCEL_TOKEN"}
