"""Live collection: read a Databricks workspace into a ``RawSnapshot``.

One function per collector. Each one only reads (GET) and appends raw API objects to a
section; nothing is interpreted here (that is the parser's job), so a saved snapshot can be
re-parsed offline later and always gives the same workbook.

An endpoint that is missing, not enabled or not permitted becomes a warning; it never ends
the run. Only an authentication failure (HTTP 401) or an unreachable host stops it.
"""

from __future__ import annotations

import base64
import binascii
import time
import urllib.parse
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from dbx_premig.client import ApiClient, EndpointUnavailable, paged
from dbx_premig.config import Settings
from dbx_premig.logging import get_logger
from dbx_premig.models import RawSnapshot

__all__ = ["COLLECTORS", "ProgressFn", "collect_workspace", "detect_cloud"]

log = get_logger("collector")

ProgressFn = Callable[[str, str], None]
Sections = dict[str, list[dict[str, Any]]]


class _Run:
    """Mutable state of one collection run (sections + warnings)."""

    def __init__(self, client: ApiClient, settings: Settings) -> None:
        self.client = client
        self.settings = settings
        self.sections: Sections = {}
        self.warnings: list[dict[str, str]] = []
        self.meta: dict[str, Any] = {}
        self._uc_schemas: list[tuple[str, str]] | None = None

    def add(self, section: str, item: dict[str, Any]) -> None:
        self.sections.setdefault(section, []).append(item)

    def warn(self, source: str, message: str) -> None:
        self.warnings.append({"source": source, "message": message})

    def try_get(self, source: str, endpoint: str, /, **params: Any) -> dict[str, Any] | None:
        try:
            return self.client.get(endpoint, **params)
        except EndpointUnavailable as exc:
            self.warn(source, f"Could not read {exc.path} (HTTP {exc.status}).")
            return None

    def try_paged(
        self, source: str, endpoint: str, key: str, /, **params: Any
    ) -> list[dict[str, Any]]:
        try:
            return list(paged(self.client, endpoint, key, **params))
        except EndpointUnavailable as exc:
            self.warn(source, f"Could not read {exc.path} (HTTP {exc.status}).")
            return []

    # Unity Catalog schemas are needed by several collectors: list them once.
    def uc_schemas(self) -> list[tuple[str, str]]:
        if self._uc_schemas is None:
            self._uc_schemas = []
            for cat in self.uc_catalogs():
                for sch in self.try_paged(
                    "unity_catalog", "/api/2.1/unity-catalog/schemas", "schemas", catalog_name=cat
                ):
                    name = str(sch.get("name", ""))
                    if name and name != "information_schema":
                        self._uc_schemas.append((cat, name))
                        self.add("schemas", sch)
        return self._uc_schemas

    def uc_catalogs(self) -> list[str]:
        if "catalogs" not in self.sections:
            self.sections["catalogs"] = []
            for cat in self.try_paged(
                "unity_catalog", "/api/2.1/unity-catalog/catalogs", "catalogs"
            ):
                name = str(cat.get("name", ""))
                if not self._catalog_wanted(name):
                    continue
                self.add("catalogs", cat)
        return sorted(str(c.get("name")) for c in self.sections["catalogs"])

    def _catalog_wanted(self, name: str) -> bool:
        s = self.settings
        if not name or name in s.skip_catalogs:
            return False
        if name == "hive_metastore" and not s.include_hive_metastore:
            return False
        return not (s.catalogs and name not in s.catalogs)


def detect_cloud(host: str) -> str:
    """Cloud from the workspace URL."""
    h = urllib.parse.urlparse(host).hostname or host
    if h.endswith("azuredatabricks.net"):
        return "Azure"
    if h.endswith("gcp.databricks.com"):
        return "GCP"
    if h.endswith("cloud.databricks.com") or h.endswith("databricks.com"):
        return "AWS"
    return "Unknown"


# --------------------------------------------------------------------------- collectors


def _workspace(run: _Run) -> None:
    run.meta["cloud"] = detect_cloud(run.client.host)
    summary = run.try_get("workspace", "/api/2.1/unity-catalog/metastore_summary")
    if summary:
        run.meta["metastore"] = summary.get("name", "")
        run.meta["metastore_id"] = summary.get("metastore_id", "")
        run.meta["region"] = summary.get("region", "")
        run.meta["metastore_cloud"] = summary.get("cloud", "")
    me = run.try_get("workspace", "/api/2.0/preview/scim/v2/Me", attributes="userName")
    if me:
        run.meta["collected_by"] = me.get("userName", "")


