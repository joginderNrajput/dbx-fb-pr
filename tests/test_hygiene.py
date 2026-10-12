"""Repository rules from CLAUDE.md that are cheap to enforce mechanically."""

from __future__ import annotations

import hashlib
import re
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
PKG = ROOT / "dbx_premig"


def _modules() -> list[Path]:
    return sorted(PKG.rglob("*.py"))


def test_every_module_has_future_import_and_all() -> None:
    for path in _modules():
        text = path.read_text()
        assert "from __future__ import annotations" in text, path
        if path.name != "__main__.py":
            assert "__all__" in text, path


def test_no_descendant_search_in_parser() -> None:
    assert ".//" not in (PKG / "parser.py").read_text()


def test_no_path_from_file_outside_resources() -> None:
    for path in _modules():
        if path.name != "resources.py":
            assert "__file__" not in path.read_text(), path


def test_default_port_is_a_setting_not_a_literal() -> None:
    for path in _modules():
        if path.name != "config.py":
            assert "7073" not in path.read_text(), path


def test_no_extractall() -> None:
    for path in _modules():
        assert ".extractall(" not in path.read_text(), path


def test_collector_only_reads() -> None:
    """The live path never sends anything but GET (the OAuth token request aside)."""
    text = (PKG / "client.py").read_text()
    assert text.count('method="POST"') == 1 and "/oidc/v1/token" in text
    assert not re.search(r'method="(PUT|PATCH|DELETE)"', text)


@pytest.mark.parametrize(
    ("member", "asset"),
    [("xl/media/image1.png", "banner.png"), ("xl/media/image2.png", "kanerika_logo.png")],
)
def test_brand_assets_copied_byte_identically(member: str, asset: str) -> None:
    template = ROOT / "Tempelate_sheet.xlsx"
    if not template.is_file():
        pytest.skip("reference workbook not present")
    with zipfile.ZipFile(template) as zf:
        expected = hashlib.sha256(zf.read(member)).hexdigest()
    actual = hashlib.sha256((PKG / "excel" / "assets" / asset).read_bytes()).hexdigest()
    assert actual == expected


def test_version_consistent() -> None:
    from dbx_premig.version import APP_VERSION

    pyproject = (ROOT / "pyproject.toml").read_text()
    assert f'version = "{APP_VERSION}"' in pyproject
    info = (ROOT / "packaging" / "file_version_info.txt").read_text()
    assert f"StringStruct('FileVersion', '{APP_VERSION}')" in info
    nums = tuple(int(x) for x in APP_VERSION.split("."))
    assert f"filevers=({nums[0]}, {nums[1]}, {nums[2]}, 0)" in info


def test_spec_bundles_every_resource_dir() -> None:
    spec = (ROOT / "packaging" / "dbx_premig.spec").read_text()
    assert '"catalog" / "data"' in spec and '"excel" / "assets"' in spec
    assert "upx=False" in spec and "discovery.py" in spec
