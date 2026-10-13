# Assessment — rules file, workbook and database tables

The assessment is built **on top of the discovery workbook**. It reads the workbook back
(Assets, Findings and the detail sheets, joined on `Asset key`), applies the formulas of a
**rules file**, and produces:

1. the **assessment workbook** (`databricks_assessment_*.xlsx`), and
2. optionally, rows in **Postgres** (`totals`, `inventory`, `finding`, `estimation`,
   `computation`) tagged with `organization_id` and `job_id`, for dashboards.

```
Databricks creds ──► discovery ──► discovery.xlsx ──► assessment ──► assessment.xlsx
                                        ▲                  │
              uploaded discovery.xlsx ──┘                  └──► Postgres (optional)
```

`analyze` / the API with credentials = discovery followed by the assessment *of the workbook
the discovery wrote*, so the one-shot and two-step routes always give the same numbers.

---

## 1. The rules file (all formulas, configurable)

Default: `dbx_premig/estimation/data/assessment_rules.yaml` (bundled in the package and the
executable). To change the formulas, **copy it, edit the copy, and point the tool at it** —
no code change:

```bash
python discovery.py rules-check --rules my_rules.yaml          # validate only
python discovery.py assess --input discovery.xlsx --rules my_rules.yaml
export DBXF_ASSESSMENT_RULES=/path/my_rules.yaml               # CLI and API default
```

Every expression is validated when the file loads (unknown variable, syntax error, wrong
level names → exit code 5 with the exact key at fault). The file name, version and SHA-256
prefix are stored with every assessment (`computation.rules_version`, the Rules sheet).

### Expression language

Python-like and sandboxed (never `eval`): numbers, `"strings"`, `true`/`false`,
`+ - * / // % **`, comparisons, `and or not`, `a if cond else b`, and the functions
`min max round abs ceil floor sqrt log` (`round` is half-up). Division by zero gives 0.

### Variables per asset

| Variable | Meaning |
|---|---|
| `asset_type`, `name` | e.g. `"Notebook"`, `"/Shared/etl/ingest"` |
| `readiness`, `readiness_score` | discovery classification (`Compatible`/`Partial`/`Manual`/`Unsupported`, 0–100) |
| `findings`, `occurrences` | distinct Databricks features found, and their total occurrences |
| `penalty_total` | Σ catalog penalty × occurrence weight (same rule as the readiness score) |
| `manual_findings`, `unsupported_findings` | findings whose verdict is manual / unsupported |
| `total_constructs`, `supported_constructs`, `unsupported_constructs`, `unsupported_ratio` | see below |
| `lines`, `cells`, `notebook_calls`, `sql_statements`, `magic_commands`, `size_bytes` | notebooks |
| `tasks` | jobs (rows on JobTasks) |
| `columns`, `definition_chars` | tables / views; `definition_chars` also for functions (body) |
| `libraries` | DLT pipelines |

Size metrics are 0 when they do not apply. Later stages also see `size_points`, `score`,
`level`, `automation_level`, `base_hours`, `size_hours`, `dev_factor`, `test_factor`,
`manual_dev_hours`, `manual_test_hours`.

### Stages (in this order)

| Key | Produces | Default |
|---|---|---|
| `base_constructs`, `support_weights` | constructs = 1 (the object) + 1 per finding; supported = base + Σ weight(verdict) | supported 1, partial 0.5, manual 0, unsupported 0, unknown 0.5 |
| `complexity.size_points.<type>` | size points | e.g. Notebook `lines / 40 + cells / 4 + notebook_calls * 2 + magic_commands`, Job `tasks * 3` |
| `complexity.score` | complexity score 0–100 | `min(100, round(penalty_total + size_points))` |
| `complexity.levels` | **Simple / Medium / Complex** (first match wins) | `< 20` Simple, `< 50` Medium, else Complex |
| `automation` | **Fully automated / Partially automated / Manual** (first match wins) | Manual if readiness Manual/Unsupported; Fully if Compatible with no manual/unsupported finding; else Partially |
| `effort.base_hours.<type>.<level>` | `base_hours` | e.g. Notebook 2 / 6 / 16, DLT 8 / 16 / 32, Dashboard 4 / 8 / 16 |
| `effort.size_hours.<type>` | `size_hours` | Notebook `lines / 500`, Job `tasks * 0.25`, SQL Query `lines / 200` |
| `effort.automation_factors.<level>` | `dev_factor`, `test_factor` | Fully 0.2 / 0.5, Partially 0.55 / 0.75, Manual 1 / 1 |
| `effort.manual_dev_hours` | | `base_hours + size_hours` |
| `effort.manual_test_hours` | | `manual_dev_hours * 0.35` |
| `effort.automation_dev_hours` | | `manual_dev_hours * dev_factor` |
| `effort.automation_test_hours` | | `manual_test_hours * test_factor` |
| `hours_decimal_places` | rounding per asset (half-up) | 2 |

`hours_saved = (manual dev + test) − (automation dev + test)` per asset. Portfolio totals
are sums of the **rounded** per-asset figures; `saving_pct = hours_saved / total_manual_hours`
(stored as a fraction, shown as %).

The default numbers are Kanerika planning heuristics, not a quote. Calibrate them with real
project actuals by editing a copy of the file.

---

## 2. The assessment workbook

| Sheet | Holds |
|---|---|
| **Assessment** | dashboard: 12 tiles (assets, Simple/Medium/Complex, Fully/Partially/Manual, constructs, manual hours, hours with automation, hours saved, saving %), run summary, 3 charts |
| **Estimation** | one row per asset: readiness, constructs, complexity score and level, automation level, the four hour figures, totals (formulas), hours saved |
| **EffortByType** | live roll-up per asset type (COUNTIFS / SUMIF over Estimation) |
| **Summary** | the single source of truth: every portfolio figure is a formula over Estimation; plus the run properties and the discovery item counts |
| **Rules** | the exact rules file used (line by line) and its SHA-256 |
| **About** | how to read the workbook |

