# Databricks → Microsoft Fabric Pre-Migration Discovery

A Kanerika accelerator that takes stock of a Databricks workspace before a migration to
Microsoft Fabric and writes a branded, client-ready **Excel discovery workbook**: every
notebook, job, DLT pipeline, cluster, SQL warehouse, Unity Catalog object (down to columns),
grant, query, dashboard, alert, model, serving endpoint, library, secret scope, mount, repo and
identity — with the Fabric target and a first readiness classification for each.

* **Read-only**: only `GET` requests against the workspace. Nothing is created, changed or run.
* **Live or offline**: scan a workspace through the REST API, or read exported notebooks
  (`.py .sql .scala .r .ipynb`, `.dbc`, `.zip`) or a saved snapshot.
* **One file to send**: a single executable built with PyInstaller (Windows / Linux / macOS).
* **Assessment on top of discovery**: complexity (Simple / Medium / Complex), automation level
  (Fully / Partially automated / Manual) and manual vs automated hours per object, from a
  configurable rules file; a second branded workbook, optional Postgres tables
  (`totals`, `inventory`, `finding`, `estimation`, `computation`) and a REST API that takes
  either a discovery workbook or Databricks credentials.

## Quick start

```bash
pip install -e ".[dev]"                     # Python 3.11-3.13

# live workspace (prefer environment variables for secrets)
export DATABRICKS_HOST=https://adb-1234567890123456.7.azuredatabricks.net
export DATABRICKS_TOKEN=dapi...
python discovery.py discover --out output

# offline export, or a snapshot from an earlier run
python discovery.py discover --input ./exports --out output

# interactive (what the double-clicked executable does)
python discovery.py
```

No install at all: `uv run discovery.py discover --help` (dependencies come from the PEP 723
header of `discovery.py`).

The workbook path is printed on stdout; progress and a one-line summary on stderr.

## Command line

```
python discovery.py discover [OPTIONS]
  -i, --input PATH        offline: folder / .dbc / .zip / snapshot .json (omit for live)
  --host TEXT             workspace URL            (or DATABRICKS_HOST)
  --token TEXT            personal access token    (or DATABRICKS_TOKEN)
  --client-id/--client-secret   service principal OAuth (or DATABRICKS_CLIENT_ID/_SECRET)
  --profile TEXT          profile in ~/.databrickscfg
  -o, --out PATH          output folder (default: output)
  --name TEXT             workbook file name
  --save-snapshot         also write the raw capture JSON (contains notebook source)
  --only TEXT             comma list of collectors (python discovery.py collectors)
  --catalogs TEXT         comma list of Unity Catalog catalogs
  --schemas TEXT          comma list of schemas (catalog.schema or schema)
  --skip-repos --no-columns --no-view-sql --max-notebooks N --insecure
  -c, --config FILE       settings file (.yaml / .toml); every setting also as DBXF_<NAME>
  -v, --verbose
python discovery.py assess  -i discovery.xlsx [--rules my_rules.yaml] [--persist --org O --job J]
python discovery.py analyze [discover options] [--rules …] [--persist --org O --job J]
python discovery.py rules-check [--rules my_rules.yaml]
python discovery.py db-init [--print-sql]          # needs DBXF_DATABASE_URL
python discovery.py serve [--host --port]          # REST API (api extra)
python discovery.py version | catalog-info | collectors
```

Exit codes: 0 ok · 1 internal error · 2 unsupported file · 4 unsafe archive · 5 catalog /
rules · 6 cannot write · 7 nothing found · 8 invalid snapshot / workbook · 9 database ·
10 connection/auth · 11 configuration.

## The workbook

**Discovery** (dashboard: navigation, 16 KPI tiles, scan summary, charts) → **Assets**
(readiness of every object) → **Findings** (Databricks features that need work, with Fabric
guidance) → one sheet per object type (Notebooks, Dependencies, Repos, Jobs, JobTasks,
DLTPipelines, Clusters, InstancePools, ClusterPolicies, SQLWarehouses, Libraries, Catalogs,
Schemas, Tables, Columns, Views, Volumes, ExternalLocations, StorageCredentials, Connections,
Functions, Grants, SQLQueries, Dashboards, Alerts, Models, ServingEndpoints, Experiments,
SecretScopes, Mounts, Identities) → **Warnings** → **Information** → **Totals** (the single
source of truth: every number is a live formula).

## The assessment

`analyze` (or `assess` on an existing discovery workbook) writes
`databricks_assessment_*.xlsx`: **Assessment** dashboard, **Estimation** (per object),
**EffortByType**, **Summary** (single source of truth), **Rules** (the formulas used), **About**.
All formulas — complexity score and levels, automation rules, hours per type and level,
automation factors — live in `dbx_premig/estimation/data/assessment_rules.yaml`; pass your
own copy with `--rules` or `DBXF_ASSESSMENT_RULES`. See [docs/ASSESSMENT.md](docs/ASSESSMENT.md).

## REST API and database

```bash
pip install -e ".[api,postgres]"
export DBXF_DATABASE_URL=postgresql+psycopg://user:pw@host:5432/db
python discovery.py db-init && python discovery.py serve --host 0.0.0.0
# or: docker compose --profile local-db up -d --build
```

`POST /v1/assessments` (multipart: discovery workbook, or credentials) and
`POST /v1/assessments/databricks` (JSON credentials) run in the background and return a run
id; download both workbooks from `/v1/runs/{id}/…`. Results are written to Postgres with the
request's `organizationId` and `jobId`. See [docs/API.md](docs/API.md).

## Build the executable

```bash
make build                                                     # Linux / macOS
powershell -ExecutionPolicy Bypass -File packaging\build.ps1   # Windows -> dist\dbx-discovery.exe
```

PyInstaller cannot cross-compile: build each OS on that OS. The GitHub Actions workflow
(`.github/workflows/build.yml`) builds and smoke-tests all three and uploads them as
artifacts. Binaries are unsigned: on Windows choose *More info → Run anyway* (SmartScreen); on
macOS right-click → Open the first time (Gatekeeper). Linux binaries need a glibc at least as
new as the build machine's.

## Documentation

* [docs/TESTING.md](docs/TESTING.md) — how to test: automated gate, offline runs, a real
  workspace, the executable, what to check in the workbook, troubleshooting
* [docs/METHODOLOGY.md](docs/METHODOLOGY.md) — every number and why
* [docs/ASSESSMENT.md](docs/ASSESSMENT.md) — rules file, assessment workbook, database tables
* [docs/API.md](docs/API.md) — REST API
* [docs/API_CURL_REQUESTS.md](docs/API_CURL_REQUESTS.md) — every API request as curl, to
  paste into Postman
* [docs/CATALOG.md](docs/CATALOG.md) — the Databricks → Fabric support catalog
* [CLAUDE.md](CLAUDE.md) — architecture, invariants, build order (read first when developing)
* [docs/PREMIGRATION_ACCELERATOR_BLUEPRINT.md](docs/PREMIGRATION_ACCELERATOR_BLUEPRINT.md) —
  the Kanerika accelerator standard this project follows

## Develop

```bash
make check          # ruff + format + mypy strict + pytest (coverage >= 80 %)
make test-all       # + LibreOffice recalculation and wheel tests
make demo           # discovery of the bundled fixture -> output/
make assets         # regenerate brand images and sheet titles
```