def _notebooks(run: _Run) -> None:
    s = run.settings
    stack = ["/"]
    exported = 0
    while stack:
        folder = stack.pop()
        listing = run.try_get("notebooks", "/api/2.0/workspace/list", path=folder)
        if listing is None:
            continue
        objects = sorted(
            (o for o in listing.get("objects", []) if isinstance(o, dict)),
            key=lambda o: str(o.get("path", "")),
        )
        for obj in objects:
            kind = str(obj.get("object_type", ""))
            path = str(obj.get("path", ""))
            if kind in {"DIRECTORY", "REPO"}:
                if "/." in path or (s.skip_repos and path.startswith("/Repos")):
                    continue
                stack.append(path)
                continue
            is_code_file = kind == "FILE" and path.lower().endswith((".py", ".sql", ".scala", ".r"))
            if kind != "NOTEBOOK" and not is_code_file:
                if kind == "FILE":
                    run.add("workspace_files", {"path": path, "size": obj.get("size")})
                continue
            item: dict[str, Any] = {
                "path": path,
                "object_type": kind,
                "language": obj.get("language") or "",
                "modified_at": obj.get("modified_at"),
                "size": obj.get("size"),
                "origin": "workspace",
                "source": None,
            }
            if exported >= s.max_notebooks:
                item["skipped_reason"] = f"over the max_notebooks cap ({s.max_notebooks})"
                run.add("notebooks", item)
                continue
            exp = run.try_get(
                "notebooks",
                "/api/2.0/workspace/export",
                path=path,
                format="SOURCE" if kind == "NOTEBOOK" else "AUTO",
            )
            exported += 1
            if exp is not None:
                try:
                    raw = base64.b64decode(str(exp.get("content", "")), validate=False)
                except (binascii.Error, ValueError):
                    raw = b""
                    run.warn("notebooks", f"Export of {path} was not valid base64.")
                if len(raw) > s.max_notebook_bytes:
                    item["skipped_reason"] = f"larger than {s.max_notebook_bytes} bytes"
                else:
                    item["source"] = raw.decode("utf-8", "replace")
                item["size"] = len(raw)
            run.add("notebooks", item)
    if exported >= s.max_notebooks:
        run.warn("notebooks", f"Stopped scanning notebooks at the cap of {s.max_notebooks}.")


def _repos(run: _Run) -> None:
    for repo in run.try_paged("repos", "/api/2.0/repos", "repos"):
        run.add("repos", repo)


def _jobs(run: _Run) -> None:
    for job in run.try_paged("jobs", "/api/2.1/jobs/list", "jobs", limit=100, expand_tasks="true"):
        run.add("jobs", job)


def _pipelines(run: _Run) -> None:
    for p in run.try_paged("pipelines", "/api/2.0/pipelines", "statuses", max_results=100):
        pid = p.get("pipeline_id")
        detail = run.try_get("pipelines", f"/api/2.0/pipelines/{pid}") if pid else None
        run.add("pipelines", {**p, **(detail or {})})


def _clusters(run: _Run) -> None:
    try:
        items = list(
            paged(
                run.client, "/api/2.1/clusters/list", "clusters", page_size=run.settings.page_size
            )
        )
    except EndpointUnavailable:
        data = run.try_get("clusters", "/api/2.0/clusters/list") or {}
        items = [c for c in data.get("clusters", []) if isinstance(c, dict)]
    for c in items:
        run.add("clusters", c)


def _instance_pools(run: _Run) -> None:
    data = run.try_get("instance_pools", "/api/2.0/instance-pools/list") or {}
    for p in data.get("instance_pools", []):
        run.add("instance_pools", p)


def _cluster_policies(run: _Run) -> None:
    data = run.try_get("cluster_policies", "/api/2.0/policies/clusters/list") or {}
    for p in data.get("policies", []):
        run.add("cluster_policies", p)


def _warehouses(run: _Run) -> None:
    data = run.try_get("warehouses", "/api/2.0/sql/warehouses") or {}
    for w in data.get("warehouses", []):
        run.add("warehouses", w)


