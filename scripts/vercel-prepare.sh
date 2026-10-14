#!/usr/bin/env bash
# Prepare the repo for a Vercel deploy: build the dashboard (Vercel's Python build does not run
# npm) and export the server's pinned dependencies to requirements.txt. Commit both afterwards.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
bash scripts/build-dashboard.sh
# uvloop/httptools/watchfiles only speed up a local uvicorn; Vercel never runs uvicorn.
uv export --frozen --no-dev --extra server --no-hashes --no-emit-project --no-header \
  | grep -vE '^(uvloop|httptools|watchfiles)==' > requirements.txt
git add -f src/treg/web/dashboard requirements.txt
echo "Hazır: src/treg/web/dashboard ve requirements.txt commit için eklendi."
