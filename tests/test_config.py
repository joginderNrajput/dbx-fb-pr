from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import SecretStr

from dbx_premig.config import ALL_COLLECTORS, load_settings
from dbx_premig.errors import ConfigError


def test_defaults() -> None:
    s = load_settings()
    assert s.collectors == ALL_COLLECTORS
    assert s.api_port == 7073
    assert s.readiness_compatible_min == 80


def test_env_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DBXF_MAX_NOTEBOOKS", "12")
    monkeypatch.setenv("DBXF_CATALOGS", '["main"]')
    s = load_settings()
    assert s.max_notebooks == 12
    assert s.catalogs == ("main",)


def test_precedence_file_env_flags(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = tmp_path / "s.yaml"
    cfg.write_text("max_notebooks: 5\npage_size: 7\n")
    monkeypatch.setenv("DBXF_MAX_NOTEBOOKS", "9")
    s = load_settings(cfg)
    assert s.page_size == 7  # from the file
    assert s.max_notebooks == 9  # env beats file
    s = load_settings(cfg, max_notebooks=3)
    assert s.max_notebooks == 3  # flag beats env


def test_toml_config(tmp_path: Path) -> None:
    cfg = tmp_path / "s.toml"
    cfg.write_text("include_columns = false\n")
    assert load_settings(cfg).include_columns is False


@pytest.mark.parametrize(
    ("name", "content"),
    [("bad.yaml", "a: [1,"), ("bad.ini", "x=1"), ("list.yaml", "- 1\n")],
)
def test_bad_config_files(tmp_path: Path, name: str, content: str) -> None:
    cfg = tmp_path / name
    cfg.write_text(content)
    with pytest.raises(ConfigError):
        load_settings(cfg)


def test_missing_config_file(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        load_settings(tmp_path / "missing.yaml")


def test_unknown_collector_rejected() -> None:
    with pytest.raises(ConfigError) as exc:
        load_settings(collectors=("jobs", "nope"))
    assert "collectors" in exc.value.message


def test_host_normalised_and_secret_hidden() -> None:
    s = load_settings(host="adb-1.azuredatabricks.net/", token=SecretStr("dapi-secret"))
    assert s.host == "https://adb-1.azuredatabricks.net"
    assert "dapi-secret" not in repr(s)
