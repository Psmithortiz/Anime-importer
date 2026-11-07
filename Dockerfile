# syntax=docker/dockerfile:1

# ---- builder: resolve and install dependencies into /app/.venv
FROM python:3.13-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:0.13.7 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never
WORKDIR /app
# Dependencies first: this layer is reused until pyproject.toml or uv.lock change.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project
# Then the project itself, installed non-editable so the venv does not depend on /app/src.
COPY README.md ./
COPY src ./src
RUN uv sync --locked --no-dev --no-editable

# ---- runtime: only the virtual environment, as a non-root user
FROM python:3.13-slim
RUN useradd --create-home app \
    && mkdir -p /home/app/.cache \
    && chown app:app /home/app/.cache
COPY --from=builder /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0
USER app
WORKDIR /home/app
EXPOSE 8000
CMD ["anime-importer-web"]
