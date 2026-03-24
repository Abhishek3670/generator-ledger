FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY alembic.ini ./
COPY config.py main.py cli_main.py ./
COPY core ./core
COPY cli ./cli
COPY web ./web
COPY scripts ./scripts
COPY alembic ./alembic

# Install Python dependencies
RUN python -m pip install --upgrade pip setuptools wheel \
    && python -m pip install .

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /usr/local /usr/local
COPY alembic.ini ./
COPY config.py main.py cli_main.py ./
COPY core ./core
COPY cli ./cli
COPY web ./web
COPY scripts ./scripts
COPY alembic ./alembic

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

# Run application
CMD ["python", "main.py", "--web", "--host", "0.0.0.0"]
