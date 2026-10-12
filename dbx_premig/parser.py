"""Raw snapshot -> ``Estate``: typed inventory rows plus per-asset feature hits.

The parser walks the real structure of each API object (``settings.tasks[]``,
``columns[]`` ...); it never searches documents generically. It does not look up support
verdicts: it only records which features an asset uses. The rules it applies (code patterns,
job task types) are injected as ``ParserRules`` by the service.

Rows are sorted explicitly so the same snapshot always produces the same workbook.
"""

from __future__ import annotations

import posixpath
import re
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from dbx_premig.config import Settings
from dbx_premig.models import (
    AlertRow,
    AssetRecord,
    CatalogRow,
    ClusterPolicyRow,
    ClusterRow,
    ColumnRow,
    ConnectionRow,
    DashboardRow,
    DependencyRow,
    Estate,
    ExperimentRow,
    ExternalLocationRow,
    FeatureHit,
    FunctionRow,
    GrantRow,
    IdentityRow,
    InstancePoolRow,
    JobRow,
    JobTaskRow,
    LibraryRow,
    ModelRow,
    MountRow,
    NotebookRow,
    PipelineRow,
    QueryRow,
    RawSnapshot,
    RepoRow,
    SchemaRow,
    SecretScopeRow,
    ServingEndpointRow,
    StorageCredentialRow,
    TableRow,
    ViewRow,
    VolumeRow,
    WarehouseRow,
    WarningRow,
)

__all__ = ["ParserRules", "asset_key", "normalise_path", "parse_snapshot"]

Raw = dict[str, Any]

_EPHEMERAL_CLUSTER_SOURCES = {"JOB", "PIPELINE", "PIPELINE_MAINTENANCE", "MODELS"}
_SPECIAL_TYPES = {"VARIANT", "INTERVAL", "GEOGRAPHY", "GEOMETRY", "OBJECT"}
_LIB_KINDS = ("pypi", "requirements", "whl", "jar", "cran", "maven", "egg")
_RUN_RE = re.compile(r"^\s*(?:#|--|//)?\s*(?:MAGIC\s+)?%run\s+(\S+)", re.MULTILINE)
_NB_RUN_RE = re.compile(r"dbutils\.notebook\.run\(\s*[\"']([^\"']+)[\"']")
_MAGIC_RE = re.compile(r"^\s*(?:(?:#|--|//)\s*MAGIC\s+)?%[a-z]+", re.MULTILINE | re.IGNORECASE)
_SQL_STMT_RE = re.compile(
    r"^\s*(?:(?:--|#)\s*MAGIC\s+)?(SELECT|INSERT|MERGE|CREATE|UPDATE|DELETE|WITH|ALTER|DROP|"
    r"OPTIMIZE|COPY|TRUNCATE|VACUUM)\b",
    re.MULTILINE | re.IGNORECASE,
)
_SPARK_SQL_RE = re.compile(r"spark\.sql\(")
_THREE_PART_RE = re.compile(r"\b\w+\.\w+\.\w+\b")
_GPU_RE = re.compile(r"\b(NC|ND|NV)\d|^g[4-6]|^p[3-5]|gpu", re.IGNORECASE)
_SEPARATOR_RE = re.compile(r"^(?:#|--|//) COMMAND ----------\s*$", re.MULTILINE)


@dataclass(frozen=True)
class ParserRules:
    """What the parser is told to look for (built from the catalog by the service)."""

    code_patterns: tuple[tuple[str, re.Pattern[str]], ...]
    task_features: dict[str, str | None]
    task_activities: dict[str, str]
    occurrence_cap: int = 10


# --------------------------------------------------------------------------- helpers


