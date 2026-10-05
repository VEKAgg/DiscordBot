# syntax=docker/dockerfile:1

# ---- build: resolve dependencies from uv.lock into a virtualenv ----
FROM python:3.13-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:0.12.9 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv

WORKDIR /app
COPY pyproject.toml uv.lock ./
# Install exactly the locked runtime dependencies (the old `pip install .` ignored uv.lock).
RUN uv sync --locked --no-dev --no-install-project

# ---- runtime: no compilers, no git ----
FROM python:3.13-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg libopus0 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app
COPY main.py ./
COPY src ./src
COPY migrations ./migrations
RUN mkdir -p logs

# Still runs as root: ./logs is bind-mounted from the host and must stay writable for the
# rotating log file. See MIGRATION_NOTES.md for switching to a non-root user.
CMD ["python", "main.py"]
