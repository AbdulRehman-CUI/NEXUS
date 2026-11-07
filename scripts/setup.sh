#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")/.."
python3.12 -m venv .venv
.venv/bin/python -m pip install -r apps/api/requirements.lock.txt
.venv/bin/python -m pip install -r apps/api/requirements-typecheck.txt
if [ ! -f .env ]; then cp .env.example .env; fi
cd apps/web
npm ci --no-audit --no-fund
printf '%s\n' 'Ready. Run scripts/run.sh api and scripts/run.sh web in separate terminals.'
