from __future__ import annotations

from typing import Any

import pytest

from dbx_premig.client import Credentials, DatabricksClient
from dbx_premig.collector import collect_workspace, detect_cloud
from dbx_premig.config import Settings, load_settings
from dbx_premig.estimation import summarise
from dbx_premig.models import DiscoveryReport, RawSnapshot
from dbx_premig.service import build_report
from tests.conftest import FIXED_CLOCK
from tests.fake_workspace import TOKEN, FakeWorkspace, serve


def _collect(ws: FakeWorkspace, **kw: Any) -> tuple[RawSnapshot, Settings, list[tuple[str, str]]]:
    s = load_settings(retry_backoff_s=0.0, **kw)
    with serve(ws) as url:
        client = DatabricksClient(Credentials(url, TOKEN), s)
        events: list[tuple[str, str]] = []
        snap = collect_workspace(client, s, lambda c, st: events.append((c, st)))
    return snap, s, events


def test_live_collection_matches_fixture(report: DiscoveryReport) -> None:
    """Live path (HTTP + collectors) and the saved snapshot give the same estate."""
    ws = FakeWorkspace.from_fixture()
    snap, s, events = _collect(ws)
    live = build_report(snap, s, generated_at=FIXED_CLOCK)
    a, b = summarise(live), summarise(report)
    assert a.by_type == b.by_type
    assert a.by_readiness == b.by_readiness
    assert len(live.estate.columns) == len(report.estate.columns)
    assert len(live.estate.grants) == len(report.estate.grants)
    assert len(live.estate.identities) == len(report.estate.identities)
    assert snap.meta["metastore"] == "metastore_westeurope"
    assert snap.meta["collected_by"] == "ana@contoso.com"
    assert ("jobs", "start") in events
    assert ws.methods == {"GET"}
    # The workspace FILE that is not code is recorded, never exported.
    assert snap.sections["workspace_files"] == [{"path": "/Shared/init.sh", "size": 10}]


def test_forbidden_endpoint_becomes_warning() -> None:
    ws = FakeWorkspace.from_fixture()
    ws.forbidden |= {"/api/2.0/secrets/scopes/list", "/api/2.1/jobs/list"}
    snap, _s, _ = _collect(ws)
    sources = {w["source"] for w in snap.warnings}
    assert {"secrets", "jobs"} <= sources
    assert "jobs" not in snap.sections
    assert snap.sections["clusters"]  # everything else still collected


def test_only_and_catalog_filter() -> None:
    snap, _s, _ = _collect(
        FakeWorkspace.from_fixture(), collectors=("unity_catalog",), catalogs=("main",)
    )
    assert set(snap.sections) == {
        "catalogs",
        "schemas",
        "tables",
        "volumes",
        "external_locations",
        "storage_credentials",
        "connections",
    }
    assert {c["name"] for c in snap.sections["catalogs"]} == {"main"}


def test_notebook_cap() -> None:
    snap, _s, _ = _collect(FakeWorkspace.from_fixture(), collectors=("notebooks",), max_notebooks=2)
    scanned = [n for n in snap.sections["notebooks"] if n.get("source")]
    assert len(scanned) <= 2
    assert any("cap" in w["message"] for w in snap.warnings)


@pytest.mark.parametrize(
    ("host", "cloud"),
    [
        ("https://adb-1.2.azuredatabricks.net", "Azure"),
        ("https://dbc-1.cloud.databricks.com", "AWS"),
        ("https://1.2.gcp.databricks.com", "GCP"),
        ("http://127.0.0.1:8080", "Unknown"),
    ],
)
def test_detect_cloud(host: str, cloud: str) -> None:
    assert detect_cloud(host) == cloud


def test_settings_fixture_is_clean(settings: Settings) -> None:
    assert settings.host is None and settings.token is None
