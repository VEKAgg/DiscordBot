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
# UV_EXTRAS is empty for the bot image; the dashboard API image builds with "--extra api".
ARG UV_EXTRAS=""
RUN uv sync --locked --no-dev --no-install-project ${UV_EXTRAS}

# ---- runtime: no compilers, no git ----
FROM python:3.13-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg libopus0 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 veka \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin veka

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    VEKA_LOG_TO_FILE=0

WORKDIR /app
COPY main.py ./
COPY src ./src
COPY migrations ./migrations
# Configuration is injected by Compose env_file, not a mounted credential file.
# Logs go to stdout; the application needs no writable host bind mount.
USER 10001:10001
CMD ["python", "main.py"]
