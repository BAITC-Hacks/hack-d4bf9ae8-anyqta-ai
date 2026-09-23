#!/bin/sh
set -eu

if [ "${DEMO_MODE:-true}" != "true" ]; then
  echo "Refusing to reset because DEMO_MODE is not true."
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
