FROM python:3.11-slim

WORKDIR /app

COPY backend /app/backend
COPY data/career_quest_dataset /app/data/career_quest_dataset
COPY scripts/start.sh /app/scripts/start.sh

RUN chmod +x /app/scripts/start.sh \
    && mkdir -p /app/var

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    CAREER_QUEST_DB=/app/var/career_quest.db \
    DEMO_MODE=true

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --start-period=15s --retries=5 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/', timeout=2)"

CMD ["/app/scripts/start.sh"]
