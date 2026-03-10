# syntax=docker/dockerfile:1.4

# ========================================
# Build stage - Install dependencies
# ========================================
FROM python:3.11-slim as builder

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Poetry
ENV POETRY_VERSION=1.7.1
ENV POETRY_HOME=/opt/poetry
ENV PATH="${POETRY_HOME}/bin:${PATH}"
RUN curl -sSL https://install.python-poetry.org | python3 -

# Set working directory
WORKDIR /app

# Copy dependency files
COPY pyproject.toml poetry.lock* ./

# Configure Poetry
RUN poetry config virtualenvs.in-project true && \
    poetry config virtualenvs.create true

# Install dependencies (without dev dependencies)
RUN poetry install --only main --no-interaction --no-ansi

# Copy application code
COPY jama_cli ./jama_cli/
COPY jama_mcp_server ./jama_mcp_server/

# Install the package
RUN poetry install --only main --no-interaction --no-ansi

# ========================================
# Production stage - Minimal runtime image
# ========================================
FROM python:3.11-slim as production

# Create non-root user for security
RUN groupadd --gid 1000 appgroup && \
    useradd --uid 1000 --gid appgroup --shell /bin/bash --create-home appuser

# Set working directory
WORKDIR /app

# Copy virtual environment from builder
COPY --from=builder /app/.venv /app/.venv

# Copy application code
COPY --from=builder /app/jama_cli /app/jama_cli
COPY --from=builder /app/jama_mcp_server /app/jama_mcp_server

# Set environment variables
ENV PATH="/app/.venv/bin:${PATH}"
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONPATH=/app

# Create config directory
RUN mkdir -p /home/appuser/.jama && \
    chown -R appuser:appgroup /home/appuser/.jama

# Switch to non-root user
USER appuser

# Expose the default port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

# Run MCP server in foreground (required for Docker)
CMD ["jama", "serve", "--host", "0.0.0.0", "--port", "8000"]

# ========================================
# Development stage - With dev dependencies
# ========================================
FROM python:3.11-slim as development

# Install development tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    vim \
    && rm -rf /var/lib/apt/lists/*

# Install Poetry
ENV POETRY_VERSION=1.7.1
ENV POETRY_HOME=/opt/poetry
ENV PATH="${POETRY_HOME}/bin:${PATH}"
RUN curl -sSL https://install.python-poetry.org | python3 -

# Create non-root user
RUN groupadd --gid 1000 appgroup && \
    useradd --uid 1000 --gid appgroup --shell /bin/bash --create-home appuser

# Set working directory
WORKDIR /app

# Copy dependency files
COPY pyproject.toml poetry.lock* ./

# Configure Poetry
RUN poetry config virtualenvs.in-project true

# Install all dependencies (including dev)
RUN poetry install --no-interaction --no-ansi

# Copy application code
COPY . .

# Install the package in development mode
RUN poetry install --no-interaction --no-ansi

# Set ownership
RUN chown -R appuser:appgroup /app

# Switch to non-root user
USER appuser

# Set environment variables
ENV PATH="/app/.venv/bin:${PATH}"
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

# Expose the default port
EXPOSE 8000

# Default command for development
CMD ["poetry", "run", "jama", "serve", "--host", "0.0.0.0", "--port", "8000"]
