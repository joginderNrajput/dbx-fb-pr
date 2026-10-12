"""Wire models of the REST API (kept separate from the domain models in models.py)."""

from __future__ import annotations

from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, SecretStr

__all__ = ["DatabricksRequest", "Health", "RunLinks", "RunStatus"]


class DatabricksRequest(BaseModel):
    """JSON body of POST /v1/assessments/databricks.

    Accepts camelCase and snake_case, and the key names used by Kanerika's platform
    (``workspaceId`` for the workspace URL, ``databricksCatalog`` / ``databricksSchema``).
    """

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    organization_id: str = Field(
        min_length=1,
        max_length=128,
        validation_alias=AliasChoices("organizationId", "organization_id"),
    )
    job_id: str = Field(
        min_length=1, max_length=128, validation_alias=AliasChoices("jobId", "job_id")
    )
    workspace_url: str = Field(
        min_length=4,
        max_length=512,
        validation_alias=AliasChoices("workspaceUrl", "workspaceId", "host", "workspace_url"),
    )
    token: SecretStr | None = None
    client_id: str | None = Field(
        default=None, max_length=256, validation_alias=AliasChoices("clientId", "client_id")
    )
    client_secret: SecretStr | None = Field(
        default=None, validation_alias=AliasChoices("clientSecret", "client_secret")
    )
    catalogs: list[str] | str | None = Field(
        default=None,
        validation_alias=AliasChoices("catalogs", "databricksCatalog", "databricks_catalog"),
    )
    schemas: list[str] | str | None = Field(
        default=None,
        validation_alias=AliasChoices("schemas", "databricksSchema", "databricks_schema"),
    )
    persist: bool | None = None
    wait: bool = False
    save_snapshot: bool = Field(
        default=False, validation_alias=AliasChoices("saveSnapshot", "save_snapshot")
    )  # fmt: skip


class RunLinks(BaseModel):
    status: str
    discovery_workbook: str | None = Field(default=None, serialization_alias="discoveryWorkbook")
    assessment_workbook: str | None = Field(default=None, serialization_alias="assessmentWorkbook")


class RunStatus(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    run_id: str = Field(serialization_alias="runId")
    status: str  # queued | running | succeeded | failed
    mode: str  # workbook | databricks
    organization_id: str = Field(serialization_alias="organizationId")
    job_id: str = Field(serialization_alias="jobId")
    created_at: str = Field(serialization_alias="createdAt")
    finished_at: str | None = Field(default=None, serialization_alias="finishedAt")
    error: str | None = None
    discovery: dict[str, Any] | None = None
    assessment: dict[str, Any] | None = None
    persisted: dict[str, Any] | None = None
    links: RunLinks


class Health(BaseModel):
    status: str
    version: str
    database: str
