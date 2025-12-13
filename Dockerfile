# Multi-stage build for Gmail MCP Server
FROM python:3.12-slim as builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy files needed for build
COPY pyproject.toml README.md ./
COPY src ./src

# Install Python dependencies
RUN pip install --no-cache-dir build && \
    pip wheel --no-cache-dir --wheel-dir /wheels .

# Production image
FROM python:3.12-slim

WORKDIR /app

# Create non-root user
RUN useradd --create-home --shell /bin/bash appuser

# Install runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Copy wheels and install
COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir /wheels/* && rm -rf /wheels

# Copy application code (already in wheel, but need config)
COPY config /app/config

# Create directories for credentials and data
RUN mkdir -p /app/credentials /app/data && \
    chown -R appuser:appuser /app

# Environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    CREDENTIALS_PATH=/app/credentials \
    CATEGORIES_CONFIG=/app/config/categories.yaml \
    MCP_SERVER_HOST=0.0.0.0 \
    MCP_SERVER_PORT=8000

# Switch to non-root user
USER appuser

# Expose API port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8000/health').raise_for_status()"

# Default command runs the REST API server
CMD ["python", "-m", "mcp_gmail.api"]
