# MIGA MCP Server — Multi-stage Dockerfile
# Shared by all platform servers, gateway, and bot.
# Build target selects which service to run.

FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install shared library
COPY miga_shared/ /app/miga_shared/
COPY pyproject.toml /app/

# Install base Python deps
RUN pip install --no-cache-dir \
    fastmcp>=2.0.0 \
    httpx>=0.27.0 \
    pydantic>=2.5.0 \
    "redis[hiredis]>=5.0.0" \
    PyJWT>=2.8.0 \
    cryptography>=41.0.0

# ---------------------------------------------------------------------------
# Platform MCP Server target
# ---------------------------------------------------------------------------
FROM base AS server

ARG SERVER_NAME
COPY servers/${SERVER_NAME}/ /app/servers/${SERVER_NAME}/

ENV SERVER_NAME=${SERVER_NAME}
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:${PORT:-8001}/health || exit 1

CMD ["sh", "-c", "python -m servers.${SERVER_NAME}.server"]

# ---------------------------------------------------------------------------
# Gateway target
# ---------------------------------------------------------------------------
FROM base AS gateway

COPY packages/gateway/ /app/packages/gateway/

ENV MIGA_GATEWAY_PORT=8000
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["python", "-m", "packages.gateway.server"]

# ---------------------------------------------------------------------------
# WebEx Bot target
# ---------------------------------------------------------------------------
FROM base AS webex-bot

RUN pip install --no-cache-dir aiohttp>=3.9.0

COPY packages/webex_bot/ /app/packages/webex_bot/

ENV WEBEX_BOT_PORT=9000
EXPOSE 9000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:9000/health || exit 1

CMD ["python", "-m", "packages.webex_bot.app"]

# ---------------------------------------------------------------------------
# INFER target (extra ML deps)
# ---------------------------------------------------------------------------
FROM base AS infer

RUN pip install --no-cache-dir \
    pandas>=2.1.0 \
    scipy>=1.11.0 \
    scikit-learn>=1.3.0

COPY servers/infer_mcp/ /app/servers/infer_mcp/

ENV INFER_MCP_PORT=8007
EXPOSE 8007

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:8007/health || exit 1

CMD ["python", "-m", "servers.infer_mcp.server"]