def _s(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "Yes" if value else "No"
    return str(value)


def _i(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _b(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"true", "yes", "1"}
    return bool(value)


def _ts(value: Any) -> str:
    """Epoch milliseconds or ISO text -> 'YYYY-MM-DD HH:MM' (UTC)."""
    if value in (None, "", 0):
        return ""
    if isinstance(value, int | float) or (isinstance(value, str) and value.isdigit()):
        try:
            return datetime.fromtimestamp(int(value) / 1000, tz=UTC).strftime("%Y-%m-%d %H:%M")
        except (OverflowError, OSError, ValueError):
            return ""
    text = str(value)
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return text[:16]


def _dicts(value: Any) -> list[Raw]:
    return [v for v in value if isinstance(v, dict)] if isinstance(value, list) else []


def _d(value: Any) -> Raw:
    return value if isinstance(value, dict) else {}


def asset_key(asset_type: str, identity: str) -> str:
    return f"{asset_type}:{identity}"


def normalise_path(path: str, base: str = "") -> str:
    """'/Workspace/Shared/x' -> '/Shared/x'; resolve ./ and ../ against the caller's folder."""
    p = (path or "").strip().strip("\"'")
    if p.startswith("/Workspace/"):
        p = p[len("/Workspace") :]
    if p and not p.startswith("/") and base.startswith("/"):
        p = posixpath.normpath(posixpath.join(posixpath.dirname(base), p))
    for ext in (".py", ".sql", ".scala", ".r", ".ipynb"):
        if p.lower().endswith(ext):
            p = p[: -len(ext)]
            break
    return p


def _sorted(rows: Iterable[Any], key: Callable[[Any], tuple[str, ...]]) -> tuple[Any, ...]:
    return tuple(sorted(rows, key=key))


def _fold(*parts: str) -> tuple[str, ...]:
    return tuple(p.casefold() for p in parts) + parts


@dataclass
class _Ctx:
    rules: ParserRules
    settings: Settings
    assets: list[AssetRecord] = field(default_factory=list)
    deps: list[tuple[str, str, str, str]] = field(default_factory=list)
    warnings: list[WarningRow] = field(default_factory=list)

    def scan(self, text: str) -> Counter[str]:
        hits: Counter[str] = Counter()
        if not text:
            return hits
        for fid, rx in self.rules.code_patterns:
            n = len(rx.findall(text))
            if n:
                hits[fid] += n
        return hits

    def asset(
        self,
        asset_type: str,
        identity: str,
        name: str,
        location: str,
        features: Counter[str] | Iterable[str],
    ) -> str:
        key = asset_key(asset_type, identity)
        counts = features if isinstance(features, Counter) else Counter(features)
        hits = tuple(
            FeatureHit(feature_id=fid, occurrences=min(n, 10**6))
            for fid, n in sorted(counts.items())
            if n > 0
        )
        self.assets.append(
            AssetRecord(key=key, asset_type=asset_type, name=name, location=location, features=hits)
        )
        return key


# --------------------------------------------------------------------------- notebooks


def _area(path: str, origin: str) -> str:
    if origin == "offline":
        return "Offline export"
    parts = [p for p in path.split("/") if p]
    head = parts[0] if parts else ""
    return head if head in {"Users", "Shared", "Repos", "Workspace"} else "Workspace root"


def _notebooks(ctx: _Ctx, items: list[Raw]) -> list[NotebookRow]:
    rows: list[NotebookRow] = []
    for nb in items:
        raw_path = _s(nb.get("path"))
        origin = _s(nb.get("origin")) or "workspace"
        path = normalise_path(raw_path) if origin != "offline" else raw_path
        source = nb.get("source")
        text = source if isinstance(source, str) else ""
        language = _s(nb.get("language")).upper()
        name = path.rsplit("/", 1)[-1].split("!/")[-1].rsplit("/", 1)[-1]
        folder = path[: len(path) - len(name)].rstrip("/") or "/"
        lines = text.count("\n") + 1 if text else 0
        cells = _i(nb.get("cells")) or (len(_SEPARATOR_RE.findall(text)) + 1 if text else 0)
        runs: list[str] = []
        base = path if origin != "offline" else ""
        for m in _RUN_RE.finditer(text):
            runs.append(normalise_path(m.group(1), base))
        for m in _NB_RUN_RE.finditer(text):
            runs.append(normalise_path(m.group(1), base))
        features = ctx.scan(text)
        if language == "SCALA":
            features["LANG-SCALA"] += 1
        elif language == "R":
            features["LANG-R"] += 1
        if not text:
            features["NB-NOT-SCANNED"] = 1
        key = ctx.asset("Notebook", path, name, path, features)
        for target in runs:
            ctx.deps.append(("Notebook", path, "runs notebook", target))
        if nb.get("skipped_reason"):
            ctx.warnings.append(
                WarningRow(source=path, message=f"Not scanned: {nb['skipped_reason']}.")
            )
        sql_statements = len(_SQL_STMT_RE.findall(text)) + len(_SPARK_SQL_RE.findall(text))
        rows.append(
            NotebookRow(
                asset_key=key,
                path=path,
                name=name,
                folder=folder,
                area=_area(path, origin),
                object_type=_s(nb.get("object_type")) or "NOTEBOOK",
                language=language or "UNKNOWN",
                lines=lines,
                cells=cells,
                size_bytes=_i(nb.get("size")) or len(text.encode("utf-8")),
                magic_commands=len(_MAGIC_RE.findall(text)),
                sql_statements=sql_statements,
                runs_notebooks=len(runs),
                scanned=bool(text),
                modified_at=_ts(nb.get("modified_at")),
            )
        )
    return list(_sorted(rows, key=lambda r: _fold(r.path)))


# --------------------------------------------------------------------------- jobs


def _task_type(task: Raw) -> str:
    for k in task:
        if k.endswith("_task") and isinstance(task[k], dict):
            return k
    return "unknown_task"


def _task_target(kind: str, body: Raw) -> str:
    if kind == "notebook_task":
        return normalise_path(_s(body.get("notebook_path")))
    if kind == "spark_python_task":
        return _s(body.get("python_file"))
    if kind == "python_wheel_task":
        return f"{_s(body.get('package_name'))}:{_s(body.get('entry_point'))}"
    if kind == "spark_jar_task":
        return _s(body.get("main_class_name"))
    if kind == "pipeline_task":
        return _s(body.get("pipeline_id"))
    if kind == "run_job_task":
        return f"job {_s(body.get('job_id'))}"
    if kind == "sql_task":
        for sub in ("query", "file", "dashboard", "alert"):
            if isinstance(body.get(sub), dict):
                d = body[sub]
                return f"{sub}: {_s(d.get('query_id') or d.get('path') or d.get(sub + '_id'))}"
    if kind == "dbt_task":
        return "; ".join(_s(c) for c in body.get("commands", []) if c)[:200]
    if kind == "condition_task":
        return f"{_s(body.get('left'))} {_s(body.get('op'))} {_s(body.get('right'))}".strip()
    if kind == "for_each_task":
        return _s(body.get("inputs"))[:200]
    return ""


def _task_compute(task: Raw) -> str:
    if task.get("existing_cluster_id"):
        return f"Existing cluster {_s(task['existing_cluster_id'])}"
    if task.get("job_cluster_key"):
        return f"Job cluster {_s(task['job_cluster_key'])}"
    if task.get("new_cluster"):
        return "New cluster"
    return "Serverless"


def _jobs(ctx: _Ctx, items: list[Raw]) -> tuple[list[JobRow], list[JobTaskRow]]:
    jobs: list[JobRow] = []
    tasks_out: list[JobTaskRow] = []
    for job in items:
        st = _d(job.get("settings"))
        job_id = _s(job.get("job_id"))
        name = _s(st.get("name")) or f"job {job_id}"
        tasks = _dicts(st.get("tasks"))
        features: Counter[str] = Counter()
        task_types: list[str] = []
        for t in tasks:
            kind = _task_type(t)
            task_types.append(kind)
            body = _d(t.get(kind))
            fid = ctx.rules.task_features.get(kind)
            if fid:
                features[fid] = 1
            if t.get("libraries"):
                features["JOB-LIBRARIES"] = 1
            target = _task_target(kind, body)
            if kind == "notebook_task" and target:
                ctx.deps.append(("Job", name, "runs notebook", target))
            elif kind == "pipeline_task" and target:
                ctx.deps.append(("Job", name, "runs DLT pipeline", target))
            elif kind == "run_job_task":
                ctx.deps.append(("Job", name, "runs job", _s(body.get("job_id"))))
            elif kind == "sql_task" and target.startswith("query: "):
                ctx.deps.append(("Job", name, "runs SQL query", target[len("query: ") :]))
            tasks_out.append(
                JobTaskRow(
                    job_id=job_id,
                    job_name=name,
                    task_key=_s(t.get("task_key")),
                    task_type=kind,
                    target=target,
                    depends_on=", ".join(
                        _s(d.get("task_key")) for d in _dicts(t.get("depends_on"))
                    ),
                    compute=_task_compute(t),
                    libraries=len(t.get("libraries") or []),
                    max_retries=_i(t.get("max_retries")),
                    timeout_s=_i(t.get("timeout_seconds")),
                    fabric_activity=ctx.rules.task_activities.get(kind, "Review manually"),
                )
            )
        if unknown := [k for k in task_types if k not in ctx.rules.task_activities]:
            for kind in sorted(set(unknown)):
                features[f"JOB-TASK-{kind.upper()}"] = 1
        sched = _d(st.get("schedule"))
        trig = _d(st.get("trigger"))
        if sched:
            features["JOB-SCHEDULE"] = 1
        if st.get("continuous"):
            features["JOB-CONTINUOUS"] = 1
        if any(k in trig for k in ("file_arrival", "table_update", "table")):
            features["JOB-EVENT-TRIGGER"] = 1
        email = _d(st.get("email_notifications"))
        notifications = bool(
            st.get("webhook_notifications") and any(_d(st.get("webhook_notifications")).values())
        ) or any(email.get(k) for k in ("on_failure", "on_success", "on_start"))
        if notifications:
            features["JOB-ALERTS"] = 1
        job_clusters = _dicts(st.get("job_clusters"))
        if any(_d(jc.get("new_cluster")).get("init_scripts") for jc in job_clusters):
            features["JOB-INIT-SCRIPTS"] = 1
        trigger = ", ".join(sorted(k for k in trig if k != "pause_status"))
        key = ctx.asset("Job", job_id or name, name, f"job_id={job_id}", features)
        tags = _d(st.get("tags"))
        run_as = _d(job.get("run_as") or st.get("run_as"))
        jobs.append(
            JobRow(
                asset_key=key,
                job_id=job_id,
                name=name,
                creator=_s(job.get("creator_user_name")),
                created_at=_ts(job.get("created_time")),
                tasks=len(tasks),
                task_types=", ".join(sorted(set(task_types))),
                schedule=_s(sched.get("quartz_cron_expression")),
                timezone=_s(sched.get("timezone_id")),
                pause_status=_s(sched.get("pause_status") or trig.get("pause_status")),
                trigger=trigger or ("schedule" if sched else "manual"),
                continuous=bool(st.get("continuous")),
                job_clusters=len(job_clusters),
                notifications=notifications,
                max_concurrent_runs=_i(st.get("max_concurrent_runs")) or 1,
                timeout_s=_i(st.get("timeout_seconds")),
                tags=", ".join(f"{k}={v}" for k, v in sorted(tags.items())),
                run_as=_s(run_as.get("user_name") or run_as.get("service_principal_name")),
            )
        )
    return (
        list(_sorted(jobs, key=lambda r: _fold(r.name, r.job_id))),
        list(_sorted(tasks_out, key=lambda r: _fold(r.job_name, r.job_id, r.task_key))),
    )


# --------------------------------------------------------------------------- compute


def _clusters(ctx: _Ctx, items: list[Raw]) -> list[ClusterRow]:
    rows: list[ClusterRow] = []
    for c in items:
        source = _s(c.get("cluster_source"))
        if source in _EPHEMERAL_CLUSTER_SOURCES:
            continue  # created by jobs / pipelines; covered there
        cid = _s(c.get("cluster_id"))
        name = _s(c.get("cluster_name")) or cid
        runtime = _s(c.get("spark_version"))
        node = _s(c.get("node_type_id"))
        conf = _d(c.get("spark_conf"))
        dbx_conf = sum(1 for k in conf if str(k).startswith("spark.databricks"))
        auto = _d(c.get("autoscale"))
        workers = (
            f"{_i(auto.get('min_workers'))}-{_i(auto.get('max_workers'))} (autoscale)"
            if auto
            else str(_i(c.get("num_workers")))
        )
        gpu = bool(_GPU_RE.search(node)) or "gpu" in runtime.lower()
        features: Counter[str] = Counter()
        if c.get("init_scripts"):
            features["CLU-INIT-SCRIPTS"] = 1
        if c.get("docker_image"):
            features["CLU-DOCKER"] = 1
        if gpu:
            features["CLU-GPU"] = 1
        if dbx_conf:
            features["CLU-SPARKCONF"] = 1
        m = re.match(r"(\d+)\.", runtime)
        if m and int(m.group(1)) < 12:
            features["CLU-OLD-RUNTIME"] = 1
        key = ctx.asset("Cluster", cid or name, name, cid, features)
        rows.append(
            ClusterRow(
                asset_key=key,
                cluster_id=cid,
                name=name,
                source=source,
                state=_s(c.get("state")),
                runtime=runtime,
                node_type=node,
                driver_node_type=_s(c.get("driver_node_type_id")) or node,
                workers=workers,
                autotermination_min=_i(c.get("autotermination_minutes")),
                access_mode=_s(c.get("data_security_mode")),
                photon=_s(c.get("runtime_engine")).upper() == "PHOTON" or "photon" in runtime,
                init_scripts=len(c.get("init_scripts") or []),
                docker=bool(c.get("docker_image")),
                gpu=gpu,
                spark_conf=len(conf),
                databricks_conf=dbx_conf,
                custom_tags=len(_d(c.get("custom_tags"))),
                policy_id=_s(c.get("policy_id")),
                creator=_s(c.get("creator_user_name")),
            )
        )
    return list(_sorted(rows, key=lambda r: _fold(r.name, r.cluster_id)))


def _pools(items: list[Raw]) -> list[InstancePoolRow]:
    rows = [
        InstancePoolRow(
            pool_id=_s(p.get("instance_pool_id")),
            name=_s(p.get("instance_pool_name")),
            node_type=_s(p.get("node_type_id")),
            min_idle=_i(p.get("min_idle_instances")),
            max_capacity=_i(p.get("max_capacity")),
            idle_autotermination_min=_i(p.get("idle_instance_autotermination_minutes")),
            preloaded_runtimes=", ".join(_s(v) for v in p.get("preloaded_spark_versions") or []),
            state=_s(p.get("state")),
        )
        for p in items
    ]
    return list(_sorted(rows, key=lambda r: _fold(r.name, r.pool_id)))


def _policies(items: list[Raw]) -> list[ClusterPolicyRow]:
    import json

    rows: list[ClusterPolicyRow] = []
    for p in items:
        definition = p.get("definition")
        try:
            rules = len(json.loads(definition)) if isinstance(definition, str) else 0
        except ValueError:
            rules = 0
        rows.append(
            ClusterPolicyRow(
                policy_id=_s(p.get("policy_id")),
                name=_s(p.get("name")),
                family=_s(p.get("policy_family_id")),
                rules=rules,
                creator=_s(p.get("creator_user_name")),
                created_at=_ts(p.get("created_at_timestamp")),
            )
        )
    return list(_sorted(rows, key=lambda r: _fold(r.name, r.policy_id)))


def _warehouses(ctx: _Ctx, items: list[Raw]) -> list[WarehouseRow]:
    rows: list[WarehouseRow] = []
    for w in items:
        wid = _s(w.get("id"))
        name = _s(w.get("name")) or wid
        key = ctx.asset("SQL Warehouse", wid or name, name, wid, ["WH-SQL-DIALECT"])
        rows.append(
            WarehouseRow(
                asset_key=key,
                warehouse_id=wid,
                name=name,
                size=_s(w.get("cluster_size")),
                warehouse_type=_s(w.get("warehouse_type")),
                serverless=_b(w.get("enable_serverless_compute")),
                min_clusters=_i(w.get("min_num_clusters")),
                max_clusters=_i(w.get("max_num_clusters")),
                auto_stop_min=_i(w.get("auto_stop_mins")),
                photon=_b(w.get("enable_photon")),
                channel=_s(_d(w.get("channel")).get("name")),
                state=_s(w.get("state")),
                creator=_s(w.get("creator_name")),
            )
        )
    return list(_sorted(rows, key=lambda r: _fold(r.name, r.warehouse_id)))


def _pipelines(ctx: _Ctx, items: list[Raw]) -> list[PipelineRow]:
    rows: list[PipelineRow] = []
    for p in items:
        spec = _d(p.get("spec"))
        pid = _s(p.get("pipeline_id") or spec.get("id"))
        name = _s(p.get("name") or spec.get("name")) or pid
        notebooks: list[str] = []
        libs = _dicts(spec.get("libraries"))
        for lib in libs:
            for kind in ("notebook", "file"):
                path = _s(_d(lib.get(kind)).get("path"))
                if path:
                    notebooks.append(normalise_path(path))
            glob = _s(_d(lib.get("glob")).get("include"))
            if glob:
                notebooks.append(glob)
        for nb in notebooks:
            ctx.deps.append(("DLT Pipeline", name, "uses notebook", nb))
        key = ctx.asset("DLT Pipeline", pid or name, name, pid, ["DLT-NO-EQUIVALENT"])
        rows.append(
            PipelineRow(
                asset_key=key,
                pipeline_id=pid,
                name=name,
                state=_s(p.get("state")),
                catalog=_s(spec.get("catalog")),
                target_schema=_s(spec.get("target") or spec.get("schema")),
                edition=_s(spec.get("edition")),
                continuous=_b(spec.get("continuous")),
                serverless=_b(spec.get("serverless")),
                photon=_b(spec.get("photon")),
                development=_b(spec.get("development")),
                channel=_s(spec.get("channel")),
                libraries=len(libs),
                notebooks=", ".join(notebooks),
                creator=_s(p.get("creator_user_name")),
            )
        )
    return list(_sorted(rows, key=lambda r: _fold(r.name, r.pipeline_id)))


# --------------------------------------------------------------------------- unity catalog


def _catalogs(items: list[Raw]) -> list[CatalogRow]:
    rows = [
        CatalogRow(
            name=_s(c.get("name")),
            catalog_type=_s(c.get("catalog_type")),
            owner=_s(c.get("owner")),
            storage_root=_s(c.get("storage_root")),
            isolation_mode=_s(c.get("isolation_mode")),
            comment=_s(c.get("comment")),
            created_at=_ts(c.get("created_at")),
        )
        for c in items
    ]
    return list(_sorted(rows, key=lambda r: _fold(r.name)))


def _schemas(items: list[Raw]) -> list[SchemaRow]:
    rows = []
    for s in items:
        cat, name = _s(s.get("catalog_name")), _s(s.get("name"))
        rows.append(
            SchemaRow(
                catalog=cat,
                schema_name=name,
                full_name=_s(s.get("full_name")) or f"{cat}.{name}",
                owner=_s(s.get("owner")),
                comment=_s(s.get("comment")),
                created_at=_ts(s.get("created_at")),
            )
        )
    return list(_sorted(rows, key=lambda r: _fold(r.full_name)))


_TABLE_ASSET_TYPES = {
    "VIEW": "View",
    "MATERIALIZED_VIEW": "Materialized View",
    "STREAMING_TABLE": "Streaming Table",
}


def _tables(ctx: _Ctx, items: list[Raw]) -> tuple[list[TableRow], list[ColumnRow], list[ViewRow]]:
    tables: list[TableRow] = []
    columns: list[ColumnRow] = []
    views: list[ViewRow] = []
    for t in items:
        cat, sch, name = _s(t.get("catalog_name")), _s(t.get("schema_name")), _s(t.get("name"))
        full = _s(t.get("full_name")) or f"{cat}.{sch}.{name}"
        ttype = _s(t.get("table_type"))
        fmt = _s(t.get("data_source_format")).upper()
        cols = _dicts(t.get("columns"))
        props = {str(k): v for k, v in _d(t.get("properties")).items()}
        part_cols = [
            _s(c.get("name"))
            for c in sorted(
                (c for c in cols if c.get("partition_index") is not None),
                key=lambda c: _i(c.get("partition_index")),
            )
        ]
        masks = sum(1 for c in cols if c.get("mask"))
        special = sorted(
            {
                _s(c.get("type_name")).upper()
                for c in cols
                if _s(c.get("type_name")).upper() in _SPECIAL_TYPES
            }
        )
        cdf = _s(props.get("delta.enableChangeDataFeed")).lower() == "true"
        dv = _s(props.get("delta.enableDeletionVectors")).lower() == "true"
        features: Counter[str] = Counter()
        if ttype == "VIEW":
            features["TBL-VIEW"] = 1
        elif ttype == "MATERIALIZED_VIEW":
            features["TBL-MV"] = 1
        elif ttype == "STREAMING_TABLE":
            features["TBL-STREAMING"] = 1
        elif ttype == "FOREIGN":
            features["TBL-FOREIGN"] = 1
        elif fmt and fmt != "DELTA":
            features["TBL-NON-DELTA"] = 1
        if cat == "hive_metastore":
            features["TBL-HIVE-METASTORE"] = 1
        if t.get("row_filter") or masks:
            features["TBL-ROW-COL-SECURITY"] = 1
        if dv or any(k.startswith("delta.feature.") for k in props):
            features["TBL-DELTA-FEATURES"] = 1
        if cdf:
            features["TBL-CDF"] = 1
        if special:
            features["TBL-TYPE"] = 1
        definition = _s(t.get("view_definition"))
        if definition:
            features.update(ctx.scan(definition))
        asset_type = _TABLE_ASSET_TYPES.get(ttype, "Table")
        key = ctx.asset(asset_type, full, full, _s(t.get("storage_location")), features)
        tables.append(
            TableRow(
                asset_key=key,
                catalog=cat,
                schema_name=sch,
                name=name,
                full_name=full,
                table_type=ttype,
                data_format=fmt,
                columns=len(cols),
                partition_columns=", ".join(part_cols),
                storage_location=_s(t.get("storage_location")),
                owner=_s(t.get("owner")),
                created_at=_ts(t.get("created_at")),
                updated_at=_ts(t.get("updated_at")),
                change_data_feed=cdf,
                deletion_vectors=dv,
                row_filter=bool(t.get("row_filter")),
                column_masks=masks,
                special_types=", ".join(special),
                comment=_s(t.get("comment")),
            )
        )
        if ctx.settings.include_columns:
            for pos, c in enumerate(cols):
                columns.append(
                    ColumnRow(
                        table=full,
                        position=_i(c.get("position")) if "position" in c else pos,
                        name=_s(c.get("name")),
                        data_type=_s(c.get("type_text") or c.get("type_name")),
                        nullable=_b(c.get("nullable", True)),
                        partition_index=_s(c.get("partition_index")),
                        masked=bool(c.get("mask")),
                        comment=_s(c.get("comment")),
                    )
                )
        if ttype in {"VIEW", "MATERIALIZED_VIEW"} or definition:
            text = definition if ctx.settings.include_view_definitions else ""
            views.append(
                ViewRow(
                    full_name=full,
                    view_type=ttype,
                    definition_chars=len(definition),
                    references=len(set(_THREE_PART_RE.findall(definition))),
                    definition=text[: ctx.settings.max_cell_chars],
                )
            )
    return (
        list(_sorted(tables, key=lambda r: _fold(r.full_name))),
        list(_sorted(columns, key=lambda r: (*_fold(r.table), f"{r.position:06d}"))),
        list(_sorted(views, key=lambda r: _fold(r.full_name))),
    )


def _volumes(ctx: _Ctx, items: list[Raw]) -> list[VolumeRow]:
    rows = []
    for v in items:
        cat, sch, name = _s(v.get("catalog_name")), _s(v.get("schema_name")), _s(v.get("name"))
        full = _s(v.get("full_name")) or f"{cat}.{sch}.{name}"
        loc = _s(v.get("storage_location"))
        key = ctx.asset("Volume", full, full, loc, ["VOL-FILES"])
        rows.append(
            VolumeRow(
                asset_key=key,
                full_name=full,
                catalog=cat,
                schema_name=sch,
                name=name,
                volume_type=_s(v.get("volume_type")),
                storage_location=loc,
                owner=_s(v.get("owner")),
            )
        )
    return list(_sorted(rows, key=lambda r: _fold(r.full_name)))


def _managed(name: str) -> bool:
    return name.startswith(("__databricks", "databricks-"))


def _external_locations(ctx: _Ctx, items: list[Raw]) -> list[ExternalLocationRow]:
    rows = []
    for e in items:
        name = _s(e.get("name"))
        if _managed(name):
            continue
        key = ctx.asset("External Location", name, name, _s(e.get("url")), ["EXTLOC"])
        rows.append(
            ExternalLocationRow(
                asset_key=key,
                name=name,
                url=_s(e.get("url")),
                credential=_s(e.get("credential_name")),
                read_only=_b(e.get("read_only")),
                owner=_s(e.get("owner")),
                comment=_s(e.get("comment")),
            )
        )
    return list(_sorted(rows, key=lambda r: _fold(r.name)))


_CRED_TYPES = (
    "azure_managed_identity",
    "azure_service_principal",
    "aws_iam_role",
    "gcp_service_account_key",
    "databricks_gcp_service_account",
    "cloudflare_api_token",
)


def _storage_credentials(ctx: _Ctx, items: list[Raw]) -> list[StorageCredentialRow]:
    rows = []
    for c in items:
        name = _s(c.get("name"))
        if _managed(name):
            continue
        kind = next((k for k in _CRED_TYPES if c.get(k)), "")
        key = ctx.asset("Storage Credential", name, name, kind, ["CRED-STORAGE"])
        rows.append(
            StorageCredentialRow(
                asset_key=key,
                name=name,
                credential_type=kind,
                owner=_s(c.get("owner")),
                read_only=_b(c.get("read_only")),
                comment=_s(c.get("comment")),
            )
        )
    return list(_sorted(rows, key=lambda r: _fold(r.name)))


def _connections(ctx: _Ctx, items: list[Raw]) -> list[ConnectionRow]:
    rows = []
    for c in items:
        name = _s(c.get("name"))
        ctype = _s(c.get("connection_type"))
        key = ctx.asset("Connection", name, name, ctype, ["CONN-RECREATE"])
        rows.append(
            ConnectionRow(
                asset_key=key,
                name=name,
                connection_type=ctype,
                owner=_s(c.get("owner")),
                read_only=_b(c.get("read_only")),
                comment=_s(c.get("comment")),
                created_at=_ts(c.get("created_at")),
            )
        )
    return list(_sorted(rows, key=lambda r: _fold(r.name)))


def _functions(ctx: _Ctx, items: list[Raw]) -> list[FunctionRow]:
    rows = []
    for f in items:
        cat, sch, name = _s(f.get("catalog_name")), _s(f.get("schema_name")), _s(f.get("name"))
        full = _s(f.get("full_name")) or f"{cat}.{sch}.{name}"
        ext = _s(f.get("external_language")).upper()
        is_python = ext == "PYTHON" or (_s(f.get("routine_body")) == "EXTERNAL" and not ext)
        language = ext or ("PYTHON" if is_python else "SQL")
        body = _s(f.get("routine_definition"))
        params = _dicts(_d(f.get("input_params")).get("parameters"))
        features = ctx.scan(body)
        features["FUNC-PYTHON" if is_python else "FUNC-SQL"] = 1
        key = ctx.asset("Function", full, full, "", features)
        rows.append(
            FunctionRow(
                asset_key=key,
                full_name=full,
                catalog=cat,
                schema_name=sch,
                name=name,
                language=language,
                return_type=_s(f.get("full_data_type") or f.get("data_type")),
                parameters=", ".join(
                    f"{_s(p.get('name'))} {_s(p.get('type_text'))}".strip() for p in params
                ),
                table_function=_s(f.get("data_type")) == "TABLE_TYPE"
                or bool(f.get("return_params")),
                body_chars=len(body),
            )
        )
    return list(_sorted(rows, key=lambda r: _fold(r.full_name)))


def _grants(items: list[Raw]) -> list[GrantRow]:
    rows = [
        GrantRow(
            securable_type=_s(g.get("securable_type")),
            securable=_s(g.get("securable")),
            principal=_s(g.get("principal")),
            privileges=", ".join(sorted(_s(p) for p in g.get("privileges") or [])),
        )
        for g in items
    ]
    return list(_sorted(rows, key=lambda r: _fold(r.securable_type, r.securable, r.principal)))


# --------------------------------------------------------------------------- analytics / ML


def _queries(ctx: _Ctx, items: list[Raw]) -> list[QueryRow]:
    rows = []
    for q in items:
        qid = _s(q.get("id"))
        name = _s(q.get("display_name") or q.get("name")) or qid
        text = _s(q.get("query_text") or q.get("query"))
        features = ctx.scan(text)
        features["QUERY-DIALECT"] = 1
        key = ctx.asset("SQL Query", qid or name, name, qid, features)
        rows.append(
            QueryRow(
                asset_key=key,
                query_id=qid,
                name=name,
                owner=_s(q.get("owner_user_name") or _d(q.get("user")).get("email")),
                warehouse_id=_s(q.get("warehouse_id") or q.get("data_source_id")),
                lines=text.count("\n") + 1 if text else 0,
                updated_at=_ts(q.get("update_time") or q.get("updated_at")),
            )
        )
    return list(_sorted(rows, key=lambda r: _fold(r.name, r.query_id)))


def _dashboards(ctx: _Ctx, items: list[Raw]) -> list[DashboardRow]:
    rows = []
    for d in items:
        kind = _s(d.get("_kind")) or "AI/BI (Lakeview)"
        did = _s(d.get("dashboard_id") or d.get("id"))
        name = _s(d.get("display_name") or d.get("name")) or did
        key = ctx.asset("Dashboard", did or name, name, _s(d.get("path")), ["DASH-REBUILD"])
        rows.append(
            DashboardRow(
                asset_key=key,
                dashboard_id=did,
                name=name,
                kind=kind,
                path=_s(d.get("path") or d.get("parent_path")),
                warehouse_id=_s(d.get("warehouse_id")),
                state=_s(d.get("lifecycle_state")) or ("TRASHED" if d.get("is_archived") else ""),
                created_at=_ts(d.get("create_time") or d.get("created_at")),
                updated_at=_ts(d.get("update_time") or d.get("updated_at")),
            )
        )
    return list(_sorted(rows, key=lambda r: _fold(r.kind, r.name, r.dashboard_id)))


def _alerts(ctx: _Ctx, items: list[Raw]) -> list[AlertRow]:
    rows = []
    for a in items:
        aid = _s(a.get("id"))
        name = _s(a.get("display_name") or a.get("name")) or aid
        features = ctx.scan(_s(a.get("query_text")))
        features["ALERT-REBUILD"] = 1
        key = ctx.asset("Alert", aid or name, name, aid, features)
        rows.append(
            AlertRow(
                asset_key=key,
                alert_id=aid,
                name=name,
                query_id=_s(a.get("query_id")),
                state=_s(a.get("state") or a.get("lifecycle_state")),
                owner=_s(a.get("owner_user_name")),
            )
        )
    return list(_sorted(rows, key=lambda r: _fold(r.name, r.alert_id)))


def _models(ctx: _Ctx, items: list[Raw]) -> list[ModelRow]:
    rows = []
    for m in items:
        workspace = m.get("_registry") == "workspace"
        full = _s(m.get("full_name")) or (
            f"workspace.{_s(m.get('name'))}" if workspace else _s(m.get("name"))
        )
        key = ctx.asset("ML Model", full, full, "", ["MODEL-REGISTRY"])
        rows.append(
            ModelRow(
                asset_key=key,
                full_name=full,
                catalog=_s(m.get("catalog_name")) or ("(workspace registry)" if workspace else ""),
                schema_name=_s(m.get("schema_name")),
                name=_s(m.get("name")),
                owner=_s(m.get("owner") or m.get("user_id")),
                created_at=_ts(m.get("created_at") or m.get("creation_timestamp")),
                updated_at=_ts(m.get("updated_at") or m.get("last_updated_timestamp")),
            )
        )
    return list(_sorted(rows, key=lambda r: _fold(r.full_name)))


def _serving(ctx: _Ctx, items: list[Raw]) -> list[ServingEndpointRow]:
    rows = []
    for e in items:
        name = _s(e.get("name"))
        if name.startswith("databricks-"):
            continue  # Databricks-hosted foundation models, not customer assets
        config = _d(e.get("config"))
        entities = _dicts(config.get("served_entities")) or _dicts(config.get("served_models"))
        kinds = sorted(
            {
                "external model"
                if ent.get("external_model")
                else "foundation model"
                if ent.get("foundation_model")
                else "custom model"
                for ent in entities
            }
        )
        key = ctx.asset("Serving Endpoint", name, name, "", ["SERVING-NO-EQUIVALENT"])
        rows.append(
            ServingEndpointRow(
                asset_key=key,
                name=name,
                state=_s(_d(e.get("state")).get("ready")),
                task=_s(e.get("task")),
                served_entities=", ".join(
                    _s(ent.get("entity_name") or ent.get("model_name") or ent.get("name"))
                    for ent in entities
                ),
                entity_types=", ".join(kinds),
                creator=_s(e.get("creator")),
            )
        )
    return list(_sorted(rows, key=lambda r: _fold(r.name)))


def _experiments(items: list[Raw]) -> list[ExperimentRow]:
    rows = [
        ExperimentRow(
            experiment_id=_s(e.get("experiment_id")),
            name=_s(e.get("name")),
            lifecycle_stage=_s(e.get("lifecycle_stage")),
            last_update=_ts(e.get("last_update_time")),
        )
        for e in items
    ]
    return list(_sorted(rows, key=lambda r: _fold(r.name, r.experiment_id)))


# --------------------------------------------------------------------------- platform


def _libraries(ctx: _Ctx, statuses: list[Raw], clusters: list[Raw]) -> list[LibraryRow]:
    names = {_s(c.get("cluster_id")): _s(c.get("cluster_name")) for c in clusters}
    used: dict[tuple[str, str], set[str]] = defaultdict(set)
    for st in statuses:
        cid = _s(st.get("cluster_id"))
        for ls in _dicts(st.get("library_statuses")):
            lib = _d(ls.get("library"))
            kind = next((k for k in _LIB_KINDS if k in lib), "other")
            value = lib.get(kind)
            if isinstance(value, dict):
                lib_name = _s(value.get("package") or value.get("coordinates"))
            else:
                lib_name = _s(value) if value is not None else _s(lib)
            used[(kind, lib_name)].add(names.get(cid) or cid)
    rows = []
    for (kind, lib_name), cl in used.items():
        feature = [] if kind == "pypi" else [f"LIB-{kind.upper()}"]
        key = ctx.asset("Library", f"{kind}:{lib_name}", lib_name, kind, feature)
        rows.append(
            LibraryRow(
                asset_key=key,
                kind=kind,
                name=lib_name,
                clusters=len(cl),
                cluster_names=", ".join(sorted(cl, key=str.casefold)),
            )
        )
    return list(_sorted(rows, key=lambda r: _fold(r.kind, r.name)))


def _secret_scopes(ctx: _Ctx, items: list[Raw]) -> list[SecretScopeRow]:
    rows = []
    for s in items:
        name = _s(s.get("name"))
        keys = [_s(k) for k in s.get("keys") or []]
        key = ctx.asset("Secret Scope", name, name, f"{len(keys)} secrets", ["SECRET-VALUES"])
        rows.append(
            SecretScopeRow(
                asset_key=key,
                scope=name,
                backend=_s(s.get("backend_type")),
                secrets=len(keys),
                keys=", ".join(keys),
            )
        )
    return list(_sorted(rows, key=lambda r: _fold(r.scope)))


def _mounts(ctx: _Ctx, items: list[Raw]) -> list[MountRow]:
    rows = []
    for m in items:
        path = _s(m.get("path"))
        key = ctx.asset("DBFS Mount", path, path, path, ["MOUNT-REPLACE"])
        rows.append(MountRow(asset_key=key, mount_point=path))
    return list(_sorted(rows, key=lambda r: _fold(r.mount_point)))


def _repos(ctx: _Ctx, items: list[Raw]) -> list[RepoRow]:
    rows = []
    for r in items:
        path = _s(r.get("path"))
        key = ctx.asset("Repo", path or _s(r.get("id")), path, _s(r.get("url")), [])
        rows.append(
            RepoRow(
                asset_key=key,
                repo_id=_s(r.get("id")),
                path=path,
                url=_s(r.get("url")),
                provider=_s(r.get("provider")),
                branch=_s(r.get("branch")),
            )
        )
    return list(_sorted(rows, key=lambda r: _fold(r.path)))


def _identities(sections: dict[str, list[Raw]]) -> list[IdentityRow]:
    rows: list[IdentityRow] = []
    for u in sections.get("users", []):
        rows.append(
            IdentityRow(
                identity_type="User",
                name=_s(u.get("userName") or u.get("displayName")),
                identifier=_s(u.get("id")),
                active=_b(u.get("active", True)),
                groups=len(u.get("groups") or []),
                members=0,
            )
        )
    for g in sections.get("groups", []):
        rows.append(
            IdentityRow(
                identity_type="Group",
                name=_s(g.get("displayName")),
                identifier=_s(g.get("id")),
                active=True,
                groups=len(g.get("groups") or []),
                members=len(g.get("members") or []),
            )
        )
    for sp in sections.get("service_principals", []):
        rows.append(
            IdentityRow(
                identity_type="Service principal",
                name=_s(sp.get("displayName") or sp.get("applicationId")),
                identifier=_s(sp.get("applicationId") or sp.get("id")),
                active=_b(sp.get("active", True)),
                groups=len(sp.get("groups") or []),
                members=0,
            )
        )
    return list(_sorted(rows, key=lambda r: _fold(r.identity_type, r.name, r.identifier)))


# --------------------------------------------------------------------------- dependencies


def _dependencies(
    ctx: _Ctx,
    notebooks: list[NotebookRow],
    pipelines: list[PipelineRow],
    jobs: list[JobRow],
    queries: list[QueryRow],
) -> list[DependencyRow]:
    nb_paths = {n.path for n in notebooks}
    known = {
        "runs notebook": nb_paths,
        "uses notebook": nb_paths,
        "runs DLT pipeline": {p.pipeline_id for p in pipelines},
        "runs job": {j.job_id for j in jobs},
        "runs SQL query": {q.query_id for q in queries},
    }
    rows = {
        DependencyRow(
            from_type=ft,
            from_name=fn,
            relation=rel,
            to=to,
            resolved=to in known.get(rel, set()),
        )
        for ft, fn, rel, to in ctx.deps
    }
    return list(_sorted(rows, key=lambda r: _fold(r.from_type, r.from_name, r.relation, r.to)))


# --------------------------------------------------------------------------- entry point


def parse_snapshot(snapshot: RawSnapshot, rules: ParserRules, settings: Settings) -> Estate:
    """Turn a raw snapshot into the estate. Never raises on a malformed object."""
    ctx = _Ctx(rules=rules, settings=settings)
    sec = {k: _dicts(v) for k, v in snapshot.sections.items()}
    get = sec.get

    notebooks = _notebooks(ctx, get("notebooks", []))
    jobs, job_tasks = _jobs(ctx, get("jobs", []))
    clusters = _clusters(ctx, get("clusters", []))
    pipelines = _pipelines(ctx, get("pipelines", []))
    tables, columns, views = _tables(ctx, get("tables", []))
    queries = _queries(ctx, get("queries", []))
    estate = Estate(
        notebooks=tuple(notebooks),
        jobs=tuple(jobs),
        job_tasks=tuple(job_tasks),
        clusters=tuple(clusters),
        instance_pools=tuple(_pools(get("instance_pools", []))),
        cluster_policies=tuple(_policies(get("cluster_policies", []))),
        warehouses=tuple(_warehouses(ctx, get("warehouses", []))),
        pipelines=tuple(pipelines),
        catalogs=tuple(_catalogs(get("catalogs", []))),
        schemas=tuple(_schemas(get("schemas", []))),
        tables=tuple(tables),
        columns=tuple(columns),
        views=tuple(views),
        volumes=tuple(_volumes(ctx, get("volumes", []))),
        external_locations=tuple(_external_locations(ctx, get("external_locations", []))),
        storage_credentials=tuple(_storage_credentials(ctx, get("storage_credentials", []))),
        connections=tuple(_connections(ctx, get("connections", []))),
        functions=tuple(_functions(ctx, get("functions", []))),
        grants=tuple(_grants(get("grants", []))),
        queries=tuple(queries),
        dashboards=tuple(_dashboards(ctx, get("dashboards", []))),
        alerts=tuple(_alerts(ctx, get("alerts", []))),
        models=tuple(_models(ctx, get("models", []))),
        serving_endpoints=tuple(_serving(ctx, get("serving_endpoints", []))),
        experiments=tuple(_experiments(get("experiments", []))),
        libraries=tuple(_libraries(ctx, get("library_statuses", []), get("clusters", []))),
        secret_scopes=tuple(_secret_scopes(ctx, get("secret_scopes", []))),
        mounts=tuple(_mounts(ctx, get("mounts", []))),
        repos=tuple(_repos(ctx, get("repos", []))),
        identities=tuple(_identities(sec)),
    )
    dependencies = _dependencies(ctx, notebooks, pipelines, jobs, queries)
    warnings = [
        WarningRow(source=w.get("source", ""), message=w.get("message", ""))
        for w in snapshot.warnings
    ]
    warnings += ctx.warnings
    assets = _sorted(
        {a.key: a for a in ctx.assets}.values(),
        key=lambda a: _fold(a.asset_type, a.name, a.key),
    )
    return estate.model_copy(
        update={
            "dependencies": tuple(dependencies),
            "assets": assets,
            "warnings": tuple(sorted(warnings, key=lambda w: _fold(w.source, w.message))),
        }
    )