def _unity_catalog(run: _Run) -> None:
    for cat, sch in run.uc_schemas():
        for t in run.try_paged(
            "unity_catalog",
            "/api/2.1/unity-catalog/tables",
            "tables",
            catalog_name=cat,
            schema_name=sch,
            max_results=500,
        ):
            run.add("tables", t)
        if cat == "hive_metastore":
            continue
        for v in run.try_paged(
            "unity_catalog",
            "/api/2.1/unity-catalog/volumes",
            "volumes",
            catalog_name=cat,
            schema_name=sch,
        ):
            run.add("volumes", v)
    for e in run.try_paged(
        "unity_catalog", "/api/2.1/unity-catalog/external-locations", "external_locations"
    ):
        run.add("external_locations", e)
    for c in run.try_paged(
        "unity_catalog", "/api/2.1/unity-catalog/storage-credentials", "storage_credentials"
    ):
        run.add("storage_credentials", c)
    for c in run.try_paged("unity_catalog", "/api/2.1/unity-catalog/connections", "connections"):
        run.add("connections", c)


def _functions(run: _Run) -> None:
    for cat, sch in run.uc_schemas():
        if cat == "hive_metastore":
            continue
        for f in run.try_paged(
            "functions",
            "/api/2.1/unity-catalog/functions",
            "functions",
            catalog_name=cat,
            schema_name=sch,
        ):
            full = f.get("full_name")
            if full and not (f.get("input_params") or {}).get("parameters"):
                # The list call can omit parameters and the body: fetch the full function.
                detail = run.try_get(
                    "functions", "/api/2.1/unity-catalog/functions/" + urllib.parse.quote(str(full))
                )
                f = {**f, **(detail or {})}
            run.add("functions", f)


def _grants(run: _Run) -> None:
    if not run.settings.include_grants:
        return
    seen: set[str] = set()
    for cat, sch in run.uc_schemas():
        targets = [("schema", f"{cat}.{sch}")]
        if cat not in seen:
            seen.add(cat)
            targets.insert(0, ("catalog", cat))
        for kind, name in targets:
            if cat == "hive_metastore":
                continue
            data = run.try_get(
                "grants",
                f"/api/2.1/unity-catalog/permissions/{kind}/{urllib.parse.quote(name)}",
            )
            for pa in (data or {}).get("privilege_assignments", []):
                run.add("grants", {"securable_type": kind, "securable": name, **pa})


def _queries(run: _Run) -> None:
    for q in run.try_paged("queries", "/api/2.0/sql/queries", "results", page_size=100):
        run.add("queries", q)


def _dashboards(run: _Run) -> None:
    for d in run.try_paged(
        "dashboards", "/api/2.0/lakeview/dashboards", "dashboards", page_size=100
    ):
        run.add("dashboards", {**d, "_kind": "AI/BI (Lakeview)"})
    page = 1
    while True:
        data = run.try_get(
            "dashboards", "/api/2.0/preview/sql/dashboards", page=page, page_size=100
        )
        results = (data or {}).get("results") or []
        for d in results:
            run.add("dashboards", {**d, "_kind": "Legacy SQL"})
        if not results or page * 100 >= int((data or {}).get("count", 0) or 0):
            break
        page += 1


def _alerts(run: _Run) -> None:
    seen: set[str] = set()
    for path, key in (("/api/2.0/sql/alerts", "results"), ("/api/2.0/alerts", "alerts")):
        for a in run.try_paged("alerts", path, key, page_size=100):
            aid = str(a.get("id", ""))
            if aid and aid in seen:
                continue
            seen.add(aid)
            run.add("alerts", a)


def _models(run: _Run) -> None:
    for m in run.try_paged("models", "/api/2.1/unity-catalog/models", "registered_models"):
        cat = str(m.get("catalog_name") or str(m.get("full_name", "")).split(".")[0])
        if run._catalog_wanted(cat):
            run.add("models", m)
    for m in run.try_paged(
        "models", "/api/2.0/mlflow/registered-models/search", "registered_models", max_results=1000
    ):
        run.add("models", {**m, "_registry": "workspace"})


def _serving_endpoints(run: _Run) -> None:
    data = run.try_get("serving_endpoints", "/api/2.0/serving-endpoints") or {}
    for e in data.get("endpoints", []):
        run.add("serving_endpoints", e)


