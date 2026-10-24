# syntax=docker/dockerfile:1

# --- 1. Build the web UI ------------------------------------------------------
FROM node:22-slim AS web
WORKDIR /src
RUN corepack enable
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY apps/web/package.json apps/web/
RUN pnpm install --frozen-lockfile
COPY apps/web apps/web
RUN pnpm --filter @openpipeline/web build

# --- 2. Install the Python app into a virtualenv ------------------------------
FROM python:3.13-slim AS app
COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY packages/core packages/core
COPY apps/server apps/server
COPY --from=web /src/apps/server/src/openpipeline/static apps/server/src/openpipeline/static
RUN uv sync --locked --no-dev --no-editable --package openpipeline

# --- 3. Small runtime image ---------------------------------------------------
FROM python:3.13-slim
LABEL org.opencontainers.image.title="OpenPipeline" \
      org.opencontainers.image.description="Explain and review dbt projects" \
      org.opencontainers.image.source="https://github.com/PawanPatil19/openpipeline" \
      org.opencontainers.image.licenses="Apache-2.0"

RUN useradd --create-home --uid 1000 openpipeline
COPY --from=app /app/.venv /app/.venv
# A demo project so `docker run` shows something. Mount your own over /project.
COPY --chown=openpipeline:openpipeline examples/jaffle_shop /project

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    OPENPIPELINE_PROJECT_DIR=/project \
    OPENPIPELINE_HOST=0.0.0.0

USER openpipeline
WORKDIR /project
EXPOSE 8484 8485
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8484/api/health')"

ENTRYPOINT ["openpipeline"]
CMD ["serve"]
