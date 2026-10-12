# CLAUDE.md — Databricks Pre-Migration Discovery (Microsoft Fabric edition)

Read this first in every session. Built from `docs/PREMIGRATION_ACCELERATOR_BLUEPRINT.md`;
where this project differs from the blueprint, the difference and its reason are stated here.

## 1. Product

Reads a Databricks workspace — **live** through the read-only REST API, or **offline** from
exported notebooks (`.py .sql .scala .r .ipynb`, `.dbc`, `.zip`) or a saved snapshot
(`.json`) — and writes a Kanerika-branded **discovery workbook** (`.xlsx`): the full estate
(notebooks, jobs, DLT, compute, Unity Catalog down to columns, governance, analytics, ML,
secrets, identities) with a first Fabric-readiness classification. No hours estimate.

| Flow | Reads | Writes | Status |
|---|---|---|---|
| `discover` | workspace (live) or export / snapshot | discovery workbook (+ optional snapshot JSON) | **done** |
| `assess` | a (reviewed) discovery workbook | assessment workbook (+ optional Postgres rows) | **done** |
| `analyze` | = `assess(discover(...))` | both workbooks (+ optional Postgres rows) | **done** |

Entry point: root **`discovery.py`** (no args → interactive prompts; args → typer CLI). It is
also the PyInstaller entry point. Ships as a single-file executable (`dist/dbx-discovery`),
`python discovery.py`, `uv run discovery.py` (PEP 723 header) or the `dbx-premig` console
script. The FastAPI service (`serve`, Docker image) accepts a discovery workbook or
Databricks credentials, runs the same service functions and can persist to Postgres.
Assessment formulas live in a configurable rules file (`estimation/data/assessment_rules.yaml`,
override with `--rules` / `DBXF_ASSESSMENT_RULES`).

Placeholders: SOURCE=Databricks, TARGET=Microsoft Fabric, pkg=`dbx_premig`,
dist=`dbx-premig`, PFX=`DBXF`, PORT=7072.

## 2. Hard constraints

- **Read-only against Databricks.** The live client sends only `GET` (plus one `POST
  /oidc/v1/token` for service-principal OAuth). *Why:* it runs inside client workspaces with
  admin tokens. *Pinned by* `test_hygiene.py::test_collector_only_reads`,
  `test_collector.py` (`ws.methods == {"GET"}`).
- **Deviation from blueprint "offline analysis":** collection is necessarily online, but it is
  isolated in `client.py` + `collector.py`, which only *capture* raw JSON into a
  `RawSnapshot`. Everything after (parser, estimation, excel) is offline and pure, so a saved
  snapshot re-runs to the same workbook. No LLM, no cloud SDKs (stdlib `urllib` only).
- **No database in the analysis.** The Postgres sink (`db/`) is write-only and optional
  (`DBXF_DATABASE_URL`); nothing is read back and no workbook number depends on it.
- **Frozen-safe resources.** All bundled files via `resources.py`; never `__file__` elsewhere
  (`test_hygiene.py::test_no_path_from_file_outside_resources`).
- **Deterministic.** Rows are sorted explicitly (`casefold` then raw); same snapshot + clock →
  equal report (`test_parser.py::test_deterministic`, `test_cli.py::test_report_deterministic`).
  One rounding helper: `estimation/rounding.round_hours` (half-up via Decimal).
- **One bad file / endpoint never ends a run.** Reader returns `ReadFailure`; collector turns
  4xx into a warning row. Only 401 / unreachable host stop a live run.
- **Never log client content or secrets.** Tokens are `SecretStr`, never in messages
  (`test_client.py::test_secret_never_in_error_messages`). Secret **values** are never
  requested; only key names. Connection options are not read.
- **No magic numbers:** thresholds, caps, retries live in `config.Settings` (`DBXF_*`).
- **Untrusted input:** `discovery.py`, `reader.py`, `client.py` responses. Archives: manifest
  validated before reading (entries, total size, ratio, symlinks, path escape), members
  streamed with a byte counter, never extracted (`test_reader.py::test_hostile_archives_refused`).
- **Frozen pydantic models**; wire schemas (future `api/schemas.py`) separate from `models.py`.
- **Secrets stay out of git:** `.env`, `*_snapshot.json`, `*.xlsx`, `*.zip`, `*.dbc` ignored.

### Service, CLI & API invariants
- `service.run_discovery` is the only orchestration; CLI and prompts call it
  (`test_cli.py::test_cli_and_service_parity`).
- stdout carries only the workbook path; progress / summary / errors go to stderr.
- `_handle()` maps `DiscoveryError` → message + fixed exit code; no traceback without `-v`.
- Precedence: CLI flags > `DBXF_*` env > `.env` > `--config` file > defaults
  (`test_config.py::test_precedence_file_env_flags`; implemented with a custom settings source).

### Assessment invariants
- The assessment reads only the discovery **workbook** (never the snapshot), joining Assets,
  Findings and detail sheets on `Asset key`. Counts are recomputed from rows; editing a total
  changes nothing (`test_assessment.py::test_editing_a_row_changes_the_assessment`).
