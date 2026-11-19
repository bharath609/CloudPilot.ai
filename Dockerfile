# syntax=docker/dockerfile:1

# ---- Frontend build -------------------------------------------------------
# The SPA is compiled with Node and then served as static files by FastAPI.
FROM node:22-alpine AS frontend

WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ---- Runtime --------------------------------------------------------------
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    CLOUDPILOT_FRONTEND_DIST_DIR=/app/frontend/dist

WORKDIR /app

RUN groupadd --system app && useradd --system --gid app --create-home app

COPY backend/pyproject.toml backend/README.md ./
COPY backend/app ./app
RUN pip install --no-cache-dir .

COPY backend/alembic.ini ./
COPY backend/alembic ./alembic
COPY --from=frontend /frontend/dist ./frontend/dist
RUN chown -R app:app /app

USER app
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health')"

# Migrations are idempotent; the API never calls cloud providers.
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
