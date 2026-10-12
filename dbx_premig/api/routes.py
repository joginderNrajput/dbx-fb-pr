"""HTTP routes: validation and plumbing only; every run goes through service.py."""

from __future__ import annotations

import asyncio
import secrets
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from dbx_premig.api.jobs import Run, RunConflict, RunExpired, RunStore
from dbx_premig.api.schemas import DatabricksRequest, Health, RunLinks, RunStatus
from dbx_premig.api.uploads import UploadRejected, save_upload
from dbx_premig.client import Credentials
from dbx_premig.config import Settings
from dbx_premig.errors import DiscoveryError
from dbx_premig.logging import get_logger
from dbx_premig.version import APP_VERSION

__all__ = ["build_router"]

log = get_logger("api")
_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _split(value: list[str] | str | None) -> tuple[str, ...] | None:
    if value is None:
        return None
    items = value if isinstance(value, list) else value.split(",")
    cleaned = tuple(v.strip() for v in items if v and v.strip())
    return cleaned or None


def _status(run: Run, base: str) -> RunStatus:
    prefix = f"{base}/v1/runs/{run.run_id}"
    return RunStatus(
        run_id=run.run_id,
        status=run.status,
        mode=run.mode,
        organization_id=run.organization_id,
        job_id=run.job_id,
        created_at=run.created_at,
        finished_at=run.finished_at,
        error=run.error,
        discovery=run.discovery,
        assessment=run.assessment,
        persisted=run.persisted,
        links=RunLinks(
            status=prefix,
            discovery_workbook=f"{prefix}/discovery" if run.discovery_workbook else None,
            assessment_workbook=f"{prefix}/assessment" if run.assessment_workbook else None,
        ),
    )


def _response(run: Run, request: Request, code: int) -> JSONResponse:
    base = str(request.base_url).rstrip("/")
    return JSONResponse(_status(run, base).model_dump(by_alias=True), status_code=code)


def _execute(
    run: Run,
    store: RunStore,
    settings: Settings,
    upload: Path | None,
    credentials: Credentials | None,
    persist: bool,
    save_snapshot: bool,
) -> None:
    """Worker thread body: discovery (if credentials) -> assessment -> optional persistence."""
    from dbx_premig.estimation import summarise
    from dbx_premig.service import run_assessment, run_discovery

    run.status = "running"
    log.info("run %s started (%s, org=%s, job=%s)", run.run_id, run.mode,
             run.organization_id, run.job_id)  # fmt: skip
    try:
        workbook = upload
        if credentials is not None:
            discovery = run_discovery(
                settings,
                input_path=None,
                output_dir=run.folder,
                keep_snapshot=save_snapshot,
                credentials=credentials,
            )
            s = summarise(discovery.report)
            run.discovery = {
                "assessableObjects": s.total_assets,
                "byReadiness": s.by_readiness,
                "byType": s.by_type,
                "warnings": s.warnings,
            }
            workbook = discovery.workbook
        run.discovery_workbook = workbook
        assert workbook is not None
        assessed = run_assessment(settings, discovery_workbook=workbook, output_dir=run.folder)
        run.assessment_workbook = assessed.workbook
        run.assessment = assessed.result.computation.model_dump()
        if run.discovery is None:
            run.discovery = {"counts": assessed.result.discovery.counts}
        else:
            run.discovery["counts"] = assessed.result.discovery.counts
        if persist:
            from dbx_premig.db.persist import persist_assessment

            outcome = persist_assessment(
                assessed.result, settings,
                organization_id=run.organization_id, job_id=run.job_id,
            )  # fmt: skip
            run.persisted = {
                "scanId": outcome.scan_id,
                "target": outcome.target,
                "rows": outcome.rows,
                "replacedPreviousRun": outcome.replaced_scans > 0,
            }
        store.finish(run, "succeeded")
    except DiscoveryError as exc:
        store.finish(run, "failed", exc.message)
    except Exception as exc:  # a bug: report only the class name, never client data
        log.exception("run %s failed", run.run_id)
        store.finish(run, "failed", f"Internal error ({type(exc).__name__}).")
    log.info("run %s %s", run.run_id, run.status)


