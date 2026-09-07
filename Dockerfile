# The engine as an image. Two stages, because the build needs a compiler and the runtime does not,
# and the difference is a few hundred megabytes on every pull.
#
#   docker build -t orderorder .
#   docker run --rm -p 8000:8000 \
#       -e ORDERORDER_API_TOKEN=... \
#       -v /srv/orderorder-data:/data orderorder
#
# What is deliberately NOT in the image:
#
#   **The corpus.** 1.2 GB of SQLite, or a Postgres somewhere else. It is state, it outlives any
#   version of this code, and baking it in would mean rebuilding the image to ingest a judgment. It
#   arrives as a volume at /data, which `ORDERORDER_DATA_DIR` points at.
#
#   **Keys.** No ARG, no COPY of .env, nothing that ends up in a layer. A key baked into an image is a
#   key published to whoever can pull it, and `docker history` will show it even if a later layer
#   deletes the file. They come in as environment at run time.
#
# The image runs as a non-root user with no write access to its own code. The engine only ever writes
# to the data volume and to a temp dir, so nothing legitimate needs more than that, and a process that
# cannot rewrite its own source is one exploit less.

FROM python:3.12-slim AS build

# uv resolves and installs from the lockfile, so an image built today and one built in a month have
# the same dependency tree. Pinned by digest-bearing tag rather than :latest for the same reason.
COPY --from=ghcr.io/astral-sh/uv:0.9.7 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Dependencies first, in their own layer. They change when the lockfile changes; the source changes
# every commit, and rebuilding the dependency tree on every commit is minutes per build for nothing.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

COPY src ./src
COPY README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev


FROM python:3.12-slim AS runtime

# libgomp is what numpy and the static embedding model want at import time. Nothing else from the
# build stage is needed: no compiler, no uv, no cache.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 orderorder \
    && mkdir -p /data \
    && chown orderorder:orderorder /data

# /data has to exist in the image and be owned by the user that runs, which is not the same thing as
# mounting something there. `Settings.data_dir` creates the directory on first access, and uid 10001
# cannot create a directory in a root-owned `/`, so a container started without a volume dies on the
# first request rather than at boot. Creating it here also decides the ownership a *named* volume gets
# initialised with, which is what makes `docker run -v orderorder-data:/data` writable.
#
# A **bind** mount is the exception and cannot be fixed from in here: the host directory's ownership
# is what the container sees, so `chown 10001:10001` it on the host or the engine cannot write its
# corpus. DEPLOYMENT.md section 3 says so where the command is.

COPY --from=build --chown=root:root /app /app

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    ORDERORDER_DATA_DIR=/data \
    HF_HOME=/data/hf

WORKDIR /app
USER orderorder

EXPOSE 8000

# The health route is the one thing that answers without a token, which is exactly what a health
# check needs and the reason it was carved out.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status==200 else 1)"

# 0.0.0.0 inside a container is the only useful binding, and `serve` refuses it without a token. That
# refusal is the point: a container published to a host port with no token set should not come up.
ENTRYPOINT ["orderorder"]
CMD ["serve", "--host", "0.0.0.0", "--port", "8000"]
