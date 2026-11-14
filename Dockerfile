# Disputes platform image (SYNTHETIC DEMO ONLY). One image for every process:
#   web     : python -m disputes.cli serve --host 0.0.0.0 --port 8000     (default CMD)
#   worker  : python -m disputes.cli work --loop
#   one-shot: python /app/deploy/bootstrap.py   (migrate, demo users, synthetic disputes; idempotent)
#
# Base image: pinned to an exact Python patch release on Debian trixie (matches the 3.13.18 interpreter the test suite runs on; tag seen on Docker Hub 2026-11-14). To pin by digest as well
# (recommended before any hosted use), resolve it with
#   docker buildx imagetools inspect python:3.13.18-slim-trixie
# and build with --build-arg PYTHON_IMAGE=python:3.13.18-slim-trixie@sha256:<digest>.
# (The digest was not resolved when this file was written: the build sandbox could not reach any
#  container registry. See docs/engineering/stage-notes/deploy.md.)
ARG PYTHON_IMAGE=python:3.13.18-slim-trixie

FROM ${PYTHON_IMAGE} AS build
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
COPY src/requirements.txt /tmp/requirements.txt
# Every runtime dependency is pinned in requirements.txt; --no-deps refuses anything unpinned.
RUN python -m venv /opt/venv && /opt/venv/bin/pip install --no-deps -r /tmp/requirements.txt

FROM ${PYTHON_IMAGE}
LABEL org.opencontainers.image.title="disputes-platform (synthetic demo)" \
      org.opencontainers.image.description="Furnisher dispute platform. SYNTHETIC DATA ONLY."
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONPATH=/app/src \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    # Safe by default: hosted-mode checks are ON unless an operator explicitly sets DISPUTES_ENV=dev
    # (the local compose stack does). See src/disputes/hosting.py.
    DISPUTES_ENV=demo \
    DISPUTES_LLM_BACKEND=offline \
    DISPUTES_ANCHOR_DIR=/app/var/anchors
RUN groupadd --system --gid 10001 app \
 && useradd --system --uid 10001 --gid app --home-dir /app --no-create-home --shell /usr/sbin/nologin app
COPY --from=build /opt/venv /opt/venv
WORKDIR /app/src
COPY --chown=root:root src/disputes /app/src/disputes
COPY --chown=root:root src/disputes_core /app/src/disputes_core
COPY --chown=root:root src/prompts /app/src/prompts
COPY --chown=root:root src/data/fixtures /app/src/data/fixtures
COPY --chown=root:root deploy/bootstrap.py /app/deploy/bootstrap.py
# Code is root-owned and read-only to the app user; only /app/var is writable.
RUN mkdir -p /app/var/anchors && chown -R app:app /app/var
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=3 \
  CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2).status == 200 else 1)"]
CMD ["python", "-m", "disputes.cli", "serve", "--host", "0.0.0.0", "--port", "8000"]
