"""Frozen domain model (pydantic v2).

To change a model, add a field; never mutate an instance. Wire schemas for a future API live
in ``api/schemas.py`` and are kept separate from these classes.

Shape of the pipeline:

``RawSnapshot`` (what the collector or the offline reader produced, plain JSON)
  -> ``parser`` -> ``Estate`` (typed inventory rows per worksheet + one ``AssetRecord`` per
     assessable object with the source features it uses)
  -> ``estimation`` -> ``AssetAssessment`` per asset (readiness, Fabric target, findings)
  -> ``DiscoveryReport`` (everything the discovery workbook renders)
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

from dbx_premig.version import APP_VERSION

__all__ = [
    "AlertRow",
    "AssessmentResult",
    "AssetAssessment",
    "AssetInput",
    "AssetRecord",
    "CatalogRow",
    "ClusterPolicyRow",
    "ClusterRow",
    "ColumnRow",
    "Computation",
    "ConnectionRow",
    "DashboardRow",
    "DependencyRow",
    "DiscoveryReport",
    "DiscoveryWorkbook",
    "Estate",
    "EstimationRow",
    "ExperimentRow",
    "ExternalLocationRow",
    "FeatureHit",
    "FileRef",
    "Finding",
    "FunctionRow",
    "GrantRow",
    "IdentityRow",
    "InstancePoolRow",
    "JobRow",
    "JobTaskRow",
    "LibraryRow",
    "ModelRow",
    "MountRow",
    "NotebookRow",
    "PipelineRow",
    "QueryRow",
    "RawSnapshot",
    "RepoRow",
    "ScanInfo",
    "SchemaRow",
    "SecretScopeRow",
    "ServingEndpointRow",
    "StorageCredentialRow",
    "TableRow",
    "ViewRow",
    "VolumeRow",
    "WarehouseRow",
    "WarningRow",
]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


# --------------------------------------------------------------------------- input


class FileRef(_Frozen):
    """One offline input file found by ``discovery.find_inputs``."""

    path: str
    relative_path: str
    kind: str  # source | ipynb | dbc | zip | snapshot
    size_bytes: int


class RawSnapshot(_Frozen):
    """Plain-JSON capture of a workspace: one list of raw API objects per section.

    Produced by the live collector or by the offline reader, saved with ``--save-snapshot``
    and re-read with ``--input snapshot.json``. The parser is the only consumer.
    """

    format_version: int = 1
    tool_version: str = APP_VERSION
    mode: str  # live | offline
    source: str  # workspace host or input path (display only)
    captured_at: str
    meta: dict[str, Any] = Field(default_factory=dict)
    sections: dict[str, list[Any]] = Field(default_factory=dict)  # parser keeps dicts only
    warnings: list[dict[str, str]] = Field(default_factory=list)


# --------------------------------------------------------------------------- features


class FeatureHit(_Frozen):
    """A source feature the parser saw on an asset, and how often."""

    feature_id: str
    occurrences: int = 1


class AssetRecord(_Frozen):
    """One assessable object, with the features that drive its readiness."""

    key: str
    asset_type: str
    name: str
    location: str = ""
    features: tuple[FeatureHit, ...] = ()


class Finding(_Frozen):
    """A feature resolved against the support catalog."""

    feature_id: str
    category: str
    occurrences: int
    penalty: int
    support: str  # supported | partial | manual | unsupported | unknown
    guidance: str


class AssetAssessment(_Frozen):
    """Readiness of one asset. Informational classification, not an hours estimate."""

    key: str
    asset_type: str
    name: str
    location: str
    fabric_target: str
    readiness_score: int
    readiness: str  # Compatible | Partial | Manual | Unsupported
    findings: tuple[Finding, ...] = ()

    @property
    def finding_ids(self) -> str:
        return ", ".join(f.feature_id for f in self.findings)


# --------------------------------------------------------------------------- inventory rows


class NotebookRow(_Frozen):
    asset_key: str
    path: str
    name: str
    folder: str
    area: str  # Users | Shared | Repos | Workspace | Offline
    object_type: str  # NOTEBOOK | FILE
    language: str
    lines: int
    cells: int
    size_bytes: int
    magic_commands: int
    sql_statements: int
    runs_notebooks: int
    scanned: bool
    modified_at: str = ""


class DependencyRow(_Frozen):
    from_type: str
    from_name: str
    relation: str
    to: str
    resolved: bool


class JobRow(_Frozen):
    asset_key: str
    job_id: str
    name: str
    creator: str
    created_at: str
    tasks: int
    task_types: str
    schedule: str
    timezone: str
    pause_status: str
    trigger: str
    continuous: bool
    job_clusters: int
    notifications: bool
    max_concurrent_runs: int
    timeout_s: int
    tags: str
    run_as: str


class JobTaskRow(_Frozen):
    job_id: str
    job_name: str
    task_key: str
    task_type: str
    target: str
    depends_on: str
    compute: str
    libraries: int
    max_retries: int
    timeout_s: int
    fabric_activity: str


class ClusterRow(_Frozen):
    asset_key: str
    cluster_id: str
    name: str
    source: str
    state: str
    runtime: str
    node_type: str
    driver_node_type: str
    workers: str
    autotermination_min: int
    access_mode: str
    photon: bool
    init_scripts: int
    docker: bool
    gpu: bool
    spark_conf: int
    databricks_conf: int
    custom_tags: int
    policy_id: str
    creator: str


class InstancePoolRow(_Frozen):
    pool_id: str
    name: str
    node_type: str
    min_idle: int
    max_capacity: int
    idle_autotermination_min: int
    preloaded_runtimes: str
    state: str


class ClusterPolicyRow(_Frozen):
    policy_id: str
    name: str
    family: str
    rules: int
    creator: str
    created_at: str


class WarehouseRow(_Frozen):
    asset_key: str
    warehouse_id: str
    name: str
    size: str
    warehouse_type: str
    serverless: bool
    min_clusters: int
    max_clusters: int
    auto_stop_min: int
    photon: bool
    channel: str
    state: str
    creator: str


class PipelineRow(_Frozen):
    asset_key: str
    pipeline_id: str
    name: str
    state: str
    catalog: str
    target_schema: str
    edition: str
    continuous: bool
    serverless: bool
    photon: bool
    development: bool
    channel: str
    libraries: int
    notebooks: str
    creator: str


class CatalogRow(_Frozen):
    name: str
    catalog_type: str
    owner: str
    storage_root: str
    isolation_mode: str
    comment: str
    created_at: str


class SchemaRow(_Frozen):
    catalog: str
    schema_name: str
    full_name: str
    owner: str
    comment: str
    created_at: str


class TableRow(_Frozen):
    asset_key: str
    catalog: str
    schema_name: str
    name: str
    full_name: str
    table_type: str
    data_format: str
    columns: int
    partition_columns: str
    storage_location: str
    owner: str
    created_at: str
    updated_at: str
    change_data_feed: bool
    deletion_vectors: bool
    row_filter: bool
    column_masks: int
    special_types: str
    comment: str


class ColumnRow(_Frozen):
    table: str
    position: int
    name: str
    data_type: str
    nullable: bool
    partition_index: str
    masked: bool
    comment: str


class ViewRow(_Frozen):
    full_name: str
    view_type: str
    definition_chars: int
    references: int
    definition: str


class VolumeRow(_Frozen):
    asset_key: str
    full_name: str
    catalog: str
    schema_name: str
    name: str
    volume_type: str
    storage_location: str
    owner: str


class ExternalLocationRow(_Frozen):
    asset_key: str
    name: str
    url: str
    credential: str
    read_only: bool
    owner: str
    comment: str


class StorageCredentialRow(_Frozen):
    asset_key: str
    name: str
    credential_type: str
    owner: str
    read_only: bool
    comment: str


class ConnectionRow(_Frozen):
    asset_key: str
    name: str
    connection_type: str
    owner: str
    read_only: bool
    comment: str
    created_at: str


class FunctionRow(_Frozen):
    asset_key: str
    full_name: str
    catalog: str
    schema_name: str
    name: str
    language: str
    return_type: str
    parameters: str
    table_function: bool
    body_chars: int


class GrantRow(_Frozen):
    securable_type: str
    securable: str
    principal: str
    privileges: str


class QueryRow(_Frozen):
    asset_key: str
    query_id: str
    name: str
    owner: str
    warehouse_id: str
    lines: int
    updated_at: str


class DashboardRow(_Frozen):
    asset_key: str
    dashboard_id: str
    name: str
    kind: str
    path: str
    warehouse_id: str
    state: str
    created_at: str
    updated_at: str


class AlertRow(_Frozen):
    asset_key: str
    alert_id: str
    name: str
    query_id: str
    state: str
    owner: str


class ModelRow(_Frozen):
    asset_key: str
    full_name: str
    catalog: str
    schema_name: str
    name: str
    owner: str
    created_at: str
    updated_at: str


class ServingEndpointRow(_Frozen):
    asset_key: str
    name: str
    state: str
    task: str
    served_entities: str
    entity_types: str
    creator: str


class ExperimentRow(_Frozen):
    experiment_id: str
    name: str
    lifecycle_stage: str
    last_update: str


class LibraryRow(_Frozen):
    asset_key: str
    kind: str
    name: str
    clusters: int
    cluster_names: str


class SecretScopeRow(_Frozen):
    asset_key: str
    scope: str
    backend: str
    secrets: int
    keys: str


class MountRow(_Frozen):
    asset_key: str
    mount_point: str


class RepoRow(_Frozen):
    asset_key: str
    repo_id: str
    path: str
    url: str
    provider: str
    branch: str


class IdentityRow(_Frozen):
    identity_type: str  # User | Group | Service principal
    name: str
    identifier: str
    active: bool
    groups: int
    members: int


class WarningRow(_Frozen):
    source: str
    message: str


class ScanInfo(_Frozen):
    """What was scanned: shown on the Discovery and Information sheets."""

    mode: str
    source: str
    cloud: str = ""
    workspace_id: str = ""
    metastore: str = ""
    collectors: tuple[str, ...] = ()
    captured_at: str = ""
    generated_at: str = ""


class Estate(_Frozen):
    """Everything the parser found, as rows ready for the workbook."""

    notebooks: tuple[NotebookRow, ...] = ()
    dependencies: tuple[DependencyRow, ...] = ()
    jobs: tuple[JobRow, ...] = ()
    job_tasks: tuple[JobTaskRow, ...] = ()
    clusters: tuple[ClusterRow, ...] = ()
    instance_pools: tuple[InstancePoolRow, ...] = ()
    cluster_policies: tuple[ClusterPolicyRow, ...] = ()
    warehouses: tuple[WarehouseRow, ...] = ()
    pipelines: tuple[PipelineRow, ...] = ()
    catalogs: tuple[CatalogRow, ...] = ()
    schemas: tuple[SchemaRow, ...] = ()
    tables: tuple[TableRow, ...] = ()
    columns: tuple[ColumnRow, ...] = ()
    views: tuple[ViewRow, ...] = ()
    volumes: tuple[VolumeRow, ...] = ()
    external_locations: tuple[ExternalLocationRow, ...] = ()
    storage_credentials: tuple[StorageCredentialRow, ...] = ()
    connections: tuple[ConnectionRow, ...] = ()
    functions: tuple[FunctionRow, ...] = ()
    grants: tuple[GrantRow, ...] = ()
    queries: tuple[QueryRow, ...] = ()
    dashboards: tuple[DashboardRow, ...] = ()
    alerts: tuple[AlertRow, ...] = ()
    models: tuple[ModelRow, ...] = ()
    serving_endpoints: tuple[ServingEndpointRow, ...] = ()
    experiments: tuple[ExperimentRow, ...] = ()
    libraries: tuple[LibraryRow, ...] = ()
    secret_scopes: tuple[SecretScopeRow, ...] = ()
    mounts: tuple[MountRow, ...] = ()
    repos: tuple[RepoRow, ...] = ()
    identities: tuple[IdentityRow, ...] = ()
    assets: tuple[AssetRecord, ...] = ()
    warnings: tuple[WarningRow, ...] = ()


class DiscoveryReport(_Frozen):
    """The discovery workbook's content: the estate plus a readiness classification."""

    tool_version: str = APP_VERSION
    scan: ScanInfo
    estate: Estate
    assessments: tuple[AssetAssessment, ...] = ()

    _by_key: dict[str, AssetAssessment] = PrivateAttr(default_factory=dict)

    def assessment_for(self, key: str) -> AssetAssessment | None:
        """The assessment of the asset with this key (index built on first use)."""
        if not self._by_key and self.assessments:
            self._by_key.update({a.key: a for a in self.assessments})
        return self._by_key.get(key)


