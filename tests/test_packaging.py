from __future__ import annotations

import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent


@pytest.mark.slow
def test_wheel_carries_each_resource_once(tmp_path: Path) -> None:
    uv = shutil.which("uv")
    cmd = (
        [uv, "build", "--wheel", "--out-dir", str(tmp_path), str(ROOT)]
        if uv
        else [sys.executable, "-m", "pip", "wheel", "--no-deps", "-w", str(tmp_path), str(ROOT)]
    )
    subprocess.run(cmd, check=True, capture_output=True, timeout=600)
    wheel = next(tmp_path.glob("dbx_premig-*.whl"))
    names = zipfile.ZipFile(wheel).namelist()
    for resource in (
        "dbx_premig/catalog/data/features.yaml",
        "dbx_premig/excel/assets/banner.png",
        "dbx_premig/excel/assets/kanerika_logo.png",
        "dbx_premig/excel/assets/platform_logo.png",
        "dbx_premig/excel/assets/titles/Discovery.png",
    ):
        assert names.count(resource) == 1, resource