- Every formula is in the rules file; expressions are parsed by `estimation/formula.py`
  (AST whitelist, never `eval`) and validated against the variables of their stage at load
  time (`test_formula_rejects_unsafe_or_invalid`, `test_invalid_rules_rejected`).
- Levels are exactly Simple/Medium/Complex and Fully automated/Partially automated/Manual,
  because the DB columns and workbook are fixed to them.
- Hours rounded half-up per asset; portfolio = sums of rounded figures; `saving_pct` is a
  fraction. Excel Summary recalculates to the same numbers
  (`test_assessment_summary_recalculates_to_computation`, slow).

### Database invariants
- Tables: totals (scan + item counts), inventory, finding, estimation, computation; all with
  organization_id + job_id. Defined once in `db/schema.py`; `db/migrations/0001_initial.sql`
  is generated from it (`test_db.py::test_migration_file_matches_schema`).
- One call = one transaction; re-posting the same (org, job) deletes its rows children-first
  and inserts fresh ones (`test_persist_and_replace`). VARCHAR overflow → DatabaseError naming
  table/column/limit. `describe_target` is the only URL renderer (no credentials).
- SQLAlchemy / psycopg are imported lazily inside `db/`; not in the executable.

### API invariants
- `api/` holds validation and plumbing only; runs call `service.run_discovery` /
  `run_assessment` in a thread pool. Wire models in `api/schemas.py`.
- Uploads: basename only, `.xlsx`, ZIP signature, size cap while streaming; then the reader's
  archive checks. One active run per (org, job) → 409; expired run → 410. Credentials from a
  request are used for that run only and never echoed (`test_api.py`).

### Packaging invariants
- Spec `packaging/dbx_premig.spec`: entry `discovery.py`, `datas` = `catalog/data` +
  `excel/assets` + `estimation/data`, UPX off, `db/` and `api/` excluded. Build per OS; `build.sh`/`build.ps1`
  smoke-test the built binary with `verify_workbook.py`.
- Pillow is a runtime dependency (openpyxl needs it to embed images).

### Catalog invariants
- `catalog/data/features.yaml` is data: unique ids, valid regex, verdict in
  supported/partial/manual/unsupported. Unknown ids get a synthetic `unknown` entry + warning,
  never dropped. Every id the parser emits must exist (`test_catalog.py`).

### Estimation invariants
- Readiness = `100 − Σ penalty × (1 + 0.1 × (min(n, cap) − 1))`, floored at 0; first match:
  Unsupported (any unsupported verdict) → Compatible ≥ 80 → Partial ≥ 50 → Manual. Discovery
  produces **no hours** (that is `assess`).

### Workbook / rendering invariants
- `writer.SHEET_ORDER` declared once; tests assert the file matches.
- **Totals is the single source of truth**: every value a live formula over data sheets;
  Discovery tiles, scan summary and hidden chart helpers are only `='Totals'!$B$n`
  (`test_workbook.py::test_dashboard_is_only_formulas_into_totals`).
- Rows 1–5 branding band, header row 6, data from row 7, freeze `A7`, autofilter.
- Hex colours only in `excel/theme.py` (`test_no_hex_colours_outside_theme`).
- Formula columns address fixed letters (Tables!A/B/F, JobTasks!A, Volumes/Functions!B/C):
  `test_formula_columns_stay_put`.
- Client text is written as a string even if it starts with `=` (formula injection), control
  characters removed, truncated to `max_cell_chars`.
- The banner (rows 1-4) is ONE picture per sheet, composed at run time by `excel/banner.py`
  (gradient + Kanerika logo + title + Databricks -> Fabric logo, all centred vertically),
  anchored at A1 with an absolute size. *Why:* separate pictures anchored by column offsets
  overlapped in Excel, which caps an offset at its column's width (LibreOffice does not).
  Pinned by `test_workbook.py::test_banner_is_one_picture_at_a1`. Never put title text in
  cells under the banner. Gradient and Kanerika logo are byte-identical copies from
  `Tempelate_sheet.xlsx` (`test_hygiene.py::test_brand_assets_copied_byte_identically`); the
  font is a subset of Inter SemiBold (OFL), made by `scripts/extract_assets.py`.
- Sheet modules are grouped by area (`sheets/code.py`, `orchestration.py`, `compute.py`,
  `data.py`, `analytics.py`, `platform.py`, `assessment.py`) rather than one file per sheet:
  33 data sheets share one declarative `SheetSpec` engine, so a file each would be noise.

### Parser invariants
- Walks the real API structure (`settings.tasks[]`, `columns[]`, `spec.libraries[]`); no
  generic descendant search (`test_no_descendant_search_in_parser`).
- Skips by design: job/pipeline clusters (ephemeral), `system`/`samples`/internal catalogs,
  `databricks-*` serving endpoints, `__databricks*` locations/credentials.
- Notebook paths normalised (`/Workspace` prefix removed, `./` `../` resolved, extension
  dropped) so `%run` / job / DLT dependencies resolve.

