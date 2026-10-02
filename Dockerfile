# The app, the web page and the prebuilt search index in one image (ADR-0002).
# CI builds build/coa.sqlite first (`coa-explorer index`), because embedding needs Vertex AI.
FROM python:3.11-slim

COPY --from=ghcr.io/astral-sh/uv:0.12.1 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"
WORKDIR /app

# Dependencies first, so code changes don't reinstall them.
COPY pyproject.toml uv.lock .python-version README.md ./
RUN uv sync --locked --no-dev --no-install-project

COPY src ./src
RUN uv sync --locked --no-dev

# Where config.DEFAULT_INDEX looks for it.
COPY build/coa.sqlite ./build/coa.sqlite

RUN useradd --system --no-create-home app
USER app

# Cloud Run sets PORT; the project settings (GCP_PROJECT_ID, GEMINI_*) arrive as env vars.
EXPOSE 8080
ENV PORT=8080
CMD ["coa-explorer", "serve", "--host", "0.0.0.0"]
