from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr

from dbx_premig.client import (
    Credentials,
    DatabricksClient,
    EndpointUnavailable,
    paged,
    resolve_credentials,
)
from dbx_premig.config import load_settings
from dbx_premig.errors import ConfigError, ConnectionFailedError
from tests.fake_workspace import TOKEN, FakeWorkspace, serve

FAST: dict[str, Any] = {"retry_backoff_s": 0.0, "request_timeout_s": 5.0}


def _client(url: str, token: str = TOKEN, **kw: Any) -> DatabricksClient:
    s = load_settings(**{**FAST, **kw})
    return DatabricksClient(Credentials(host=url, token=token), s)


def test_get_and_paging() -> None:
    ws = FakeWorkspace.from_fixture()
    with serve(ws) as url:
        client = _client(url)
        jobs = list(paged(client, "/api/2.1/jobs/list", "jobs"))
    assert [j["job_id"] for j in jobs] == [11, 12, 13]
    assert ws.calls.count("/api/2.1/jobs/list") == 3  # one item per page
    assert ws.methods == {"GET"}  # read-only


def test_401_is_fatal() -> None:
    with (
        serve(FakeWorkspace.from_fixture()) as url,
        pytest.raises(ConnectionFailedError, match="401"),
    ):
        _client(url, token="wrong").get("/api/2.0/sql/warehouses")


def test_403_is_endpoint_unavailable() -> None:
    ws = FakeWorkspace.from_fixture()
    ws.forbidden.add("/api/2.0/sql/warehouses")
    with serve(ws) as url, pytest.raises(EndpointUnavailable) as exc:
        _client(url).get("/api/2.0/sql/warehouses")
    assert exc.value.status == 403


def test_retries_5xx_then_succeeds() -> None:
    ws = FakeWorkspace.from_fixture()
    ws.flaky["/api/2.0/sql/warehouses"] = 2
    with serve(ws) as url:
        data = _client(url).get("/api/2.0/sql/warehouses")
    assert data["warehouses"][0]["id"] == "wh-1"


def test_retries_exhausted() -> None:
    ws = FakeWorkspace.from_fixture()
    ws.flaky["/api/2.0/sql/warehouses"] = 10
    with serve(ws) as url, pytest.raises(EndpointUnavailable, match="retries exhausted"):
        _client(url, max_retries=1).get("/api/2.0/sql/warehouses")


def test_unreachable_host_fails_fast() -> None:
    with pytest.raises(ConnectionFailedError, match="Cannot connect"):
        _client("http://127.0.0.1:9", max_retries=0).get("/api/2.0/sql/warehouses")


def test_oauth_m2m() -> None:
    ws = FakeWorkspace.from_fixture()
    ws.oauth = ("sp-id", "sp-secret")
    with serve(ws) as url:
        s = load_settings(**FAST)
        client = DatabricksClient(Credentials(url, None, "sp-id", "sp-secret"), s)
        assert client.get("/api/2.0/sql/warehouses")["warehouses"]
        bad = DatabricksClient(Credentials(url, None, "sp-id", "wrong"), s)
        with pytest.raises(ConnectionFailedError, match="OAuth"):
            bad.get("/api/2.0/sql/warehouses")


def test_resolve_credentials_sources(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="workspace URL"):
        resolve_credentials(load_settings())
    with pytest.raises(ConfigError, match="credentials"):
        resolve_credentials(load_settings(host="adb-1.azuredatabricks.net"))
    c = resolve_credentials(load_settings(host="h.example.com", token=SecretStr("t")))
    assert c.host == "https://h.example.com" and c.token == "t"
    assert c.auth_kind == "Personal access token"

    monkeypatch.setenv("DATABRICKS_HOST", "env.example.com")
    monkeypatch.setenv("DATABRICKS_TOKEN", "env-token")
    c = resolve_credentials(load_settings())
    assert (c.host, c.token) == ("https://env.example.com", "env-token")

    cfg = tmp_path / ".databrickscfg"
    cfg.write_text(
        "[DEFAULT]\nhost = https://default.example.com\ntoken = d\n"
        "[prod]\nhost = https://prod.example.com\nclient_id = cid\nclient_secret = cs\n"
    )
    monkeypatch.setenv("DATABRICKS_CONFIG_FILE", str(cfg))
    c = resolve_credentials(load_settings(profile="prod"))
    assert c.host == "https://prod.example.com"
    assert c.client_id == "cid" and c.auth_kind == "OAuth service principal"
    with pytest.raises(ConfigError, match="not defined"):
        resolve_credentials(load_settings(profile="missing"))
    monkeypatch.delenv("DATABRICKS_HOST")
    monkeypatch.delenv("DATABRICKS_TOKEN")
    c = resolve_credentials(load_settings())
    assert c.host == "https://default.example.com" and c.source == "profile DEFAULT"


def test_secret_never_in_error_messages() -> None:
    with serve(FakeWorkspace.from_fixture()) as url:
        try:
            _client(url, token="super-secret-value").get("/api/2.0/sql/warehouses")
        except ConnectionFailedError as exc:
            assert "super-secret-value" not in exc.message