# --------------------------------------------------------------------------- assessment


class AssetInput(_Frozen):
    """One assessable object read back from a discovery workbook (Assets + Findings rows)."""

    key: str
    asset_type: str
    name: str
    location: str = ""
    fabric_target: str = ""
    readiness_score: int = 100
    readiness: str = "Compatible"
    findings: tuple[Finding, ...] = ()
    metrics: dict[str, float] = Field(default_factory=dict)


class DiscoveryWorkbook(_Frozen):
    """What ``assess`` reads: the discovery workbook's rows, with every total recomputed."""

    file_name: str
    scan: ScanInfo
    assets: tuple[AssetInput, ...]
    counts: dict[str, float]


class EstimationRow(_Frozen):
    """Per-asset assessment (one row on Estimation, one row in the estimation table)."""

    asset_key: str
    asset_type: str
    asset_name: str
    location: str
    fabric_target: str
    readiness: str
    readiness_score: int
    total_constructs: int
    supported: float
    unsupported: float
    complexity_score: int
    complexity_level: str  # Simple | Medium | Complex
    automation_level: str  # Fully automated | Partially automated | Manual
    manual_dev_hours: float
    manual_test_hours: float
    automation_dev_hours: float
    automation_test_hours: float
    hours_saved: float

    @property
    def total_manual_hours(self) -> float:
        return self.manual_dev_hours + self.manual_test_hours

    @property
    def total_automation_hours(self) -> float:
        return self.automation_dev_hours + self.automation_test_hours


class Computation(_Frozen):
    """Portfolio roll-up (one row in the computation table). Sums of rounded asset figures."""

    assessment_generated_at: str
    total_assets: int
    total_constructs: int
    supported_constructs: float
    unsupported_constructs: float
    simple_count: int
    medium_count: int
    complex_count: int
    fully_automated: int
    partially_automated: int
    manual: int
    manual_dev_hours: float
    manual_test_hours: float
    total_manual_hours: float
    automation_dev_hours: float
    automation_test_hours: float
    total_automation_hours: float
    hours_saved: float
    saving_pct: float  # fraction 0-1
    rules_version: str


class AssessmentResult(_Frozen):
    tool_version: str = APP_VERSION
    discovery: DiscoveryWorkbook
    estimations: tuple[EstimationRow, ...]
    computation: Computation