def build_router(settings: Settings, store: RunStore, pool: ThreadPoolExecutor) -> APIRouter:
    router = APIRouter()

    def api_key(x_api_key: Annotated[str | None, Header()] = None) -> None:
        if settings.api_key is None:
            return
        if not x_api_key or not secrets.compare_digest(
            x_api_key.encode(), settings.api_key.get_secret_value().encode()
        ):
            raise HTTPException(401, "Missing or wrong X-API-Key.")

    def persist_flag(requested: bool | None) -> bool:
        configured = settings.database_url is not None
        if requested and not configured:
            raise HTTPException(503, "Persistence requested but no database is configured.")
        return configured if requested is None else requested

    async def submit(
        request: Request,
        run: Run,
        upload: Path | None,
        credentials: Credentials | None,
        persist: bool,
        save_snapshot: bool,
        wait: bool,
        run_settings: Settings,
    ) -> JSONResponse:
        future = pool.submit(
            _execute, run, store, run_settings, upload, credentials, persist, save_snapshot
        )
        if wait:
            await asyncio.wrap_future(future)
            return _response(run, request, 200 if run.status == "succeeded" else 422)
        return _response(run, request, 202)

    @router.get("/healthz", response_model=Health)
    def healthz() -> Health:
        from dbx_premig.db.engine import describe_target

        db = describe_target(settings) if settings.database_url else "not configured"
        return Health(status="ok", version=APP_VERSION, database=db)

    @router.post("/v1/assessments", dependencies=[Depends(api_key)])
    async def create_assessment(
        request: Request,
        organization_id: Annotated[str, Form(alias="organizationId", min_length=1, max_length=128)],
        job_id: Annotated[str, Form(alias="jobId", min_length=1, max_length=128)],
        file: Annotated[UploadFile | None, File(description="Discovery workbook")] = None,
        workspace_url: Annotated[str | None, Form(alias="workspaceUrl")] = None,
        token: Annotated[str | None, Form()] = None,
        client_id: Annotated[str | None, Form(alias="clientId")] = None,
        client_secret: Annotated[str | None, Form(alias="clientSecret")] = None,
        catalogs: Annotated[str | None, Form()] = None,
        schemas: Annotated[str | None, Form()] = None,
        persist: Annotated[bool | None, Form()] = None,
        wait: Annotated[bool, Form()] = False,
    ) -> JSONResponse:
        """Multipart: upload a discovery workbook (``file``) OR send Databricks credentials.

        With a workbook only the assessment runs. With credentials the discovery runs first
        and the assessment is computed on the workbook it produced.
        """
        if file is None and not workspace_url:
            raise HTTPException(422, "Send a discovery workbook (file) or Databricks credentials.")
        if file is not None and workspace_url:
            raise HTTPException(422, "Send either a workbook or credentials, not both.")
        do_persist = persist_flag(persist)
        credentials = None
        if workspace_url:
            credentials = _credentials(workspace_url, token, client_id, client_secret)
        run = _new_run(store, organization_id, job_id, "workbook" if file else "databricks")
        upload = None
        if file is not None:
            try:
                upload = await save_upload(file, run.folder, settings.max_upload_bytes)
            except UploadRejected as exc:
                store.finish(run, "failed", str(exc))
                raise HTTPException(exc.status, str(exc)) from None
        run_settings = _scoped(settings, catalogs, schemas)
        return await submit(request, run, upload, credentials, do_persist, False, wait,
                            run_settings)  # fmt: skip

    @router.post("/v1/assessments/databricks", dependencies=[Depends(api_key)])
    async def create_from_databricks(request: Request, body: DatabricksRequest) -> JSONResponse:
        """JSON: Databricks credentials -> discovery -> assessment (-> database)."""
        do_persist = persist_flag(body.persist)
        credentials = _credentials(
            body.workspace_url,
            body.token.get_secret_value() if body.token else None,
            body.client_id,
            body.client_secret.get_secret_value() if body.client_secret else None,
        )
        run = _new_run(store, body.organization_id, body.job_id, "databricks")
        run_settings = settings.model_copy(
            update={
                k: v
                for k, v in {
                    "catalogs": _split(body.catalogs),
                    "schemas": _split(body.schemas),
                }.items()
                if v is not None
            }
        )
        return await submit(request, run, None, credentials, do_persist, body.save_snapshot,
                            body.wait, run_settings)  # fmt: skip

    @router.get("/v1/runs/{run_id}", dependencies=[Depends(api_key)])
    def get_run(run_id: str, request: Request) -> JSONResponse:
        return _response(_lookup(store, run_id), request, 200)

    @router.get("/v1/runs/{run_id}/discovery", dependencies=[Depends(api_key)])
    def get_discovery(run_id: str) -> FileResponse:
        return _file(_lookup(store, run_id).discovery_workbook)

    @router.get("/v1/runs/{run_id}/assessment", dependencies=[Depends(api_key)])
    def get_assessment(run_id: str) -> FileResponse:
        return _file(_lookup(store, run_id).assessment_workbook)

    return router


def _credentials(
    url: str, token: str | None, client_id: str | None, client_secret: str | None
) -> Credentials:
    host = url.strip().rstrip("/")
    if not host.startswith(("https://", "http://")):
        host = "https://" + host
    if token:
        return Credentials(host, token, None, None, "request")
    if client_id and client_secret:
        return Credentials(host, None, client_id, client_secret, "request")
    raise HTTPException(422, "Send a token, or clientId and clientSecret, with the workspace URL.")


def _new_run(store: RunStore, org: str, job: str, mode: str) -> Run:
    try:
        return store.create(org, job, mode)
    except RunConflict as exc:
        raise HTTPException(
            409, f"Run {exc} for this organizationId / jobId is still in progress."
        ) from None


def _scoped(settings: Settings, catalogs: str | None, schemas: str | None) -> Settings:
    update: dict[str, Any] = {}
    if (c := _split(catalogs)) is not None:
        update["catalogs"] = c
    if (s := _split(schemas)) is not None:
        update["schemas"] = s
    return settings.model_copy(update=update) if update else settings


def _lookup(store: RunStore, run_id: str) -> Run:
    try:
        run = store.get(run_id)
    except RunExpired:
        raise HTTPException(410, "This run has expired; its workbooks were deleted.") from None
    if run is None:
        raise HTTPException(404, "Unknown run id.")
    return run


def _file(path: Path | None) -> FileResponse:
    if path is None or not path.is_file():
        raise HTTPException(404, "This workbook is not available (yet).")
    return FileResponse(path, media_type=_XLSX, filename=path.name)
