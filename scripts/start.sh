#!/bin/sh
set -eu

python -m backend.app.bootstrap \
  --database "${CAREER_QUEST_DB}" \
  --dataset-dir /app/data/career_quest_dataset

exec python -m backend.app.web \
  --database "${CAREER_QUEST_DB}" \
  --host 0.0.0.0 \
  --port 8000
