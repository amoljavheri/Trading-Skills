# Stage 1: Build dependencies
FROM python:3.12-slim AS builder

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copy dependency files first for layer caching
COPY pyproject.toml uv.lock ./

# Install dependencies into /app/.venv (no dev deps, frozen lockfile)
RUN uv sync --frozen --no-dev --no-install-project

# Copy source code
COPY src/ ./src/
COPY mcp_server/ ./mcp_server/

# Install the project itself
RUN uv sync --frozen --no-dev

# Stage 2: Lean runtime image
FROM python:3.12-slim AS runtime

WORKDIR /app

# Create non-root user
RUN groupadd -r trading && useradd -r -g trading trading

# Copy installed venv and source from builder
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/src /app/src
COPY --from=builder /app/mcp_server /app/mcp_server
COPY --from=builder /app/pyproject.toml /app/pyproject.toml

# Make venv binaries available; expose both packages on PYTHONPATH
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH="/app/src:/app"
ENV PORT=8080

# Run as non-root
USER trading

EXPOSE 8080

CMD ["python", "-m", "mcp_server.server"]
