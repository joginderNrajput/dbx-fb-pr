"""THE orchestration layer. CLI, prompts, root scripts (and later the API) only call this.

    discover_live(settings)          -> RawSnapshot   (reads the workspace, GET only)
    discover_offline(path, settings) -> RawSnapshot   (folder / .dbc / .zip / snapshot.json)
    build_report(snapshot, settings) -> DiscoveryReport  (parse + readiness; offline, pure)
    run_discovery(...)               -> DiscoveryResult   (all of the above + files written)

    run_assessment(workbook, settings)  -> AssessmentRun  (discovery .xlsx -> assessment .xlsx)
    run_analysis(...)                    -> discovery + assessment in one call

``analyze`` IS ``assess(discover(...))``: it writes the discovery workbook and assesses that
file, so the one-shot and the two-step routes cannot give different numbers.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from dbx_premig.catalog.loader import Catalog, load_catalog
from dbx_premig.client import Credentials, DatabricksClient, resolve_credentials
from dbx_premig.collector import ProgressFn, collect_workspace
from dbx_premig.config import Settings
from dbx_premig.errors import NothingFoundError
from dbx_premig.estimation import assess_assets
from dbx_premig.excel.discovery_writer import write_discovery_workbook
from dbx_premig.logging import get_logger
from dbx_premig.models import AssessmentResult, DiscoveryReport, RawSnapshot, ScanInfo
from dbx_premig.offline import snapshot_from_path
from dbx_premig.parser import ParserRules, parse_snapshot

__all__ = [
    "AssessmentRun",
    "DiscoveryResult",
    "build_report",
    "discover_live",
    "discover_offline",
    "parser_rules",
    "run_analysis",
    "run_assessment",
    "run_discovery",
    "save_snapshot",
]

log = get_logger("service")


@dataclass(frozen=True)
class DiscoveryResult:
    report: DiscoveryReport
    workbook: Path
    snapshot: Path | None


def parser_rules(catalog: Catalog, settings: Settings) -> ParserRules:
    return ParserRules(
        code_patterns=tuple((p.feature_id, p.regex) for p in catalog.code_patterns()),
        task_features={k: v.feature for k, v in catalog.job_task_types.items()},
        task_activities={k: v.activity for k, v in catalog.job_task_types.items()},
        occurrence_cap=settings.occurrence_cap,
    )


def discover_live(
    settings: Settings,
    progress: ProgressFn | None = None,
    credentials: Credentials | None = None,
) -> RawSnapshot:
    """Read the workspace named by ``credentials`` or the settings / environment / profile."""
    creds = credentials or resolve_credentials(settings)
    log.info("connecting to %s (%s, from %s)", creds.host, creds.auth_kind, creds.source)
    client = DatabricksClient(creds, settings)
    snapshot = collect_workspace(client, settings, progress)
    log.info("collected with %d API calls", client.calls)
    return snapshot


def discover_offline(input_path: Path, settings: Settings) -> RawSnapshot:
    return snapshot_from_path(input_path, settings)


def build_report(
    snapshot: RawSnapshot, settings: Settings, generated_at: datetime | None = None
) -> DiscoveryReport:
    """Parse and classify. Pure and deterministic for a given snapshot and clock."""
    catalog = load_catalog()
    estate = parse_snapshot(snapshot, parser_rules(catalog, settings), settings)
    assessments, catalog_warnings = assess_assets(estate.assets, catalog, settings)
    if catalog_warnings:
        estate = estate.model_copy(update={"warnings": estate.warnings + catalog_warnings})
    meta = snapshot.meta
    when = (generated_at or datetime.now(UTC)).replace(microsecond=0)
    scan = ScanInfo(
        mode=snapshot.mode,
        source=snapshot.source,
        cloud=str(meta.get("cloud", "")),
        workspace_id=str(meta.get("workspace_id", "")),
        metastore=str(meta.get("metastore", "")),
        collectors=tuple(str(c) for c in meta.get("collectors", [])),
        captured_at=snapshot.captured_at,
        generated_at=when.strftime("%Y-%m-%d %H:%M UTC"),
    )
    return DiscoveryReport(scan=scan, estate=estate, assessments=assessments)


def _slug(source: str) -> str:
    host = re.sub(r"^https?://", "", source).split("/")[0] if "://" in source else Path(source).name
    return re.sub(r"[^A-Za-z0-9]+", "-", host.split(".")[0]).strip("-")[:40] or "workspace"


def default_output_name(snapshot: RawSnapshot, when: datetime, suffix: str) -> str:
    return f"databricks_discovery_{_slug(snapshot.source)}_{when:%Y%m%d_%H%M}{suffix}"


def save_snapshot(snapshot: RawSnapshot, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot.model_dump(), indent=1, ensure_ascii=False), "utf-8")
    return path


def run_discovery(
    settings: Settings,
    *,
    input_path: Path | None,
    output_dir: Path,
    output_name: str | None = None,
    keep_snapshot: bool = False,
    progress: ProgressFn | None = None,
    credentials: Credentials | None = None,
) -> DiscoveryResult:
    """One call for every surface: collect (live or offline), classify, write the files."""
    snapshot = (
        discover_offline(input_path, settings)
        if input_path
        else discover_live(settings, progress, credentials)
    )
    report = build_report(snapshot, settings)
    if not report.assessments and not report.estate.catalogs and not report.estate.identities:
        raise NothingFoundError(
            "Nothing was discovered: no notebooks, jobs, compute or catalog objects were "
            "visible. Check the token's permissions (see the warnings with --verbose)."
        )
    when = datetime.now(UTC)
    name = output_name or default_output_name(snapshot, when, ".xlsx")
    if not name.lower().endswith(".xlsx"):
        name += ".xlsx"
    workbook = write_discovery_workbook(report, output_dir / name, settings)
    snap_path = None
    if keep_snapshot and snapshot.mode == "live":
        snap_path = save_snapshot(snapshot, output_dir / (Path(name).stem + "_snapshot.json"))
    return DiscoveryResult(report=report, workbook=workbook, snapshot=snap_path)


@dataclass(frozen=True)
class AssessmentRun:
    result: AssessmentResult
    workbook: Path
    discovery: DiscoveryResult | None = None


def run_assessment(
    settings: Settings,
    *,
    discovery_workbook: Path,
    output_dir: Path,
    output_name: str | None = None,
    rules_file: Path | None = None,
    generated_at: datetime | None = None,
) -> AssessmentRun:
    """Assess a discovery workbook with the rules file and write the assessment workbook."""
    from dbx_premig.estimation.effort import assess_workbook
    from dbx_premig.estimation.rules import load_rules
    from dbx_premig.excel.assessment_writer import write_assessment_workbook
    from dbx_premig.excel.discovery_reader import read_discovery_workbook

    rules = load_rules(rules_file or settings.assessment_rules)
    workbook = read_discovery_workbook(discovery_workbook, settings)
    if not workbook.assets:
        raise NothingFoundError(f"{discovery_workbook.name} has no assessable objects.")
    result = assess_workbook(
        workbook, rules, occurrence_cap=settings.occurrence_cap, generated_at=generated_at
    )
    when = generated_at or datetime.now(UTC)
    stem = re.sub(r"_\d{8}_\d{4}$", "", Path(discovery_workbook).stem)
    stem = stem.replace("databricks_discovery_", "") or "workspace"
    name = output_name or f"databricks_assessment_{stem}_{when:%Y%m%d_%H%M}.xlsx"
    if not name.lower().endswith(".xlsx"):
        name += ".xlsx"
    path = write_assessment_workbook(result, output_dir / name, settings, rules.text, rules.sha256)
    return AssessmentRun(result=result, workbook=path)


def run_analysis(
    settings: Settings,
    *,
    input_path: Path | None,
    output_dir: Path,
    rules_file: Path | None = None,
    keep_snapshot: bool = False,
    progress: ProgressFn | None = None,
    credentials: Credentials | None = None,
) -> AssessmentRun:
    """Discovery (live or offline) followed by the assessment of the workbook it wrote."""
    discovery = run_discovery(
        settings,
        input_path=input_path,
        output_dir=output_dir,
        keep_snapshot=keep_snapshot,
        progress=progress,
        credentials=credentials,
    )
    run = run_assessment(
        settings, discovery_workbook=discovery.workbook, output_dir=output_dir,
        rules_file=rules_file,
    )  # fmt: skip
    return AssessmentRun(result=run.result, workbook=run.workbook, discovery=discovery)
