#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")/.."
case "${1:-}" in
api) export PYTHONPATH=apps/api OMP_NUM_THREADS=2 TOKENIZERS_PARALLELISM=false; exec .venv/bin/python -m uvicorn nexus.main:app --host 127.0.0.1 --port 8000 --workers 1 --no-access-log ;;
web) export NEXT_PUBLIC_API_URL="$(.venv/bin/python -c 'from dotenv import dotenv_values; print(dotenv_values(".env").get("NEXT_PUBLIC_API_URL", "http://127.0.0.1:8000"))')"; cd apps/web; exec npm run dev ;;
*) printf '%s\n' 'Usage: sh scripts/run.sh api|web'; exit 2 ;;
esac
