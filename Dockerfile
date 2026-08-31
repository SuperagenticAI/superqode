# Container image for the public SuperQode A2A endpoint.
#
# Built for Cloud Run, which sets PORT at runtime and requires the process to
# bind 0.0.0.0. The image installs only the a2a extra, so it carries neither the
# optional SDK runtimes nor the local model stack.
#
# This lives at the repository root because Cloud Build uses the Dockerfile's
# directory as the build context, and the COPY steps below need the repository
# root as that context.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    SUPERQODE_TELEMETRY=false \
    SUPERQODE_NO_SPLASH=1

WORKDIR /app

# uv resolves and installs considerably faster than pip, which matters because
# Cloud Run rebuilds the image on every source deploy.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# SuperQode uses a src layout, so the package is copied under src/ and the
# agent catalogue TOMLs travel with it through package-data.
COPY pyproject.toml README.md LICENSE NOTICE MANIFEST.in ./
COPY src ./src

RUN uv pip install --system --no-cache ".[a2a]"

# The advertised interface URL. Cloud Run cannot know the custom domain mapped
# in front of it, and a card that advertises the run.app hostname would pin
# callers to an address you cannot move. Set this on the service.
ENV SUPERQODE_A2A_PUBLIC_URL=https://a2a.superqode.dev

# Cloud Run injects PORT. The default keeps `docker run` working locally.
ENV PORT=8080
EXPOSE 8080

# The entry point is a CLI subcommand rather than a uvicorn app path.
#
# --allow-remote is required because the server refuses a non-loopback bind
# without it. The harness skill stays off: on a remote bind SuperQode serves
# only the Hub shortlist, which needs no repository, no model call and no
# sandbox. Serving harnesses publicly would need --expose-harness and a named
# spec, which is a different security decision.
#
# --no-task-store keeps A2A task records in memory. Cloud Run's filesystem is
# ephemeral and per-instance, so a SQLite file would not survive a restart and
# would diverge between instances.
CMD exec superqode serve a2a \
    --host 0.0.0.0 \
    --port ${PORT} \
    --public-url ${SUPERQODE_A2A_PUBLIC_URL} \
    --allow-remote \
    --no-task-store
