from __future__ import annotations

from dbx_premig.catalog.loader import load_catalog
from dbx_premig.config import load_settings
from dbx_premig.estimation import summarise
from dbx_premig.estimation.complexity import assess_assets, classify, weighted_penalty
from dbx_premig.estimation.rounding import round_hours
from dbx_premig.models import AssetRecord, DiscoveryReport, FeatureHit, Finding


def _f(support: str) -> Finding:
    return Finding(
        feature_id="X", category="c", occurrences=1, penalty=1, support=support, guidance="g"
    )


def test_classify_first_match_wins() -> None:
    s = load_settings()
    assert classify(100, [_f("unsupported")], s) == "Unsupported"
    assert classify(80, [], s) == "Compatible"
    assert classify(79, [], s) == "Partial"
    assert classify(50, [], s) == "Partial"
    assert classify(49, [], s) == "Manual"


def test_thresholds_are_settings() -> None:
    s = load_settings(readiness_compatible_min=90)
    assert classify(85, [], s) == "Partial"


def test_weighted_penalty_caps_occurrences() -> None:
    assert weighted_penalty(10, 1, 10) == 10
    assert weighted_penalty(10, 3, 10) == 12
    assert weighted_penalty(10, 500, 10) == weighted_penalty(10, 10, 10)


def test_assess_assets_scores_and_unknowns() -> None:
    s = load_settings()
    assets = [
        AssetRecord(
            key="Notebook:/a",
            asset_type="Notebook",
            name="a",
            features=(FeatureHit(feature_id="AUTOLOADER"), FeatureHit(feature_id="DLT")),
        ),
        AssetRecord(
            key="Job:1",
            asset_type="Job",
            name="j",
            features=(FeatureHit(feature_id="JOB-TASK-WEIRD_TASK"),),
        ),
        AssetRecord(
            key="Serving Endpoint:e",
            asset_type="Serving Endpoint",
            name="e",
            features=(FeatureHit(feature_id="SERVING-NO-EQUIVALENT"),),
        ),
    ]
    out, warnings = assess_assets(assets, load_catalog(), s)
    by = {a.key: a for a in out}
    assert by["Notebook:/a"].readiness_score == 52 and by["Notebook:/a"].readiness == "Partial"
    assert by["Job:1"].readiness == "Compatible"
    assert by["Serving Endpoint:e"].readiness == "Unsupported"
    assert by["Notebook:/a"].fabric_target == "Fabric Notebook"
    assert len(warnings) == 1 and "JOB-TASK-WEIRD_TASK" in warnings[0].message


def test_score_never_negative() -> None:
    hits = tuple(
        FeatureHit(feature_id=f, occurrences=50)
        for f in ("DLT", "AUTOLOADER", "DBX-SDK", "FEATURE-STORE")
    )
    out, _ = assess_assets(
        [AssetRecord(key="k", asset_type="Notebook", name="n", features=hits)],
        load_catalog(),
        load_settings(),
    )
    assert out[0].readiness_score == 0 and out[0].readiness == "Manual"


def test_summary_matches_fixture(report: DiscoveryReport) -> None:
    s = summarise(report)
    assert s.total_assets == 41
    assert sum(s.by_readiness.values()) == 41
    assert s.by_readiness == {"Compatible": 25, "Partial": 12, "Manual": 2, "Unsupported": 2}
    assert s.top_findings[0] == ("UC-3PART", 6)


def test_round_hours_half_up() -> None:
    assert round_hours(2.25) == 2.3
    assert round_hours(2.35) == 2.4
    assert round_hours(0.05, 1) == 0.1
    assert round_hours(1.005, 2) == 1.01
