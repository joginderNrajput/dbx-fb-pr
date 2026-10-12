# Methodology — every number and why

## What is counted

Each data sheet has one row per Databricks object the identity can see. **Totals** counts the
rows with live formulas (`COUNTA`, `COUNTIF`, `SUM`), so the dashboard always agrees with the
data sheets, including after manual edits.

Deliberately not counted:

| Skipped | Reason |
|---|---|
| Clusters with source `JOB`, `PIPELINE`, `PIPELINE_MAINTENANCE`, `MODELS` | created per run; their config is on the job / pipeline |
| Catalogs `system`, `samples`, `__databricks_internal` | platform-owned (setting `skip_catalogs`) |
| `information_schema` schemas | metadata views |
| Serving endpoints named `databricks-*` | Databricks-hosted foundation models |
| External locations / credentials named `__databricks*`, `databricks-*` | managed storage |

## Assessable objects

Objects that need a migration decision become one row on **Assets**: notebooks, jobs, DLT
pipelines, clusters, SQL warehouses, tables, views, materialized views, streaming tables,
volumes, external locations, storage credentials, connections, functions, SQL queries,
dashboards, alerts, ML models, serving endpoints, libraries, secret scopes, mounts and repos.
Reference data (schemas, columns, grants, pools, policies, experiments, identities) is
inventoried but not scored.

## Features

The parser records which **features** each object uses:

* **Code features** — notebook source, view definitions, function bodies, SQL queries and
  alert queries are matched against the `code` patterns in `features.yaml` (37 regular
  expressions: `dbutils.*`, `%run`, DBFS paths, Auto Loader, DLT, `COPY INTO`, Unity Catalog
  three-part names, Feature Store, AI functions …). Matching is case-insensitive and counts
  occurrences.
* **Structural features** — derived from metadata: job task types, schedules, continuous
  runs, file-arrival triggers, init scripts, Docker images, GPU nodes, old runtimes, table
  type and format, Change Data Feed, deletion vectors, row filters / column masks, special
  data types, hive_metastore, library type, secret scopes, mounts.

## Readiness score

For each asset:

```
penalty(feature) = catalog penalty × (1 + 0.1 × (min(occurrences, 10) − 1))
readiness score  = max(0, 100 − round(Σ penalty))
```

So a feature seen ten or more times weighs 1.9 × its base penalty; more occurrences add
nothing (setting `occurrence_cap`).

Classification, first match wins:

| Rule | Level | Meaning |
|---|---|---|
| any finding with verdict `unsupported` | **Unsupported** | no Fabric equivalent (e.g. model serving, Python eggs, clean rooms) |
| score ≥ 80 | **Compatible** | lift and shift with small edits |
| score ≥ 50 | **Partial** | convert and configure |
| otherwise | **Manual** | redesign or rewrite |

Thresholds are settings (`readiness_compatible_min`, `readiness_partial_min`). Penalties and
verdicts are in `features.yaml`. They are this tool's heuristics, inherited from and extending
the earlier prototype script, not an industry standard.

**Average readiness score** on Totals is the simple mean over all assessable objects.

## Effort points (Totals, bottom)

`points = count × weight` per driver, summed to **Portfolio points**. The weights are yellow,
editable cells. They exist to compare estates of different sizes and to make the drivers of
effort visible. They are **not hours**; hours come from the later `assess` flow, after the
artifact owner has reviewed this workbook.

## Dependencies

Edges come from `%run`, `dbutils.notebook.run("…")`, job tasks (notebook, DLT pipeline, run
job, SQL query) and DLT pipeline libraries. Paths are normalised (`/Workspace` prefix
removed, `./` and `../` resolved, file extension dropped). *Resolved = No* means the target is
not in this discovery: deleted, outside the scanned scope, or built dynamically at run time.