Editing an Estimation value (e.g. after a workshop) updates Summary, EffortByType, the tiles
and the charts. Re-run the assessment to apply a new rules file to every asset.

---

## 3. Database tables

The tables live in the existing Azure Database for PostgreSQL named by `DBXF_DATABASE_URL`
(in `.env`), schema `DBXF_DB_SCHEMA`. They are created and changed **only by Alembic
migrations** (`dbx_premig/db/migrations/versions/`):

```bash
python discovery.py db-init            # = alembic upgrade head (idempotent)
alembic upgrade head                   # same, from the repository root (alembic.ini)
alembic current                        # which revision the database is at
python discovery.py db-init --print-sql   # the SQL, without touching a database
```

The migration state is kept in `dbx_premig_alembic_version` (`<prefix>alembic_version` with a
table prefix) in the same schema, so it never mixes with another tool's `alembic_version`.
**Sharing a schema** with the Alteryx accelerator (which already has `totals`, `inventory`,
`estimation`, `computation`): set `DBXF_DB_TABLE_PREFIX=dbx_` and the tables become
`dbx_totals`, `dbx_inventory`, `dbx_finding`, `dbx_estimation`, `dbx_computation`. Without a
prefix, `db-init` refuses to touch same-named tables it did not create (exit 9) and changes
nothing. Remote hosts are reached with `sslmode=require`.

Every table carries `organization_id` and
`job_id` (indexed). Persisting again for the same pair **replaces** that pair's rows in one
transaction (delete children → insert), so a re-run never duplicates.

| Table | One row per | Main columns |
|---|---|---|
| `totals` | scan | `scan_id` (PK), source, mode, cloud, metastore, collectors, discovery_workbook, captured_at, discovered_at, **one count column per Databricks item type** (notebooks, notebook_lines, python/sql/scala/r_notebooks, repos, dependencies, jobs, job_tasks, scheduled/continuous_jobs, dlt_pipelines, clusters, gpu_clusters, instance_pools, cluster_policies, sql_warehouses, libraries, catalogs, schemas, tables, managed/external/foreign/hive_metastore tables, views, materialized_views, streaming_tables, columns, volumes, external_locations, storage_credentials, connections, functions, grants, sql_queries, dashboards, alerts, ml_models, serving_endpoints, experiments, secret_scopes, secrets, mounts, users, groups, service_principals, assessable/compatible/partial/manual/unsupported assets, avg_readiness_score, findings, warnings) |
| `inventory` | assessable object | `inventory_id` (PK), `scan_id` (FK), asset_key, asset_type, asset_name, location, fabric_target, readiness, readiness_score, findings, finding_ids, lines, cells, tasks, columns |
| `finding` | feature found on an object | `finding_id`, `scan_id`, `inventory_id` (FKs), rule, category, occurrences, penalty, support, guidance |
| `estimation` | assessed object | `estimation_id`, `scan_id`, `inventory_id` (FKs), asset_name, asset_type, location, total_constructs, supported, unsupported (numeric 14,6), complexity_score, complexity_level, recommended_target, automation_level, readiness, manual/automation dev/test hours, hours_saved |
| `computation` | scan (unique) | `computation_id`, `scan_id` (FK, unique), assessment_generated_at, total_assets, total_constructs, supported/unsupported_constructs, simple/medium/complex_count, fully_automated, partially_automated, manual, manual_dev/test_hours, total_manual_hours, automation_dev/test_hours, total_automation_hours, hours_saved, saving_pct, rules_version |

### Mapping to the Alteryx accelerator's tables

The structure follows `alteryx_to_databricks_premigration.{totals, inventory, estimation,
computation}`; the Alteryx-specific names are translated to Databricks terms:

| Alteryx column | Here | Why |
|---|---|---|
| `total_workflows` | `total_assets` | Databricks has notebooks, jobs, tables … not workflows |
| `total_tools` / `supported_tools` / `unsupported_tools` | `total_constructs` / `supported_constructs` / `unsupported_constructs` | an object plus the platform features it uses |
| `low_count` | `simple_count` | levels are Simple / Medium / Complex |
| `estimation.workflow_id` → `inventory.workflow_id` | `estimation.inventory_id` → `inventory.inventory_id` | |
| `estimation.file_name`, `file_type` | `asset_name`, `asset_type` (+ `location`) | names repeat across folders, so the unique key is (`scan_id`, `inventory_id`) |
| `recommended_engine` | `recommended_target` | the Fabric item (Notebook, Data Factory pipeline, Lakehouse …) |
| `ON CONFLICT (computation_id) DO UPDATE` | delete-then-insert per (`organization_id`, `job_id`) in one transaction | same idempotent result, and children never orphaned |

### Example dashboard queries

```sql
-- latest portfolio per job
SELECT organization_id, job_id, total_assets, simple_count, medium_count, complex_count,
       total_manual_hours, total_automation_hours, saving_pct
FROM databricks_to_fabric_premigration.computation;

-- hours by asset type
SELECT asset_type, count(*), sum(manual_dev_hours + manual_test_hours) AS manual_hours,
       sum(automation_dev_hours + automation_test_hours) AS automation_hours
FROM databricks_to_fabric_premigration.estimation
WHERE organization_id = :org AND job_id = :job
GROUP BY asset_type ORDER BY manual_hours DESC;

-- discovery counts
SELECT notebooks, jobs, dlt_pipelines, clusters, tables, views, columns, dashboards
FROM databricks_to_fabric_premigration.totals WHERE organization_id = :org AND job_id = :job;
```
