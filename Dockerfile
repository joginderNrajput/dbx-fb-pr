# REST API image: discovery + assessment + optional Postgres sink.
#   docker build -t dbx-premig:0.2.0 .
#   docker run -p 7073:7073 -e DBXF_DATABASE_URL=... dbx-premig:0.2.0
FROM python:3.12-slim AS build
WORKDIR /src
COPY pyproject.toml README.md discovery.py ./
COPY dbx_premig ./dbx_premig
RUN pip wheel --no-cache-dir --wheel-dir /wheels ".[api,postgres]"

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DBXF_API_WORK_DIR=/data/runs
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --uid 10001 --create-home app \
    && mkdir -p /data/runs && chown -R app /data
COPY --from=build /wheels /wheels
RUN pip install --no-index --find-links /wheels "dbx-premig[api,postgres]" && rm -rf /wheels
USER app
WORKDIR /data
EXPOSE 7073
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD curl -fsS "http://127.0.0.1:${DBXF_API_PORT:-7073}/healthz" || exit 1
ENTRYPOINT ["python", "-m", "dbx_premig"]
CMD ["serve", "--host", "0.0.0.0"]
