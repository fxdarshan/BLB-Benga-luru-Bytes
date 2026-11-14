# The BLB API, for Railway. See Doc/deployment-plan.md.
#
# Two stages: the first builds data/ from the pinned dataset revision, and the second is the
# server, which gets only data/ from it. The 574 MB raw download and the ingestion packages
# (datasets, pandas, ftfy) never reach the running image.

# ---------- Stage 1: build data/ ----------
FROM python:3.11-slim AS data
COPY --from=ghcr.io/astral-sh/uv:0.12.19 /uv /bin/uv
ENV UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock ./
# Hatchling needs the readme named in pyproject.toml to install the project.
COPY Doc/problemStatement.md Doc/
RUN uv sync --locked --no-default-groups --group ingest --no-install-project
COPY src/ src/
RUN uv sync --locked --no-default-groups --group ingest \
 && uv run --no-sync python -m recommender.ingest

# ---------- Stage 2: the API server ----------
FROM python:3.11-slim
COPY --from=ghcr.io/astral-sh/uv:0.12.19 /uv /bin/uv
ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PATH="/app/.venv/bin:$PATH" \
    DATA_DIR=/app/data \
    STATE_DIR=/app/state
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY Doc/problemStatement.md Doc/
RUN uv sync --locked --no-default-groups --no-install-project
COPY src/ src/
RUN uv sync --locked --no-default-groups
COPY --from=data /app/data ./data

# Serve as an unprivileged user. STATE_DIR keeps the usage counts and feedback; on Railway it is a
# volume, which is mounted owned by root. So the container starts as root only to hand that
# directory to the user, and setpriv drops to it before the server starts. The build checks that
# setpriv exists, so a missing tool fails the build rather than a deploy.
RUN useradd --create-home --uid 10001 blb \
 && mkdir -p "$STATE_DIR" \
 && chown -R blb:blb /app \
 && setpriv --version

# Railway sets PORT. One worker, so every search shares one cache and one view of the
# provider's token limit. If the chown fails, the server still starts and keeps counts in memory.
CMD ["sh", "-c", "chown -R blb:blb \"$STATE_DIR\"; exec setpriv --reuid=blb --regid=blb --init-groups uvicorn --factory recommender.api:create_app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
