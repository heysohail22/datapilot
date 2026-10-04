# ==============================================================================
# DataPilot Backend Dockerfile (Python 3.12 + FastAPI + uv)
# ==============================================================================

FROM python:3.12-slim AS base

# Prevent Python from writing .pyc files and enable unbuffered output
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PORT=8000

# Install system dependencies (libpq for PostgreSQL psycopg2) and curl for healthchecks
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install Astral uv binary from official image
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Set working directory
WORKDIR /app

# Create non-root system user for security compliance
RUN groupadd -g 10001 appuser && \
    useradd -u 10001 -g appuser -d /app -s /sbin/nologin appuser

# Copy dependency definition files first for optimal Docker layer caching
COPY pyproject.toml uv.lock ./

# Install production dependencies directly into /app/.venv
RUN uv sync --frozen --no-dev

# Copy application source code
COPY main.py ./
COPY app/ ./app/

# Place virtual environment in PATH
ENV PATH="/app/.venv/bin:$PATH"

# Set ownership to non-root user
RUN chown -R appuser:appuser /app

# Switch to non-privileged user
USER appuser

# Expose backend service port
EXPOSE 8000

# Container Healthcheck probing /health
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Launch FastAPI service with dynamic PORT support (defaulting to 8000)
CMD exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}
