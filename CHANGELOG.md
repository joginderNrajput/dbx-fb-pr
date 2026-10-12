# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [0.2.0] - 2026-10-12

### Added
- Assessment flow built on the discovery workbook: `assess`, `analyze` (= assess(discover)),
  `rules-check`. Per object: constructs (supported / unsupported), complexity score and level
  (Simple / Medium / Complex), automation level (Fully / Partially automated / Manual),
  manual and automation development / testing hours, hours saved; portfolio computation.
- Configurable rules file (`estimation/data/assessment_rules.yaml`) with a sandboxed
  expression language; `--rules` / `DBXF_ASSESSMENT_RULES`.
- Discovery-workbook reader (counts recomputed from rows; `Asset key` column added to
  Assets and Findings).
- Branded assessment workbook (Assessment, Estimation, EffortByType, Summary, Rules, About).
- Optional Postgres sink: `totals`, `inventory`, `finding`, `estimation`, `computation`
  with `organization_id` / `job_id`; replace-on-repost; `db-init`, migration SQL.
- FastAPI service: workbook upload or Databricks credentials (JSON or multipart, PAT or
  OAuth), background runs, downloads, API key, CORS; Dockerfile and docker-compose.
- `--schemas` filter for Unity Catalog collection.

### Changed
- The rules-language `round()` and all score rounding are half-up.

## [0.1.0] - 2026-10-12

### Added
- `discover` flow: live, read-only Databricks REST collection (22 collectors: workspace
  notebooks and files, repos, jobs, DLT pipelines, clusters, instance pools, cluster
  policies, SQL warehouses, Unity Catalog catalogs / schemas / tables / columns / volumes /
  external locations / storage credentials / connections / functions / grants, SQL queries,
  AI/BI and legacy dashboards, alerts, UC and workspace models, serving endpoints, MLflow
  experiments, cluster libraries, secret scopes (names only), DBFS mounts, users / groups /
  service principals).
- Offline input: exported source files, `.ipynb`, `.dbc` and `.zip` archives (hardened
  reader), and snapshots saved with `--save-snapshot`.
- Personal access token, OAuth service principal (M2M) and `~/.databrickscfg` profiles.
- Databricks → Fabric support catalog (`features.yaml`, 95 features) and per-asset readiness
  classification (Compatible / Partial / Manual / Unsupported).
- Kanerika-branded discovery workbook: 34 data sheets, Discovery dashboard with KPI tiles and
  charts, Totals as the single source of truth (live formulas), Information and Warnings.
- Root `discovery.py` entry point (interactive prompts or CLI), PyInstaller spec, build and
  smoke-test scripts, GitHub Actions build matrix.
- Test suite with a local fake Databricks workspace; docs (TESTING, METHODOLOGY, CATALOG).
