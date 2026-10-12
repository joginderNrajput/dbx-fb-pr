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
  --skip-repos --no-columns --no-view-sql --max-notebooks N --insecure
  -c, --config FILE       settings file (.yaml / .toml); every setting also as DBXF_<NAME>
  -v, --verbose
python discovery.py version | catalog-info | collectors
```

Exit codes: 0 ok · 1 internal error · 2 unsupported file · 4 unsafe archive · 5 catalog ·
6 cannot write · 7 nothing found · 8 invalid snapshot · 10 connection/auth · 11 configuration.

## The workbook

**Discovery** (dashboard: navigation, 16 KPI tiles, scan summary, charts) → **Assets**
(readiness of every object) → **Findings** (Databricks features that need work, with Fabric
guidance) → one sheet per object type (Notebooks, Dependencies, Repos, Jobs, JobTasks,
DLTPipelines, Clusters, InstancePools, ClusterPolicies, SQLWarehouses, Libraries, Catalogs,
Schemas, Tables, Columns, Views, Volumes, ExternalLocations, StorageCredentials, Connections,
Functions, Grants, SQLQueries, Dashboards, Alerts, Models, ServingEndpoints, Experiments,
SecretScopes, Mounts, Identities) → **Warnings** → **Information** → **Totals** (the single
source of truth: every number is a live formula).

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
