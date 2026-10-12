from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from dbx_premig.catalog.loader import load_catalog, load_catalog_file
from dbx_premig.errors import CatalogError

PARSER = Path(__file__).parent.parent / "dbx_premig" / "parser.py"


def test_catalog_loads_and_ids_unique() -> None:
    cat = load_catalog()
    ids = [f.id for f in cat.features]
    assert len(ids) == len(set(ids))
    assert len(cat.code_patterns()) >= 30


def test_every_structural_id_in_parser_is_in_catalog() -> None:
    """A feature id the parser emits but the catalog lacks would silently become 'unknown'."""
    cat = load_catalog()
    emitted = set(re.findall(r'"([A-Z]{2,}(?:-[A-Z0-9]+)+)"', PARSER.read_text()))
    emitted |= {t.feature for t in cat.job_task_types.values() if t.feature}
    emitted |= {f"LIB-{k}" for k in ("REQUIREMENTS", "WHL", "JAR", "CRAN", "MAVEN", "EGG")}
    missing = sorted(i for i in emitted if not cat.is_known(i))
    assert not missing, missing


def test_unknown_feature_is_synthetic_not_dropped() -> None:
    entry = load_catalog().feature("NOT-A-FEATURE")
    assert entry.support == "unknown" and entry.penalty == 0


def test_every_asset_type_has_a_target() -> None:
    cat = load_catalog()
    for t in ("Notebook", "Job", "Table", "View", "Dashboard", "Serving Endpoint"):
        assert cat.target_for(t) != "Review manually"
    assert cat.target_for("Spaceship") == "Review manually"


def _write(tmp_path: Path, data: object) -> Path:
    p = tmp_path / "f.yaml"
    p.write_text(yaml.safe_dump(data))
    return p


def test_invalid_catalogs_rejected(tmp_path: Path) -> None:
    base = yaml.safe_load(
        (Path(__file__).parent.parent / "dbx_premig/catalog/data/features.yaml").read_text()
    )
    dup = {**base, "features": [*base["features"], base["features"][0]]}
    with pytest.raises(CatalogError, match="repeats"):
        load_catalog_file(_write(tmp_path, dup))
    bad_re = {**base, "features": [{**base["features"][0], "pattern": "("}]}
    with pytest.raises(CatalogError, match="invalid pattern"):
        load_catalog_file(_write(tmp_path, bad_re))
    no_pat = {**base, "features": [{**base["features"][0], "pattern": None}]}
    with pytest.raises(CatalogError, match="no pattern"):
        load_catalog_file(_write(tmp_path, no_pat))
    bad_support = {**base, "features": [{**base["features"][0], "support": "maybe"}]}
    with pytest.raises(CatalogError):
        load_catalog_file(_write(tmp_path, bad_support))
    bad_task = {**base, "job_task_types": {"x_task": {"activity": "a", "feature": "NOPE"}}}
    with pytest.raises(CatalogError, match="unknown feature"):
        load_catalog_file(_write(tmp_path, bad_task))
    with pytest.raises(CatalogError):
        load_catalog_file(tmp_path / "missing.yaml")
