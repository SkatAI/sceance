# Multi-stage image for DigitalOcean App Platform.
# Builds the sceance server with uv, runs uvicorn on port 8080.

FROM python:3.11-slim-bookworm AS base

# Runtime system deps: libgomp1 is needed by onnxruntime (Silero VAD).
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        libgomp1 \
        libgl1 \
        libglib2.0-0 \
        libxcb1 \
        libsm6 \
        libxext6 \
        libxrender1 \
    && rm -rf /var/lib/apt/lists/*

# Install uv (multi-arch, pinned via :latest tag of the official image).
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    PYTHONUNBUFFERED=1

# --- deps layer ---
# Copy lockfile first so dependency installation is cached.
WORKDIR /app/server
COPY server/pyproject.toml server/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# --- source layer ---
WORKDIR /app
COPY server /app/server
COPY personas /app/personas

WORKDIR /app/server

# App Platform routes inbound HTTPS to port 8080 by default.
EXPOSE 8080

CMD ["uv", "run", "--no-dev", "uvicorn", "server:app", \
     "--host", "0.0.0.0", "--port", "8080"]
