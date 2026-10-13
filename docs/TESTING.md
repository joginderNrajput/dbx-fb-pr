# Testing guide — Databricks → Fabric discovery

How to check that the discovery tool works: the automated suite, hands-on runs without a
workspace, a run against a real Databricks workspace, the built executable, and what to look
for in the Excel workbook.

---

## 1. Set up once

Python 3.11–3.13. From the repository root:

```bash
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -e ".[dev]"            # includes the api and postgres extras
```

With [uv](https://docs.astral.sh/uv/) instead: `uv venv && uv pip install -e ".[dev]"`.

Check the install:

```bash
python discovery.py version          # dbx-premig 0.1.0
python discovery.py catalog-info     # catalog v1: 95 features (37 code patterns, ...)
```

---

## 2. The automated gate (run before every commit)

```bash
ruff check . && ruff format --check .
mypy dbx_premig tests scripts
pytest                                # unit + end-to-end, coverage gate 80 %
pytest --run-slow                     # adds the LibreOffice recalculation and wheel tests
DBXF_TEST_DATABASE_URL=postgresql://user:pw@localhost:5432/test pytest   # + Postgres tests
```

The Postgres tests (`database` marker) are skipped unless `DBXF_TEST_DATABASE_URL` points at
a database the tests may create and drop schemas in; each test uses its own throwaway
schema. A local one: `docker run -d -p 5432:5432 -e POSTGRES_PASSWORD=pw postgres:16-alpine`.

or simply `make check` (and `make test-all` for the slow tests).

| Test file | What it proves |
|---|---|
| `test_config.py` | defaults, `DBXF_*` variables, `--config` YAML/TOML, precedence **flags > env > file > defaults**, bad settings rejected |
| `test_catalog.py` | `features.yaml` is valid, ids are unique, every feature id the parser can emit exists in the catalog, unknown ids are kept (not dropped) |
| `test_reader.py` | offline inputs: folders, `.ipynb`, `.zip` source exports, `.dbc` archives, snapshots; **hostile archives** (zip-slip, absolute paths, symlinks, zip bomb, too many entries, fake archive) are refused and never stop the run |
| `test_parser.py` | the fixture parses to the expected counts; dependencies resolve; malformed API objects never crash; output is deterministic |
| `test_estimation.py` | readiness rules (thresholds, first match wins, Unsupported), penalty weighting cap, half-up rounding |
| `test_client.py` | REST client against a local **fake Databricks workspace**: paging, 401 is fatal, 403 becomes a warning, 5xx retry, OAuth service-principal flow, credential sources (`--host/--token`, `DATABRICKS_*`, `~/.databrickscfg` profiles), secrets never appear in messages |
| `test_collector.py` | the full live collection over HTTP gives the same estate as the saved snapshot; forbidden endpoints become warnings; `--only` / `--catalogs` / notebook cap; only GET requests are sent |
| `test_workbook.py` | sheet order, headers, frozen panes, branding on every sheet, dashboard and chart cells are **only formulas into Totals**, formula columns stay in place, client text is never turned into a formula, charts do not overlap, no hex colours outside `theme.py`; slow: LibreOffice recalculates the workbook and the totals equal the Python roll-up with no `#REF!`/`#VALUE!` |
| `test_cli.py` | CLI exit codes, stdout carries only the workbook path, CLI ≡ service parity, live run against the fake workspace with `--save-snapshot`, interactive mode without a terminal |
| `test_hygiene.py` | repository rules: `from __future__` + `__all__` everywhere, no `__file__` paths outside `resources.py`, no `extractall`, only GET/OAuth in the client, Kanerika logo and banner byte-identical to `Tempelate_sheet.xlsx`, versions consistent |
| `test_packaging.py` (slow) | the wheel carries every bundled resource exactly once |
| `test_assessment.py` | the rules language (and that it refuses imports, attributes, lambdas …), rules-file validation, hand-checked estimates, the discovery-workbook reader round trip (editing a row changes the assessment, editing a total does not), the assessment workbook; slow: LibreOffice recalculates Summary and it equals the Python computation |
| `test_db.py` | migration file in step with the schema, URL never shows credentials; with Postgres: all five tables written, re-posting the same org/job replaces, foreign keys line up, too-long values rejected |
| `test_api.py` | upload path, Databricks-credentials path (JSON and multipart, PAT and OAuth) against the fake workspace, 401/409/410/413/415/422/503, API key, persistence through the API |

The fake workspace (`tests/fake_workspace.py`) is a small HTTP server that answers the real
Databricks REST paths from `tests/fixtures/mini/snapshot.json`, one item per page, so the
live code path is exercised end to end without a real workspace.

---

## 3. Hands-on, no workspace needed

### 3.1 The bundled fixture (looks like a live scan)

```bash
python discovery.py discover --input tests/fixtures/mini/snapshot.json --out output
```

Expected on stderr: `41 assessable objects · 25 compatible · 12 partial · 2 manual ·
2 unsupported · average readiness 78.6 · 3 warning(s)`. stdout is the workbook path.

### 3.2 Offline notebook export

```bash
python discovery.py discover --input tests/fixtures/mini/notebooks --out output
```

Expected: `5 assessable objects`. Only the notebook-related sheets have rows; the others are
present but empty (that is correct for an offline run).

Try your own exports too — all of these work with `--input`:

| Export | How to get it from Databricks |
|---|---|
| Folder of source files | Workspace → folder → ⋮ → **Export → Source file**, or `databricks workspace export-dir /Shared ./exports` |
| `.dbc` archive | Workspace → folder → ⋮ → **Export → DBC archive** |
| `.zip` of source files | Workspace → folder → ⋮ → **Export → Source file** (a folder downloads as zip) |
| `.ipynb` | Notebook → File → Export → IPython Notebook |
| Snapshot `.json` | an earlier live run with `--save-snapshot` |

### 3.3 Interactive mode (what a double-clicked exe does)

```bash
python discovery.py
```

Answer `offline`, then `tests/fixtures/mini/snapshot.json`, then accept the defaults.

### 3.4 Error handling (exit codes)

```bash
python discovery.py discover --input does-not-exist        ; echo $?   # 7  nothing found
python discovery.py discover --input README.md             ; echo $?   # 2  unsupported file
python discovery.py discover                               ; echo $?   # 11 no host / token
python discovery.py discover --host https://adb-1.azuredatabricks.net --token wrong ; echo $?
                                                                       # 10 connection / auth error
```

No command may print a Python traceback unless `--verbose` is given.

---

## 3b. Assessment, database and API (no workspace needed)

```bash
# discovery + assessment in one go (both workbooks in output/)
python discovery.py analyze --input tests/fixtures/mini/snapshot.json --out output
# or assess an existing discovery workbook
python discovery.py assess --input output/databricks_discovery_*.xlsx --out output
```

Expected: `41 assets · 22 simple / 14 medium / 5 complex · 24 fully / 13 partially automated /
4 manual · 218.9 h manual -> 151.2 h with automation (31% saved)`.

**Try a different formula**: copy `dbx_premig/estimation/data/assessment_rules.yaml`, change
e.g. `manual_test_hours: "manual_dev_hours * 0.5"`, run `python discovery.py rules-check
--rules my.yaml`, then `assess --rules my.yaml`: the hours change, the Rules sheet shows your
file. Break a formula on purpose (`lnes / 10`): `rules-check` exits 5 naming the key.

**Database**:

The database settings come from `.env` (Azure Database for PostgreSQL; see `.env.example`).

```bash
python discovery.py db-init                       # Alembic: creates / upgrades the 5 tables
python discovery.py analyze --input tests/fixtures/mini/snapshot.json --out output \
    --persist --org org-1 --job job-1             # "Saved to … as scan N (totals 1, inventory 41, …)"
# then, in any SQL client on the same database (with DBXF_DB_TABLE_PREFIX=dbx_):
#   select * from <DBXF_DB_SCHEMA>.dbx_computation;
```

Run the same command again: the summary says *replaced the previous run* and the tables
still hold one scan for `org-1 / job-1`.

**API** (see [API.md](API.md)):

```bash
python discovery.py serve                          # http://127.0.0.1:7073/docs
curl -X POST localhost:7073/v1/assessments -F organizationId=o -F jobId=j -F wait=true \
     -F file=@output/databricks_discovery_<…>.xlsx
curl -o a.xlsx localhost:7073/v1/runs/<runId>/assessment
```

---

## 4. Against a real Databricks workspace

Discovery is **read-only**: it sends only `GET` requests (plus one OAuth token request when a
service principal is used). Nothing is created, changed or run.

### 4.1 Credentials

Use a **workspace admin** identity for full coverage; a normal user only sees what they have
access to (missing objects show up as warnings, not errors).

* **Personal access token**: User settings → Developer → Access tokens → Generate.
* **Service principal (OAuth M2M)**: workspace admin settings → Identity and access → Service
  principals → Secrets → Generate secret. Use its *client id* and *secret*.

Prefer environment variables over command-line flags (flags can show up in shell history and
process lists):

```bash
export DATABRICKS_HOST=https://adb-1234567890123456.7.azuredatabricks.net
export DATABRICKS_TOKEN=dapi...            # or DATABRICKS_CLIENT_ID + DATABRICKS_CLIENT_SECRET
```

A profile in `~/.databrickscfg` works too: `--profile prod`.

### 4.2 Smoke run first (fast, small)

```bash
python discovery.py discover --only workspace,jobs,clusters,warehouses -v --out output
```

`-v` lists every collector with the number of objects found. Then the full run:

```bash
python discovery.py discover --out output --save-snapshot -v
```

Useful knobs for large workspaces:

| Flag | Effect |
|---|---|
| `--catalogs main,sales` | only these Unity Catalog catalogs |
| `--schemas main.default` | only these schemas (`catalog.schema` or a bare name) |
| `--max-notebooks 500` | stop exporting notebook source after 500 |
| `--skip-repos` | leave out `/Repos` |
| `--no-columns` | no Columns sheet (very large metastores) |
| `--no-view-sql` | do not copy view SQL into the workbook |
| `--only notebooks,jobs` | run selected collectors (`python discovery.py collectors` lists them) |

`--save-snapshot` writes `<workbook>_snapshot.json`. It contains notebook source: treat it as
client data. Re-run the analysis offline any time with
`python discovery.py discover --input <snapshot>.json`; the workbook is identical apart from
the "generated" time.

### 4.3 Cross-check the numbers with Databricks

Pick a few totals from the **Totals** sheet and compare them with the workspace UI or SQL:

| Workbook | Check in Databricks |
|---|---|
| Jobs | Workflows → Jobs list count |
| All-purpose clusters | Compute → All-purpose compute |
| SQL warehouses | SQL Warehouses page |
| Tables and views | `SELECT count(*) FROM system.information_schema.tables WHERE table_catalog NOT IN ('system','samples')` (Unity Catalog) |
| Columns | `SELECT count(*) FROM system.information_schema.columns WHERE ...` (same filter) |
| Notebooks | Workspace browser (or `databricks workspace list -r /`) |

Differences are expected only for what the Warnings sheet says could not be read, and for the
documented skips (job/pipeline clusters, `system`/`samples` catalogs, `databricks-*`
foundation-model endpoints, managed `__databricks*` locations).

---

## 5. What to check in the workbook

Open the `.xlsx` in Excel (formulas recalculate on open; LibreOffice works too).

1. **Discovery** — Kanerika logo left, *Databricks → Fabric* logo right, title in the banner;
   16 KPI tiles (the red row is the risk row); scan summary; three charts. Click a few
   navigation links: each opens its sheet, and *« Back to Discovery* returns.
2. **Totals** — every value is a live formula (click a cell: `=COUNTA(...)` / `=COUNTIF(...)`).
   Change a readiness value on **Assets** from `Compatible` to `Manual`: the Totals row,
   the dashboard tile and the doughnut chart all change. That proves the single source of truth.
3. **Assets** — one row per object; readiness colour-coded; filters on every header.
4. **Findings** — filter `Rule` to e.g. `AUTOLOADER` to see every affected notebook with the
   Fabric guidance.
5. **Warnings** — must list every endpoint that was not readable. An empty sheet after a live
   run means full coverage.
6. **Information** — what was scanned (mode, workspace, metastore, collectors) and the limits.
7. **Effort weights** (bottom of Totals) — change a yellow weight: *Portfolio points* and the
   dashboard's *Effort points* follow.

Automated version of the structural checks: `python packaging/verify_workbook.py <file>.xlsx`.

---

## 6. The executable (PyInstaller)

PyInstaller builds for the OS it runs on, so build the Windows `.exe` on Windows, the macOS
binary on a Mac, and so on. The GitHub Actions workflow `.github/workflows/build.yml` builds
all three on every push and attaches them as run artifacts.

```bash
make build                                         # Linux / macOS: packaging/build.sh
powershell -ExecutionPolicy Bypass -File packaging\build.ps1   # Windows
```

The build script then **smoke-tests the built binary**: `version`, `catalog-info`, a discovery
of the fixture snapshot and of the offline notebooks, an assessment of the first, and
`verify_workbook.py` on all three workbooks. The executable discovers and assesses; the REST
API and the database sink are not bundled (use the Docker image or a pip install for those). A missing bundled data file shows up here (the binary starts, then fails on its
first discovery), not at the client.

Manual checks of the binary (`dist/dbx-discovery` or `dist\dbx-discovery.exe`):

```bash
dist/dbx-discovery version
dist/dbx-discovery discover --input tests/fixtures/mini/snapshot.json --out output
dist/dbx-discovery                    # double-click equivalent: interactive prompts
```

On Windows, double-clicking the `.exe` opens the prompts and keeps the window open at the
end. The binary is unsigned: SmartScreen shows *More info → Run anyway*; on macOS use
right-click → Open the first time (Gatekeeper).

Sending it to a client: give them the binary and section 4.1 above. They run it on any
machine that can reach their workspace URL, and send back only the `.xlsx` (and, if you
asked for it, the snapshot JSON).

---

## 7. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| exit 10, *rejected the credentials (HTTP 401)* | token expired or for another workspace |
| exit 10, *Cannot connect* | wrong URL, VPN / private link, or a proxy: set `HTTPS_PROXY`; for an inspecting proxy in a lab only, `--insecure` |
| Many *HTTP 403* rows on Warnings | the identity is not a workspace admin, or Unity Catalog privileges are missing |
| *HTTP 404* for a collector | feature not enabled in that workspace (e.g. no Unity Catalog, no Lakeview); expected |
| Notebook rows with *Scanned = No* | larger than `max_notebook_bytes` (5 MB) or not exportable |
| Excel shows 0 everywhere | the file was opened in a viewer that does not recalculate; open in Excel or LibreOffice |
| exit 5 on `assess` | the rules file is invalid: `rules-check --rules <file>` names the key |
| exit 8 on `assess` | the input is not a discovery workbook written by this tool |
| exit 9 | database unreachable (URL, Azure firewall rule for your IP, TLS) or tables missing: check `.env`, run `db-init`; *did not create* = shared schema, set `DBXF_DB_TABLE_PREFIX` |
| exit 1, *Internal error* | a bug: re-run with `-v` and report the class name and traceback (no client data is printed) |
