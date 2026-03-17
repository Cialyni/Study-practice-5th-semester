FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

COPY gitlab-scripts /app/gitlab-scripts
COPY webhook-app /app/webhook-app
COPY .env /app/.env

WORKDIR /app/webhook-app

RUN uv venv && \
    uv pip install -e /app/gitlab-scripts && \
    uv pip install -e .


CMD ["uv", "run", "python", "-m", "uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]