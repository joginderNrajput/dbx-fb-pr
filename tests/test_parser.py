from __future__ import annotations

from dbx_premig.catalog.loader import load_catalog
from dbx_premig.config import Settings, load_settings
from dbx_premig.models import RawSnapshot
from dbx_premig.parser import normalise_path, parse_snapshot
from dbx_premig.service import parser_rules


def _parse(snapshot: RawSnapshot, settings: Settings):  # type: ignore[no-untyped-def]
    return parse_snapshot(snapshot, parser_rules(load_catalog(), settings), settings)


def test_fixture_counts(snapshot: RawSnapshot, settings: Settings) -> None:
    e = _parse(snapshot, settings)
    assert len(e.notebooks) == 6
    assert len(e.jobs) == 3 and len(e.job_tasks) == 7
    assert len(e.clusters) == 2  # the JOB cluster is ephemeral and skipped
    assert len(e.tables) == 6 and len(e.columns) == 12 and len(e.views) == 2
    assert len(e.external_locations) == 1  # managed location skipped
    assert len(e.serving_endpoints) == 1  # databricks-* foundation model skipped
    assert len(e.libraries) == 4  # great-expectations de-duplicated across clusters
    assert len(e.identities) == 4
    assert len(e.assets) == 41


def test_notebook_details(snapshot: RawSnapshot, settings: Settings) -> None:
    e = _parse(snapshot, settings)
    nb = {n.path: n for n in e.notebooks}
    ingest = nb["/Shared/etl/ingest_orders"]  # /Workspace prefix removed
    assert ingest.area == "Shared" and ingest.runs_notebooks == 1 and ingest.cells == 5
    assert nb["/Shared/huge_notebook"].scanned is False
    hits = {a.key: {f.feature_id for f in a.features} for a in e.assets}
    assert {"AUTOLOADER", "DBU-SECRETS", "DBU-WIDGETS", "DBFS-PATH"} <= hits[ingest.asset_key]
    assert "NB-NOT-SCANNED" in hits["Notebook:/Shared/huge_notebook"]
    assert "LANG-SCALA" in hits["Notebook:/Users/ana@contoso.com/scala_job"]


def test_dependencies_resolved(snapshot: RawSnapshot, settings: Settings) -> None:
    deps = {
        (d.from_name, d.relation, d.to): d.resolved for d in _parse(snapshot, settings).dependencies
    }
    assert deps[("/Shared/etl/ingest_orders", "runs notebook", "/Shared/etl/helpers")] is True
    assert deps[("Daily orders", "runs DLT pipeline", "p-1")] is True
    assert deps[("Daily orders", "runs SQL query", "q-1")] is True
    assert deps[("File trigger", "runs notebook", "/Shared/etl/missing_notebook")] is False


def test_jobs_and_tables(snapshot: RawSnapshot, settings: Settings) -> None:
    e = _parse(snapshot, settings)
    daily = next(j for j in e.jobs if j.name == "Daily orders")
    assert daily.schedule == "0 0 6 * * ?" and daily.notifications and daily.tasks == 3
    tasks = {t.task_key: t for t in e.job_tasks if t.job_id == "11"}
    assert tasks["report"].target == "query: q-1"
    assert tasks["ingest"].compute == "Job cluster etl"
    assert tasks["dlt"].fabric_activity.startswith("Materialized Lake Views")
    orders = next(t for t in e.tables if t.full_name == "main.sales.orders")
    assert orders.partition_columns == "order_date"
    assert orders.change_data_feed and orders.deletion_vectors and orders.column_masks == 1
    assert orders.special_types == "VARIANT"


def test_deterministic(snapshot: RawSnapshot, settings: Settings) -> None:
    assert _parse(snapshot, settings) == _parse(snapshot, settings)


def test_malformed_objects_never_crash(settings: Settings) -> None:
    junk = RawSnapshot(
        mode="live",
        source="x",
        captured_at="now",
        sections={
            "jobs": [{"settings": "not a dict"}, {"job_id": 1, "settings": {"tasks": [1, {}]}}],
            "clusters": [{"spark_version": None, "autoscale": "x"}],
            "tables": [{"columns": "nope", "properties": None}],
            "notebooks": [{"path": None, "source": 42}],
            "cluster_policies": [{"definition": "{bad json"}],
            "library_statuses": [{"library_statuses": [{"library": {}}]}],
            "users": ["not a dict"],
            "warehouses": [{}],
        },
    )
    e = _parse(junk, settings)
    assert len(e.jobs) == 2 and len(e.tables) == 1 and len(e.cluster_policies) == 1


def test_options_drop_columns_and_view_sql(snapshot: RawSnapshot) -> None:
    s = load_settings(include_columns=False, include_view_definitions=False)
    e = _parse(snapshot, s)
    assert e.columns == () and all(v.definition == "" for v in e.views)


def test_normalise_path() -> None:
    assert normalise_path("/Workspace/Shared/a") == "/Shared/a"
    assert normalise_path("./b", "/Shared/x/a") == "/Shared/x/b"
    assert normalise_path("../c.py", "/Shared/x/a") == "/Shared/c"
    assert normalise_path("'/Users/u/n'") == "/Users/u/n"
