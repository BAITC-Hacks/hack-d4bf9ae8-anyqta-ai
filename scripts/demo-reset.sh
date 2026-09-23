#!/bin/sh
set -eu

if ! docker compose exec -T career-quest python -c 'import os, sys; sys.exit(0 if os.getenv("DEMO_MODE", "false").lower() == "true" else 1)'; then
  echo "Reset requires a running career-quest service with DEMO_MODE=true."
  exit 1
fi

printf 'This removes the local Career Quest demo database, imported jury profiles and demo progress. Type reset-demo to continue: '
read answer
if [ "$answer" != "reset-demo" ]; then
  echo "Reset cancelled."
  exit 0
fi

docker compose down -v
docker compose up --build -d
echo "Demo reset complete. Open http://127.0.0.1:${CAREER_QUEST_PORT:-8000}"
