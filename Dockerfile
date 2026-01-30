FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml README.md /app/
COPY src /app/src
COPY docs/templates/dashboard-template-option1-2026-01-28.html /app/docs/templates/dashboard-template-option1-2026-01-28.html

# Security: pull OS security updates and upgrade pip tooling (wheel has known CVEs).
RUN apt-get update \
  && apt-get upgrade -y \
  && rm -rf /var/lib/apt/lists/* \
  && pip install --no-cache-dir --upgrade pip wheel \
  && pip install --no-cache-dir -e .

ENV PYTHONUNBUFFERED=1
ARG MCP_PUBLIC_READONLY=false
ENV MCP_PUBLIC_READONLY=${MCP_PUBLIC_READONLY}

# Default to a non-root user (recommended for public images).
# If you need to override (e.g. file permissions on mounted volumes), run with: `--user root`.
RUN useradd -m -u 10001 -s /usr/sbin/nologin app \
  && chown -R app:app /app
USER app

CMD ["yandex-direct-metrica-mcp"]
