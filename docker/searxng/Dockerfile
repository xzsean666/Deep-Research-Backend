# SearXNG's own build is split across container/builder.dockerfile and
# container/dist.dockerfile, where dist.dockerfile's first stage is just
# `FROM localhost/searxng/searxng:builder` — i.e. it expects the builder
# image to already exist as a separately-tagged local image. Plain
# `docker compose build` can't express that two-image dependency, so this
# file merges both stages into one multi-stage build using a named stage
# instead of a pre-tagged image. Content otherwise matches upstream as of
# the pinned commit in vendor/searxng — see ARCHITECTURE.md §13.2 and
# BUILD.md §10.2 for the upgrade procedure (re-diff against upstream's
# two files when bumping the pinned commit).
#
# Build context MUST be vendor/searxng (the repo root), not this directory:
# docker-compose.yml sets `context: ./vendor/searxng, dockerfile: ../../docker/searxng/Dockerfile`.

FROM docker.io/searxng/base:searxng-builder AS builder

COPY ./requirements.txt ./requirements-server.txt ./

ENV UV_NO_MANAGED_PYTHON="true"
ENV UV_NATIVE_TLS="true"

ARG TIMESTAMP_VENV="0"

RUN --mount=type=cache,id=uv,target=/root/.cache/uv set -eux -o pipefail; \
    export SOURCE_DATE_EPOCH="$TIMESTAMP_VENV"; \
    uv venv; \
    uv pip install --requirements ./requirements.txt --requirements ./requirements-server.txt; \
    uv cache prune --ci; \
    find ./.venv/lib/ -type f -exec strip --strip-unneeded {} + || true; \
    find ./.venv/lib/ -type d -name "__pycache__" -exec rm -rf {} +; \
    find ./.venv/lib/ -type f -name "*.pyc" -delete; \
    python -m compileall -q -f -j 0 --invalidation-mode=unchecked-hash ./.venv/lib/; \
    find ./.venv/lib/python*/site-packages/*.dist-info/ -type f -name "RECORD" -exec sort -t, -k1,1 -o {} {} \;; \
    find ./.venv/ -exec touch -h --date="@$TIMESTAMP_VENV" {} +

COPY --exclude=./searx/version_frozen.py ./searx/ ./searx/

RUN set -eux -o pipefail; \
    python -m compileall -q -f -j 0 --invalidation-mode=unchecked-hash ./searx/; \
    find ./searx/static/ -type f \
    \( -name "*.html" -o -name "*.css" -o -name "*.js" -o -name "*.svg" \) \
    -exec gzip -9 -k {} + \
    -exec brotli -9 -k {} + \
    -exec gzip --test {}.gz + \
    -exec brotli --test {}.br +

FROM docker.io/searxng/base:searxng AS dist

COPY --chown=977:977 --from=builder /usr/local/searxng/.venv/ ./.venv/
COPY --chown=977:977 --from=builder /usr/local/searxng/searx/ ./searx/
COPY --chown=977:977 ./container/ ./
COPY --chown=977:977 ./searx/version_frozen.py ./searx/

ENV __SEARXNG_SETTINGS_PATH="$__SEARXNG_CONFIG_PATH/settings.yml" \
    GRANIAN_PROCESS_NAME="searxng" \
    GRANIAN_INTERFACE="wsgi" \
    GRANIAN_HOST="::" \
    GRANIAN_PORT="8080" \
    GRANIAN_WEBSOCKETS="false" \
    GRANIAN_BLOCKING_THREADS="4" \
    GRANIAN_WORKERS_KILL_TIMEOUT="30s" \
    GRANIAN_BLOCKING_THREADS_IDLE_TIMEOUT="5m"

VOLUME $__SEARXNG_CONFIG_PATH
VOLUME $__SEARXNG_DATA_PATH

EXPOSE 8080

ENTRYPOINT ["/usr/local/searxng/entrypoint.sh"]
