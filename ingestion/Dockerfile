FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app/ingestion

COPY pyproject.toml alembic.ini ./
COPY migrations ./migrations
COPY src ./src
COPY tests ./tests
RUN pip install --no-cache-dir .

CMD ["python", "-m", "bpc_ingestion"]
