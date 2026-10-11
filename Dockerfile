# syntax=docker/dockerfile:1
#
# yt-dl : image de production (un seul process uvicorn, utilisateur non-root).
#   make build   (ou : docker compose build)

ARG PYTHON_VERSION=3.12

# --- 1. Dépendances Python, figées par uv.lock -------------------------------
FROM ghcr.io/astral-sh/uv:0.10 AS uv
FROM python:${PYTHON_VERSION}-slim-trixie AS builder

COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv

WORKDIR /src
COPY pyproject.toml uv.lock ./
# --frozen : échoue si uv.lock ne correspond plus à pyproject.toml
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

# --- 2. Image finale ---------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim-trixie AS runtime

# ffmpeg : fusion vidéo/audio, sous-titres, conversion audio
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg \
 && rm -rf /var/lib/apt/lists/*

# Même UID que l'utilisateur de l'hôte (make build le passe) : les secrets
# montés en lecture seule restent lisibles sans les ouvrir à tout le monde.
ARG APP_UID=10001
ARG APP_GID=10001
RUN groupadd --system --gid ${APP_GID} app \
 && useradd --system --uid ${APP_UID} --gid app --home-dir /nonexistent --shell /usr/sbin/nologin app \
 && mkdir -p /data/jobs \
 && chown -R app:app /data

COPY --from=builder /opt/venv /opt/venv
WORKDIR /app
COPY app ./app

ENV PATH=/opt/venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    # Pas d'authentification = refus de démarrer (fail closed)
    REQUIRE_AUTH=1 \
    OAUTH_STATE_DB=/data/oauth_state.sqlite3 \
    JOBS_DIR=/data/jobs \
    # deno (fourni par le paquet PyPI) écrit son cache ici
    DENO_DIR=/tmp/deno \
    XDG_CACHE_HOME=/tmp/cache \
    # uvicorn ne fait confiance aux en-têtes X-Forwarded-* que de ces adresses
    FORWARDED_ALLOW_IPS=127.0.0.1

USER app
EXPOSE 8765
VOLUME ["/data"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD ["python", "-c", "import urllib.request,sys; sys.exit(urllib.request.urlopen('http://127.0.0.1:8765/api/health', timeout=4).status != 200)"]

# Un seul worker : l'état des téléchargements vit en mémoire (app/jobs.py).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8765", \
     "--proxy-headers", "--no-server-header", "--workers", "1"]