def _experiments(run: _Run) -> None:
    for e in run.try_paged(
        "experiments", "/api/2.0/mlflow/experiments/search", "experiments", max_results=1000
    ):
        run.add("experiments", e)


def _libraries(run: _Run) -> None:
    data = run.try_get("libraries", "/api/2.0/libraries/all-cluster-statuses") or {}
    for st in data.get("statuses", []):
        run.add("library_statuses", st)


def _secrets(run: _Run) -> None:
    data = run.try_get("secrets", "/api/2.0/secrets/scopes/list") or {}
    for scope in data.get("scopes", []):
        name = scope.get("name")
        listing = run.try_get("secrets", "/api/2.0/secrets/list", scope=name) or {}
        keys = sorted(str(k.get("key", "")) for k in listing.get("secrets", []))
        # Only key NAMES are kept. Secret values are never requested.
        run.add("secret_scopes", {**scope, "keys": keys})


def _mounts(run: _Run) -> None:
    try:
        data = run.client.get("/api/2.0/dbfs/list", path="/mnt")
    except EndpointUnavailable as exc:
        if exc.status == 404:
            run.meta["mounts_note"] = "No /mnt folder (normal for Unity Catalog-only workspaces)"
        else:
            run.warn("mounts", f"Could not read {exc.path} (HTTP {exc.status}).")
        return
    for f in data.get("files", []):
        if f.get("is_dir"):
            run.add("mounts", {"path": f.get("path")})


def _scim(run: _Run, resource: str, attributes: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    start = 1
    while True:
        data = run.try_get(
            "identities",
            f"/api/2.0/preview/scim/v2/{resource}",
            startIndex=start,
            count=500,
            attributes=attributes,
        )
        items = (data or {}).get("Resources") or []
        out.extend(i for i in items if isinstance(i, dict))
        total = int((data or {}).get("totalResults", 0) or 0)
        if not items or start + len(items) > total:
            return out
        start += len(items)


def _identities(run: _Run) -> None:
    for u in _scim(run, "Users", "id,userName,displayName,active,groups"):
        run.add("users", u)
    for g in _scim(run, "Groups", "id,displayName,members,groups"):
        run.add("groups", g)
    for sp in _scim(run, "ServicePrincipals", "id,applicationId,displayName,active,groups"):
        run.add("service_principals", sp)


COLLECTORS: dict[str, Callable[[_Run], None]] = {
    "workspace": _workspace,
    "notebooks": _notebooks,
    "repos": _repos,
    "jobs": _jobs,
    "pipelines": _pipelines,
    "clusters": _clusters,
    "instance_pools": _instance_pools,
    "cluster_policies": _cluster_policies,
    "warehouses": _warehouses,
    "unity_catalog": _unity_catalog,
    "functions": _functions,
    "grants": _grants,
    "queries": _queries,
    "dashboards": _dashboards,
    "alerts": _alerts,
    "models": _models,
    "serving_endpoints": _serving_endpoints,
    "experiments": _experiments,
    "libraries": _libraries,
    "secrets": _secrets,
    "mounts": _mounts,
    "identities": _identities,
}


def collect_workspace(
    client: ApiClient, settings: Settings, progress: ProgressFn | None = None
) -> RawSnapshot:
    """Run the selected collectors against a workspace and return the raw snapshot."""
    run = _Run(client, settings)
    for name in settings.collectors:
        if progress:
            progress(name, "start")
        started = time.monotonic()
        before = sum(len(v) for v in run.sections.values())
        try:
            COLLECTORS[name](run)
        except EndpointUnavailable as exc:  # pragma: no cover - collectors catch their own
            run.warn(name, f"Could not read {exc.path} (HTTP {exc.status}).")
        found = sum(len(v) for v in run.sections.values()) - before
        log.info("collector %s: %d objects in %.1fs", name, found, time.monotonic() - started)
        if progress:
            progress(name, f"{found} objects")
    run.meta.setdefault("cloud", detect_cloud(client.host))
    return RawSnapshot(
        mode="live",
        source=client.host,
        captured_at=datetime.now(UTC).replace(microsecond=0).isoformat(),
        meta={**run.meta, "collectors": list(settings.collectors)},
        sections=run.sections,
        warnings=run.warnings,
    )
