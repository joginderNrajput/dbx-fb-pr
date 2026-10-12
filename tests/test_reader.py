from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from dbx_premig.config import Settings, load_settings
from dbx_premig.discovery import find_inputs
from dbx_premig.errors import InvalidSnapshotError, NothingFoundError, UnsupportedFileError
from dbx_premig.offline import snapshot_from_path
from dbx_premig.reader import ReadFailure, decode_text, read_archive, read_file, read_snapshot
from tests.archives import dbc_archive, hostile_archives, source_zip
from tests.conftest import NOTEBOOKS


def test_find_inputs_sorted_and_typed() -> None:
    refs = find_inputs(NOTEBOOKS)
    rel = [r.relative_path for r in refs]
    assert rel == sorted(rel, key=lambda p: (p.casefold(), p))
    assert {r.kind for r in refs} == {"source", "ipynb"}


def test_find_inputs_skips_symlinks_and_hidden(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("x = 1")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "b.py").write_text("x")
    (tmp_path / "notes.json").write_text("{}")
    if hasattr(os, "symlink"):
        os.symlink(tmp_path / "a.py", tmp_path / "link.py")
    assert [r.relative_path for r in find_inputs(tmp_path)] == ["a.py"]


def test_find_inputs_errors(tmp_path: Path) -> None:
    with pytest.raises(NothingFoundError):
        find_inputs(tmp_path / "missing")
    with pytest.raises(NothingFoundError):
        find_inputs(tmp_path)
    bad = tmp_path / "x.txt"
    bad.write_text("x")
    with pytest.raises(UnsupportedFileError):
        find_inputs(bad)


def test_read_source_and_ipynb(settings: Settings) -> None:
    refs = {r.relative_path: r for r in find_inputs(NOTEBOOKS)}
    nb = read_file(refs["Shared/train_model.ipynb"], settings)
    assert not isinstance(nb, ReadFailure)
    assert nb.cells == 2 and "FeatureStoreClient" in nb.source
    py = read_file(refs["Shared/etl/ingest_orders.py"], settings)
    assert not isinstance(py, ReadFailure) and py.object_type == "NOTEBOOK"


def test_bad_ipynb_and_oversize(tmp_path: Path) -> None:
    (tmp_path / "bad.ipynb").write_text("{not json")
    (tmp_path / "big.py").write_text("x" * 5000)
    small = load_settings(max_notebook_bytes=1024)
    refs = {r.relative_path: r for r in find_inputs(tmp_path)}
    assert isinstance(read_file(refs["bad.ipynb"], small), ReadFailure)
    assert isinstance(read_file(refs["big.py"], small), ReadFailure)


def test_source_zip_and_dbc(tmp_path: Path, settings: Settings) -> None:
    source_zip(tmp_path / "export.zip")
    dbc_archive(tmp_path / "ws.dbc")
    snap = snapshot_from_path(tmp_path, settings)
    paths = sorted(n["path"] for n in snap.sections["notebooks"])
    assert paths == [
        "export.zip!/export/Shared/a.py",
        "export.zip!/export/Shared/b.sql",
        "ws.dbc!/Shared/etl.scala",
    ]
    messages = " ".join(w["message"] for w in snap.warnings)
    assert "nested archive skipped" in messages
    assert "not a readable notebook" in messages
    scala = next(n for n in snap.sections["notebooks"] if n["path"].endswith("etl.scala"))
    assert scala["language"] == "SCALA" and scala["cells"] == 2


@pytest.mark.parametrize("name", ["zip_slip", "absolute", "symlink", "bomb", "many", "not_zip"])
def test_hostile_archives_refused(tmp_path: Path, name: str) -> None:
    archives = hostile_archives(tmp_path / "evil")
    settings = load_settings(max_archive_entries=20)
    ref = next(r for r in find_inputs(archives[name].parent) if r.path == str(archives[name]))
    result = read_archive(ref, settings)
    assert isinstance(result, ReadFailure), name
    # Nothing is ever written to disk next to the archive.
    assert not (tmp_path / "etc").exists()


def test_one_bad_archive_never_ends_the_run(tmp_path: Path) -> None:
    hostile_archives(tmp_path)
    (tmp_path / "good.py").write_text("dbutils.fs.ls('/')")
    snap = snapshot_from_path(tmp_path, load_settings(max_archive_entries=20))
    assert [n["path"] for n in snap.sections["notebooks"]] == ["good.py"]
    assert len(snap.warnings) >= 5


def test_snapshot_round_trip_and_errors(tmp_path: Path, settings: Settings) -> None:
    from tests.conftest import SNAPSHOT

    snap = read_snapshot(SNAPSHOT, settings)
    assert snap.mode == "live" and "jobs" in snap.sections
    bad = tmp_path / "bad.json"
    bad.write_text("{")
    with pytest.raises(InvalidSnapshotError):
        read_snapshot(bad, settings)
    other = tmp_path / "other.json"
    other.write_text(json.dumps({"hello": 1}))
    with pytest.raises(InvalidSnapshotError):
        read_snapshot(other, settings)
    future = tmp_path / "future.json"
    data = json.loads(SNAPSHOT.read_text())
    data["format_version"] = 99
    future.write_text(json.dumps(data))
    with pytest.raises(InvalidSnapshotError, match="format version"):
        read_snapshot(future, settings)
    with pytest.raises(InvalidSnapshotError):
        read_snapshot(tmp_path / "missing.json", settings)


def test_decode_text_bom_and_invalid() -> None:
    assert decode_text(b"\xef\xbb\xbfabc") == "abc"
    assert decode_text(b"a\xffb") == "a�b"
