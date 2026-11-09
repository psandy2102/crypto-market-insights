FROM python:3.12-slim

WORKDIR /app

COPY apps/api/pyproject.toml apps/api/README.md ./
COPY apps/api/src ./src
COPY apps/api/migrations ./apps/api/migrations
COPY alembic.ini ./

RUN pip install --no-cache-dir .

EXPOSE 8000

CMD ["sh", "-c", "alembic upgrade head && uvicorn crypto_market_insights.main:app --host 0.0.0.0 --port 8000"]
