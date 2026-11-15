#!/bin/sh
# Deploys the API to its Vercel project, blb-api, from this checkout.
#
# data/ isn't in git (the dataset has no stated licence), so the API is deployed from a machine
# that has it, rather than by Vercel's Git integration. Build it first if needed:
#     uv run --group ingest python -m recommender.ingest
# The upload is assembled in a temporary folder with only what the function needs, so no
# .vercelignore or vercel.json at the repository root affects the web page's builds.
# Run from anywhere: sh scripts/deploy-api.sh. It uses the project link in .vercel/ (made by
# `npx vercel link --project blb-api`), or VERCEL_ORG_ID and VERCEL_PROJECT_ID with VERCEL_TOKEN.
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

upload=$(mktemp -d)
trap 'rm -rf "$upload"' EXIT
mkdir -p "$upload/api" "$upload/.vercel"
cp api/index.py "$upload/api/"
cp -r src data "$upload/"
find "$upload/src" -name __pycache__ -type d -prune -exec rm -rf {} +
cp requirements.txt "$upload/"
cp deploy/api/vercel.json "$upload/"
if [ -f .vercel/project.json ]; then
  cp .vercel/project.json "$upload/.vercel/"
fi

npx --yes vercel@65.16.0 deploy --prod --yes --cwd "$upload" ${VERCEL_TOKEN:+--token "$VERCEL_TOKEN"}