## 3. Layout

```
discovery.py                 entry point (PEP 723), no logic
dbx_premig/
  version.py config.py errors.py logging.py models.py resources.py
  discovery.py   offline input walk -> FileRef            (untrusted)
  reader.py      hardened file / archive / snapshot reader (untrusted)
  offline.py     FileRefs -> RawSnapshot
  client.py      read-only REST client, auth, retries      (untrusted responses)
  collector.py   live collectors -> RawSnapshot
  parser.py      RawSnapshot -> Estate (rows + AssetRecords)
  catalog/       loader.py + data/features.yaml
  estimation/    complexity.py (readiness) aggregate.py rounding.py
                 formula.py (safe expressions) rules.py (+ data/assessment_rules.yaml)
                 effort.py (the assessment engine) | plan.py (stub)
  excel/         theme layout types writer dashboard charts discovery_writer
                 discovery_reader assessment_writer  banner  sheets/*  assets/
  service.py cli.py prompts.py __main__.py
  api/           app.py routes.py schemas.py jobs.py uploads.py
  db/            schema.py engine.py persist.py migrations/0001_initial.sql
scripts/extract_assets.py, scripts/brand_src/   brand assets (build time)
packaging/       spec, build.sh, build.ps1, verify_workbook.py, icons, version info
tests/           fake_workspace.py (local HTTP fake of the REST API), archives.py, fixtures/mini
docs/            TESTING.md METHODOLOGY.md CATALOG.md ASSESSMENT.md API.md + the blueprint
Dockerfile docker-compose.yml   API image (+ opt-in local Postgres)
```

Data flow: `collector|offline -> RawSnapshot -> parser -> estimation -> excel`;
`service.py` orchestrates; `cli.py` / `prompts.py` are skins.

## 4. Build order

| # | Prompt | Status |
|---|---|---|
| 01 | Scaffold, configuration and domain model | done |
| 02 | Discovery and hardened reader (+ live client / collector) | done |
| 03 | Parser → inventory and feature counts | done |
| 04 | Target-support catalog | done (hand-written YAML; no generator yet) |
| 05 | Complexity, automation and effort | done (rules file + engine) |
| 06 | Plan, lanes and schedule | stub |
| 07 | Theme, assets and data sheets | done |
| 08 | Dashboard and charts | done |
| 09 | Service, CLI and FastAPI | done (assess / analyze / serve / db-init, discovery_reader) |
| 10 | Packaging, CI, end-to-end tests and docs | done (spec, build scripts, GitHub Actions, Docker, docs) |
| — | Postgres sink | done (5 tables, replace-on-repost) |

## 5. The numbers

See `docs/METHODOLOGY.md` (discovery) and `docs/ASSESSMENT.md` (rules file, tables). Thresholds: Compatible ≥ 80, Partial ≥ 50 (settings
`readiness_compatible_min`, `readiness_partial_min`); occurrence cap 10. Effort-point weights
on Totals are editable in the workbook (heuristic, not hours).

## 6. Workbook

| Sheet | Visible | Holds | Values from |
|---|---|---|---|
| Discovery | yes | nav, 16 KPI tiles, scan summary, 3 charts | `='Totals'!…` only |
| Assets | yes | one row per assessable object + readiness | assessment |
| Findings | yes | one row per (asset, feature) + guidance | assessment + catalog |
| Notebooks … Identities (31 sheets) | yes | one row per Databricks object | parser |
| Warnings | yes | unreadable endpoints / files, catalog misses | collector, reader, estimation |
| Information | yes | how to read, what was scanned, limits | static + ScanInfo |
| Totals | yes | all totals, readiness by type, findings by rule, effort weights | live formulas |
| ChartReadiness / ChartAssetTypes / ChartTopFindings | hidden | chart series | `='Totals'!…` only |

## 7. Exit codes

| Code | Meaning |
|---|---|
| 0 | success |
| 1 | internal error (bug) |
| 2 | unsupported file type |
| 3 | malformed artifact |
| 4 | unsafe archive |
| 5 | catalog or assessment-rules error |
| 6 | report write error |
| 7 | nothing found |
| 8 | invalid discovery workbook / snapshot |
| 9 | database error |
| 10 | Databricks connection / authentication error |
| 11 | invalid configuration (missing host / token, bad setting) |

## 8. Working agreements

```
pip install -e ".[dev]"
ruff check . && ruff format --check . && mypy dbx_premig tests scripts && pytest
pytest --run-slow          # LibreOffice recalculation + wheel contents
DBXF_TEST_DATABASE_URL=postgresql://… pytest   # + Postgres tests (own throwaway schema each)
```
- Every change leaves ruff, mypy (strict) and pytest (coverage ≥ 80 %) green.
- Python >=3.11,<3.14; line length 100; `from __future__ import annotations`; `__all__`.
- Domain models are frozen. Wire schemas stay separate from domain models.
- `dbx2fabric_assess (3) 2.py` is the original prototype this tool replaces; its rules now
  live in `features.yaml`. Keep it only as a reference.
