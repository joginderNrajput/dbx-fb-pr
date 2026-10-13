"""``create_app(settings)``: the FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from dbx_premig.api.jobs import RunStore
from dbx_premig.api.routes import build_router
from dbx_premig.config import Settings, get_settings
from dbx_premig.version import APP_NAME, APP_VERSION

__all__ = ["create_app"]


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    store = RunStore(settings.api_work_dir.resolve(), settings.api_run_ttl_s)
    pool = ThreadPoolExecutor(max_workers=settings.api_max_workers, thread_name_prefix="run")

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        if settings.database_url is not None and settings.db_auto_migrate:
            from dbx_premig.db.engine import migrate

            migrate(settings)  # fail fast: the API does not start on a database it cannot use
        yield
        pool.shutdown(wait=False, cancel_futures=True)

    app = FastAPI(
        title=f"{APP_NAME} API",
        version=APP_VERSION,
        description=(
            "Upload a Databricks discovery workbook, or send Databricks credentials, and get a "
            "Microsoft Fabric migration assessment (Excel + optional Postgres tables)."
        ),
        lifespan=lifespan,
    )
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(settings.cors_origins),
            allow_methods=["GET", "POST"],
            allow_headers=["*"],
        )
    app.include_router(build_router(settings, store, pool))
    app.state.store = store
    app.state.settings = settings
    return app
