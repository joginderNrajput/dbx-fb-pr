"""Orchestration: Jobs, JobTasks, DLTPipelines."""

from __future__ import annotations

from dbx_premig.excel.sheets.common import assessed_columns, yes_no
from dbx_premig.excel.types import Column, SheetSpec

__all__ = ["DLT_PIPELINES", "JOBS", "JOB_TASKS"]

N = "#,##0"

JOBS = SheetSpec(
    name="Jobs",
    title="Jobs  ·  Databricks Workflows",
    description=(
        "One row per job: schedule, triggers, task mix and readiness. Each job becomes a "
        "Fabric Data Factory pipeline; Tasks counts the rows on JobTasks."
    ),
    columns=[
        Column("Job id", "job_id", 16),
        Column("Name", "name", 36),
        Column("Creator", "creator", 26),
        Column("Created", "created_at", 16),
        Column(
            "Tasks",
            formula="=COUNTIF('JobTasks'!$A$7:$A$1048576,$A{r})",
            width=8,
            numeric=True,
            number_format=N,
        ),
        Column("Task types", "task_types", 36),
        Column("Schedule (Quartz cron)", "schedule", 20),
        Column("Timezone", "timezone", 16),
        Column("Pause status", "pause_status", 12),
        Column("Trigger", "trigger", 16),
        Column("Continuous", yes_no("continuous"), 10),
        Column("Job clusters", "job_clusters", 9, numeric=True, number_format=N),
        Column("Notifications", yes_no("notifications"), 12),
        Column("Max concurrent runs", "max_concurrent_runs", 11, numeric=True, number_format=N),
        Column("Timeout (s)", "timeout_s", 10, numeric=True, number_format=N),
        Column("Run as", "run_as", 24),
        Column("Tags", "tags", 24),
        *assessed_columns(),
    ],
    rows=lambda r: r.estate.jobs,
    readiness_column="Readiness",
)

JOB_TASKS = SheetSpec(
    name="JobTasks",
    title="Job tasks  ·  one row per task in every job",
    description="Every task of every job, what it runs, on which compute, and its Fabric activity.",
    columns=[
        Column("Job id", "job_id", 16),
        Column("Job", "job_name", 32),
        Column("Task key", "task_key", 24),
        Column("Task type", "task_type", 20),
        Column("Runs", "target", 46),
        Column("Depends on", "depends_on", 24),
        Column("Compute", "compute", 28),
        Column("Libraries", "libraries", 9, numeric=True, number_format=N),
        Column("Max retries", "max_retries", 9, numeric=True, number_format=N),
        Column("Timeout (s)", "timeout_s", 10, numeric=True, number_format=N),
        Column("Fabric activity", "fabric_activity", 38),
    ],
    rows=lambda r: r.estate.job_tasks,
)

DLT_PIPELINES = SheetSpec(
    name="DLTPipelines",
    title="Delta Live Tables / Lakeflow pipelines",
    description=(
        "DLT pipelines have no direct Fabric equivalent: plan a redesign as Materialized Lake "
        "Views or Spark jobs."
    ),
    columns=[
        Column("Pipeline id", "pipeline_id", 38),
        Column("Name", "name", 30),
        Column("State", "state", 10),
        Column("Catalog", "catalog", 14),
        Column("Target schema", "target_schema", 16),
        Column("Edition", "edition", 10),
        Column("Continuous", yes_no("continuous"), 10),
        Column("Serverless", yes_no("serverless"), 10),
        Column("Photon", yes_no("photon"), 8),
        Column("Development", yes_no("development"), 11),
        Column("Channel", "channel", 10),
        Column("Libraries", "libraries", 9, numeric=True, number_format=N),
        Column("Source notebooks", "notebooks", 46),
        Column("Creator", "creator", 24),
        *assessed_columns(),
    ],
    rows=lambda r: r.estate.pipelines,
    readiness_column="Readiness",
)
