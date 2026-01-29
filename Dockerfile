FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml README.md /app/
COPY src /app/src
COPY docs/templates/dashboard-template-option1-2026-01-28.html /app/docs/templates/dashboard-template-option1-2026-01-28.html

RUN pip install --no-cache-dir --upgrade pip \
  && pip install --no-cache-dir -e .

ENV PYTHONUNBUFFERED=1
ARG MCP_PUBLIC_READONLY=false
ENV MCP_PUBLIC_READONLY=${MCP_PUBLIC_READONLY}

CMD ["yandex-direct-metrica-mcp"]
