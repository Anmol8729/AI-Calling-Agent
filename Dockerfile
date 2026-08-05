# Clarivo API image.
#
# Previously: a single stage that ran as ROOT, kept `build-essential` (a full C
# toolchain) in the shipped image, and had no healthcheck. Combined with the
# missing .dockerignore, `COPY . .` also baked the real .env and the entire git
# history into the layer. .dockerignore now covers that; this file covers the rest.
#
# Two stages so compilers exist only where wheels are built and never ship.

# ---------- stage 1: build the dependency set ----------
FROM python:3.11-slim AS builder

# Some packages still need a compiler when no manylinux wheel matches the
# platform (notably on arm64). Present here, absent from the final image.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

# A self-contained venv is the easiest thing to copy cleanly between stages.
ENV VIRTUAL_ENV=/opt/venv
RUN python -m venv "$VIRTUAL_ENV"
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

# Requirements first so the dependency layer is cached across source changes.
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# ---------- stage 2: runtime ----------
FROM python:3.11-slim AS runtime

# Unbuffered so logs reach the container driver immediately; no .pyc clutter.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

# Run as an unprivileged account. Without this a container escape lands as root
# on the host kernel namespace, and any write bug can rewrite the app itself.
RUN groupadd --system --gid 1001 clarivo \
    && useradd --system --uid 1001 --gid clarivo --create-home clarivo

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv

# Source is owned by root and only readable by the app user, so the running
# process cannot modify its own code.
COPY --chown=root:clarivo . .
RUN chmod -R g=rX,o= /app

USER clarivo

EXPOSE 8000

# Mirrors the compose healthcheck so the image is self-describing when run
# without compose (plain `docker run`, ECS, Kubernetes, Fly, etc.).
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0) if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=5).status == 200 else sys.exit(1)"

# No --reload: it doubles memory, watches the filesystem, and is a dev feature.
# Scale with replicas rather than in-process workers — the notification event bus
# and reminder worker are still per-process (audit H3), so more than one worker
# per deployment breaks notifications and duplicates reminders until that lands.
CMD ["uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "8000"]
