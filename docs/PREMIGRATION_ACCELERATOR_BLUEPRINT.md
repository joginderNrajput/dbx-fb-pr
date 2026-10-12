# Pre-Migration Accelerator Blueprint

The standard project structure, architecture and tooling for every Kanerika **pre-migration
accelerator**: a tool that reads a client's source-platform artifacts offline, takes stock of
what is there, estimates the effort to migrate it to a target platform, and produces a
client-ready report.

It is taken from the reference implementation, `alteryx_to_databricks_premigration`
(Alteryx → Databricks). Every rule here is generic. Where a concrete example helps, it comes
from that project and is labelled *Reference*.

---

## 0. How to use this file (for Claude Code)

When this file is given to you for a new or existing accelerator:

1. **Fill in the placeholders first** (§1) and confirm them with the user if they cannot be
   inferred from the repository or the request.
2. **Create or restructure the repository to match §3 exactly**: directory names, file
   names and responsibilities. Do not invent a parallel layout. If the source platform needs
   a module this blueprint does not name, add it inside the package under the stage it
   belongs to (§4) and record it in the project's `CLAUDE.md`.
3. **Apply every rule in §2.** They are constraints, not suggestions. Later work inherits
   them.
4. **Write the project's own `CLAUDE.md`** from the template in §17. That file, not this one,
   is what future sessions read first.
5. **Work in numbered prompts** (§16). Each one must leave `ruff`, `mypy` and `pytest` green
   before the next starts.

### Placeholders

| Placeholder | Meaning | Reference value |
|---|---|---|
| `<SOURCE>` | Platform being migrated from | `Alteryx` |
| `<TARGET>` | Platform being migrated to | `Databricks` |
| `<pkg>` | Python import package (snake_case) | `alteryx_premig` |
| `<dist>` | Distribution / CLI / binary name (kebab-case) | `alteryx-premig` |
| `<PFX>` | Environment-variable prefix, no trailing underscore | `APX` |
| `<EXT>` | Source artifact extensions | `.yxmd .yxmc .yxzp .yxwz` |
| `<PORT>` | Default API port | `7070` |
| `<schema>` | Postgres schema for the optional sink | `alteryx_to_databricks_premigration` |

Use a different `<PORT>` and `<PFX>` for each accelerator, so that several of them can run on
the same VM.

---

## 1. Product shape

**One pipeline, three flows.** The pipeline splits at the inventory, and both halves can be
called on their own:

| Flow | Reads | Writes |
|---|---|---|
| `analyze` | the `<SOURCE>` artifact tree | the effort-analysis workbook |
| `discover` | the `<SOURCE>` artifact tree | the **discovery** workbook: the estate, no estimate |
| `assess` | a discovery workbook | the effort-analysis workbook |

`analyze` **is** `assess(discover(...))`, built from the same two functions the split flow
calls. The one-shot route and the two-step route therefore cannot produce different numbers.
The gap between the two steps is a product feature: the artifact owner reviews the discovery
workbook and fills in what its Warnings sheet says is missing *before* anyone argues about
hours.

**It ships three ways, all calling one service layer:**

1. A **PyInstaller single-file executable** (Windows / Linux / macOS): the CLI and the API
   server in one binary.
2. A **FastAPI REST service** in a Docker image.
3. **Root-level `uv run` scripts** for people who will not install anything.

---

## 2. Hard constraints (apply to every accelerator, every prompt)

- **Offline analysis.** No network calls, no LLM, no source-platform installation and no
  cloud SDKs in the analysis path. The only outbound calls allowed are explicitly optional
  integrations behind the API (the persistence sink, the completion callback, Logstash).
- **No database in the analysis.** Postgres is an **optional sink** behind one API route. It
  is off unless `<PFX>_DATABASE_URL` is set, it lives in an optional extra, and no number
  depends on it. Nothing reads rows back.
- **Frozen-safe resources.** Every bundled data file is loaded through `<pkg>/resources.py`.
  Never compute a path from `__file__`, which breaks inside a PyInstaller one-file binary.
- **Deterministic.** The same input tree always produces the same output. Sort everything
  explicitly (for example `name.casefold()`, then relative path). Round only at the
  presentation boundary, through **one** shared `round_hours()` helper (half-up via
  `Decimal`, never banker's rounding).
- **One bad file never ends a run.** A malformed or unreadable artifact becomes a warning and
  still appears in the report with zeroed counts.
- **Never log client content.** No artifact XML/JSON, expressions, SQL or connection
  strings. Log only file names, counts, durations and exception class names.
- **No magic numbers.** Every threshold, rate, cap and calendar assumption lives in
  `<pkg>/config.Settings` and can be overridden from a YAML/TOML file or a `<PFX>_`
  environment variable.
- **Untrusted-input boundary.** Only the discovery and reader modules (and the discovery
  workbook reader) touch untrusted input. They must:
  - configure XML parsers with entity resolution off, network off and huge trees off, and
    refuse documents that declare entities;
  - validate an archive's whole manifest **before writing a byte** (no symlinks, no path
    escape, entry-count and uncompressed-size caps), then stream each member with a live byte
    counter. Never call `zipfile.extractall`;
  - return a failure value rather than raise, so the caller can record a warning and move on.
- **Frozen domain models.** Pydantic v2 `frozen=True`. To change one, add a field; never
  mutate.
- **Wire schemas ≠ domain models.** `api/schemas.py` is separate from `models.py`, so an
  internal refactor cannot silently change the API contract.
- **Secrets stay out of git.** `.env` is git-ignored. `.env.example` is committed and never
  holds a real credential. A connection string is never logged, returned or put in an error
  message.

---

## 3. Repository layout

```
<repo>/
├── <pkg>/                          # the one importable package (see §4)
│   ├── __init__.py
│   ├── __main__.py                 # `python -m <pkg>` and the PyInstaller entry point
│   ├── version.py                  # APP_NAME, APP_VERSION, TARGET_PLATFORM; imports nothing
│   ├── config.py                   # Settings (pydantic-settings), load_settings(), get_settings()
│   ├── errors.py                   # <Base>Error hierarchy + fixed exit codes
│   ├── logging.py                  # rich console logger, quiet by default; payload logger
│   ├── models.py                   # frozen pydantic v2 domain model
│   ├── resources.py                # bundled-data resolver, frozen-safe
│   ├── discovery.py                # walk the input tree -> FileRef list       (untrusted)
│   ├── reader.py                   # hardened file / archive reader            (untrusted)
│   ├── parser.py                   # bundle -> per-artifact inventory row
│   ├── service.py                  # THE orchestration layer: discover / assess / analyze
│   ├── cli.py                      # typer CLI: analyze, discover, assess, serve, version, ...
│   ├── prompts.py                  # interactive front end shared by the root scripts
│   ├── catalog/                    # source-feature -> target-support knowledge base
│   │   ├── loader.py
│   │   └── data/                   # *.yaml (+ generated *.json sidecar), shipped in wheel+exe
│   ├── estimation/                 # complexity.py effort.py aggregate.py plan.py rounding.py
│   ├── excel/                      # the report
│   │   ├── theme.py                # the ONLY place raw hex colours may appear
│   │   ├── layout.py types.py writer.py
│   │   ├── sheets/                 # one module per worksheet
│   │   ├── discovery_writer.py     # the discovery workbook ...
│   │   ├── discovery_reader.py     # ... and reading it back (untrusted input)
│   │   └── assets/                 # banner, logos (committed, regenerated by scripts/)
│   ├── api/                        # FastAPI skin over service.py
│   │   ├── app.py                  # create_app(settings), middleware, error handlers
│   │   ├── routes.py               # validation + plumbing only
│   │   ├── schemas.py              # wire models, separate from models.py
│   │   ├── jobs.py                 # in-memory job store (single instance, TTL, 410 on expiry)
│   │   ├── uploads.py              # basename, extension, magic-byte and streaming size checks
│   │   ├── callback.py             # optional: completion callback with SSRF guard
│   │   └── logstash.py             # optional: milestone events to the caller's ELK
│   └── db/                         # OPTIONAL Postgres sink, lazily imported
│       ├── schema.py rows.py engine.py persist.py
│       └── migrations/             # Alembic env.py + versions/NNNN_description.py
├── generate_report.py              # root scripts: PEP 723 header, argument parsing + one
├── generate_discovery.py           #   call into service/prompts. No logic of their own.
├── generate_assessment.py
├── tests/
│   ├── conftest.py                 # neutralises <PFX>_ env vars AND env_file
│   ├── archives.py                 # generates hostile archive fixtures at test time
│   ├── fixtures/
│   │   ├── mini/                   # tiny, valid, readable-by-eye end-to-end tree
│   │   └── adversarial/            # inputs the reader must refuse cleanly (+ README.md)
│   └── test_<module>.py            # one file per module, plus test_e2e / test_packaging
├── scripts/                        # build-time generators (catalog, assets); never imported
├── packaging/
│   ├── <pkg>.spec                  # PyInstaller spec: datas, hiddenimports, excludes
│   ├── build.sh  build.ps1         # local build + smoke test on THIS OS
│   ├── verify_*.py                 # checks the BUILT binary's output in CI
│   ├── make_icons.py  *.ico *.icns  file_version_info.txt
├── docs/
│   ├── METHODOLOGY.md              # every number and why
│   ├── TESTING.md                  # hands-on test guide and scenario walkthroughs
│   ├── CATALOG.md                  # how the support catalog is built and extended
│   ├── prompt-playbook.html        # the numbered build prompts, verbatim
│   └── postman/                    # API collection (a deliverable, committed)
├── sample_output/                  # reference workbook(s) the report mirrors (git-ignored)
├── CLAUDE.md                       # read first every session (template in §17)
├── README.md                       # quick start, CLI, API, Docker, troubleshooting
├── CHANGELOG.md                    # Keep a Changelog + SemVer
├── pyproject.toml                  # the single dependency + tool configuration file
├── uv.lock                         # committed lock file
├── Makefile                        # the developer front door (§11)
├── Dockerfile                      # multi-stage, non-root, health-checked (§12)
├── docker-compose.yml              # api + opt-in local db profile
├── alembic.ini                     # NO URL in it
├── .env.example                    # committed template; .env is git-ignored
├── .gitignore                      # §14
└── azure-pipelines.yml             # deploy pipeline (and/or .github/workflows/)
```

---

## 4. Architecture

### Data flow: one direction, no cycles

```
discovery -> reader -> parser -> catalog -> estimation -> excel
                          |                      ^
                          |  DiscoveryReport     |
                          +--> discovery_writer -> [.xlsx] -> discovery_reader --+
                          |
                          +--> db/rows -> db/persist -> [Postgres]   OPTIONAL, write-only

           service.py orchestrates; cli.py, api/ and the root scripts are skins
```

### Module responsibilities

| Module | Owns | Must not |
|---|---|---|
| `discovery.py` | Walking the tree, matching `<EXT>`, building `FileRef`s in sorted order | Parse content |
| `reader.py` | The one safe parser configuration; archive validation; `read_x()` returns a failure value; the one sanctioned text accessor | Unescape twice; extract archives wholesale |
| `parser.py` | Turning a read artifact into an inventory row and per-feature usage rows | Consult the catalog; search the document with descendant XPath (walk the real structure) |
| `catalog/` | Mapping each source feature to a target support verdict, category, weight and target construct | Drop an unknown feature (return a synthetic `unknown` entry and record the miss) |
| `estimation/` | Complexity level, automation level, hours, engine recommendation, plan/schedule | Branch on informational scores; round before the presentation boundary |
| `excel/` | Rendering. A `Summary` sheet is the single source of truth; every other figure is a live formula into it | Hold literal copies of derived values; use hex outside `theme.py` |
| `service.py` | `discover_portfolio()`, `assess()`, `analyze() = assess(discover_portfolio())` | Be bypassed: no surface may sequence the pipeline itself |
| `cli.py` | Typer commands; `_handle()` turns a domain error into message-on-stderr + exit code | Print a traceback (except with `--verbose`); write anything but the report to stdout |
| `api/` | HTTP validation, upload safety, jobs, optional sink/callback | Contain analysis logic |
| `db/` | Mirroring the target tables, building rows from the sheet modules, one transaction | Be imported at module scope anywhere outside `db/` |

### The parity rule

A test runs the same fixture through the CLI path and the API path and asserts that the two
summary objects are **equal field by field**. If it fails, a surface has grown logic of its
own. A second test asserts that `analyze()` equals `assess(discover())` on the same tree.

---

## 5. Configuration (`config.py`)

- One `Settings(BaseSettings)` class with `env_prefix="<PFX>_"`, `env_nested_delimiter="__"`
  and `env_file=".env"`.
- Precedence, lowest first: code defaults → `--config file.yaml|toml` → environment variables
  → CLI flags (applied with `model_copy`).
- Each field gets an `Annotated[..., Field(ge=...)]` bound and a docstring stating what it
  controls. Group fields with comment banners: thresholds, rate card, calendar, safety caps,
  API, database, callback, logging.
- Composite settings (such as a rate card) must be given in full or not at all. A partial
  override is rejected, never silently merged.
- **The listening address is defined once:** `api_host` (`127.0.0.1`) and `api_port`
  (`<PORT>`). The CLI's `--host`/`--port` default to `None` and fall back to them. The
  Dockerfile passes only `--host 0.0.0.0`. Compose takes its port mapping and health check
  from `<PFX>_API_PORT`.

## 6. Errors and exit codes (`errors.py`)

A single base class `<Base>Error(Exception)` with `.message` (a full sentence that names the
file or setting at fault and never quotes content), `.detail` (shown only with `--verbose`)
and `.exit_code`. The codes are a **contract** that CI pipelines branch on: fix them, document
them in the module docstring and in `CLAUDE.md`, and never renumber.

| Code | Meaning |
|---|---|
| 0 | success |
| 1 | uncaught internal error (a bug) |
| 2 | unsupported file type |
| 3 | malformed artifact |
| 4 | unsafe archive |
| 5 | catalog error |
| 6 | report write error |
| 7 | nothing found to analyse |
| 8 | invalid discovery workbook |
| 9 | database error |

The API maps the same classes to HTTP statuses in one exception handler.

## 7. Logging (`logging.py`)

- A `rich` console handler, quiet by default (`WARNING`), raised to `INFO` by `-v` or
  `<PFX>_LOG_LEVEL`.
- A separate **payload logger** with a plain handler and no propagation, for pretty-printed
  JSON. Rich re-wraps lines at 80 columns when no terminal is attached, which breaks JSON. Use
  it to log outbound callback bodies and inbound request metadata (field values, file names,
  sizes, content types and first bytes, never file content). Strip query strings from logged
  URLs.
- Switch payload logging off with a setting (`<PFX>_CALLBACK_LOG_PAYLOAD=false`).

## 8. Domain model, catalog and estimation

- `models.py` holds frozen models: `FileRef`, the inventory row, feature usage, warnings,
  `DiscoveryReport`, per-artifact estimate, plan row, portfolio summary and `AnalysisResult`
  (stamped with `APP_VERSION`).
- **The catalog is data, not code.** YAML under `catalog/data/`, generated by
  `scripts/build_catalog.py` from an authoritative source and then extended by hand. A
  `--check` mode fails when the committed file has drifted, and a test runs it. If loading
  the YAML is too slow for the start-up budget, generate a JSON sidecar keyed by the YAML's
  SHA-256 and fall back to the YAML when the hash does not match.
- Aliases are globally unique and never shadow another entry's id.
- Complexity level comes from a documented, size-based rule. Any richer score is
  **informational** only.
- `supported + unsupported == total`. Partial and unknown support count as fractions
  (settings), so automation degrades gradually.
- Percentages are stored as **fractions** and formatted by the workbook.
- Summary totals are summed from the **rounded** per-artifact figures, so a reviewer with a
  calculator gets the same answer.
- Decision tables (such as recommended engine) are ordered first-match-wins, and a test
  asserts that no rule is shadowed by an earlier one.

## 9. The report (`excel/`)

- Sheet order is declared once (`writer.SHEET_ORDER`) and tests assert the file matches it.
- **`Summary` is the single source of truth.** The dashboard, computation and hidden chart
  helper sheets hold only `=Summary!Bn` formulas, and a test asserts it.
- Rows 1–5 are the branding band, the header is row 6 and data starts in row 7, unless a
  sheet documents a different layout.
- Every sheet declares `NUMERIC_COLUMNS`, which are right-aligned. Numbers must fit their
  cells, tested against a worst-case seven-figure value. Charts must not overlap (measure
  from the drawing XML). Merged ranges must never collide.
- Brand assets are committed, regenerated reproducibly by `scripts/extract_assets.py`, and
  client logos are copied byte-identically with a SHA-256 test.
- **The discovery workbook is a file format.** Its data sheets' headers and row order are a
  contract. `discovery_reader` reads them back into identical objects and recomputes every
  total from the rows, so editing a row changes the estimate but editing a total does not. A
  round-trip test and a "two-step equals one-shot" test guard it.

## 10. Service, CLI, API, database

**CLI (`cli.py`, typer).** `analyze`, `discover`, `assess`, `serve`, `version`, plus
diagnostics such as `catalog-info`. `main()` is the console-script and frozen entry point.
stdout carries only the report, so it can be piped.

**Root scripts.** Each carries a PEP 723 `# /// script` block listing **only** the runtime
dependencies the analysis needs (no typer, FastAPI or uvicorn), so `uv run generate_x.py`
works with nothing installed. All interaction lives in `prompts.py`. Only the input question
may be asked without a TTY; every other question falls back to its default.

**API (`api/`).**
- `create_app(settings)` factory. `/healthz` never needs a key. `X-API-Key`
  (`secrets.compare_digest`) and CORS are off by default and enabled by settings.
- Long work runs as a background job in a thread executor (it is CPU-bound). Jobs are
  in-memory, single-instance, with a TTL. An expired job returns **410**, not 404.
- Uploads: basename only, extension allow-list, **magic-byte sniff**, per-file and total
  size caps enforced **while streaming**.
- Uploaded `.zip` files are unpacked **recursively** (zip-in-zip) up to
  `max_zip_nesting_depth`. The entry and byte caps are shared across the whole upload so
  nesting cannot multiply them, and every level gets the symlink and path-escape checks.
- A route that takes a server-side path is disabled unless `<PFX>_ALLOWED_ROOTS` is set, and
  never echoes the resolved path.

**Persist + callback route (when the accelerator feeds the FLIP platform).**
`POST /v1/discover/persist` accepts the FLIP payload (`preMigrationZipFile` (repeatable) or
`file`, `organizationId`, `jobId`, `callbackURL`, optional `userId`, `environment`, `mode`,
`logstashHost`/`logstashPort`; camelCase and snake_case both accepted). It answers **202**
once the upload is saved, runs the rest as a background task, and POSTs the outcome to the
callback.
- Order of checks: identifiers → callback URL → persistence configured → upload. Fast
  failures come first.
- The extension selects the path: an `.xlsx` (or a `.zip` that holds exactly one `.xlsx`
  and no source artifacts) is a discovery workbook and is read. Anything else is the estate
  and is parsed. Both converge on one `DiscoveryReport` before any row is written.
- The callback body always has all of its fields. A domain error's message is sent; an
  unexpected exception sends only its class name. Transport errors and 5xx responses are
  retried, 4xx are not.
- The callback URL and the Logstash host are SSRF surfaces: `https` only, no
  private/loopback/link-local addresses unless a setting allows it, checked on arrival and
  again before delivery, redirects not followed.
- One run per `(organizationId, jobId)` at a time (409 otherwise). Re-posting replaces the
  previous rows and never appends.

**Database (`db/`, optional).**
- SQLAlchemy, psycopg, Alembic and httpx live in a `postgres` extra. They are imported lazily
  inside functions, with `ImportError` mapped to 503. The PyInstaller spec excludes `db/`.
- If the tables already exist in the target schema, **mirror them; never regenerate them
  from the model.** Migrations only add what is needed (for example `organization_id` and
  `job_id`, appended last).
- Name each table after the sheet it holds. When renaming one, keep the old name as a view.
- One call is one transaction. Insert in graph order using `RETURNING` keys; delete children
  first, matching on the parent key as well as the identity pair.
- Check column length limits before the insert, with an error that names the table, column,
  limit and actual length.
- `engine.describe_target()` is the only function allowed to render a URL (`host:port/db`,
  no credentials). Use `sslmode=require` for managed services.
- `alembic.ini` holds no URL. `env.py` reads it from settings and creates the schema only if
  it is genuinely absent.

---

## 11. Dependency management (`pyproject.toml`)

- **Build backend: hatchling.** `[tool.hatch.build.targets.wheel] packages = ["<pkg>"]`
  ships every data directory inside the package. **Never add `force-include`** for them:
  hatchling ≥ 1.27 refuses the duplicate file. `tests/test_packaging.py` builds a real wheel
  and asserts each resource is present exactly once.
- `requires-python = ">=3.11,<3.14"`. `version` matches `version.py`. Include the
  `"Private :: Do Not Upload"` classifier.
- `dependencies`: the runtime only, with lower bounds (`>=`), no upper pins.
- `[project.optional-dependencies]`:
  - `postgres`: the database driver, ORM, Alembic and httpx. These are never base
    dependencies.
  - `dev`: pytest, pytest-cov, ruff, mypy, pyinstaller, httpx, type stubs (`types-*`) and
    `"<dist>[postgres]"`.
- `[project.scripts] <dist> = "<pkg>.cli:app"`.
- **uv** is the package manager. Commit `uv.lock`. `pip install -e ".[dev]"` must also work.
- Tool configuration lives in the same file:
  - **ruff:** `line-length = 100`, `target-version = "py311"`, rules
    `E W F I B UP C4 SIM RUF`, ignore `B008`, `known-first-party = ["<pkg>"]`.
  - **mypy:** `strict = true`, `warn_unreachable`, `disallow_any_generics`,
    `no_implicit_reexport`, the `pydantic.mypy` plugin. Narrow per-module overrides only for
    untyped third-party calls.
  - **pytest:** `testpaths = ["tests"]`,
    `addopts = "-q --strict-markers --strict-config --cov=<pkg> --cov-fail-under=80"`,
    `filterwarnings = ["error", ...]`, markers `slow`, `integration`, `database`.
  - **coverage:** `branch = true`. Omit `__main__.py` and `db/migrations/*`.
- Every module starts with `from __future__ import annotations` and declares `__all__`.

## 12. Makefile

`.DEFAULT_GOAL := help`. Each target has a `## description` comment that `make help` prints.
Variables: `PYTHON ?= python`, `IMAGE ?= <dist>:<version>`, and a throwaway-Postgres block
(`PG_CONTAINER`, `PG_PORT`, `TEST_DB_URL`).

| Target | Does |
|---|---|
| `help` | List targets |
| `install` | `pip install -e ".[dev]"` |
| `install-db` | `pip install -e ".[dev,postgres]"` |
| `lint` | `ruff check .` + `ruff format --check .` + `mypy <pkg> tests scripts` |
| `test` | `pytest` (with the coverage gate) |
| `test-all` | `pytest -m "" --run-slow` |
| `test-db` | `db-up`, then the database tests against it |
| `build` | `packaging/build.sh`: the one-file binary for this OS |
| `build-docker` | `docker build -t $(IMAGE) .` |
| `serve` | `python -m <pkg> serve --host 0.0.0.0` |
| `report` | `python generate_report.py` |
| `assets` | Regenerate images, icons and the catalog |
| `db-up` / `db-down` | Start or stop a throwaway `postgres:16-alpine` |
| `migrate` | `alembic upgrade head` |
| `clean` | Remove build, dist and caches |

## 13. Docker

**Dockerfile (multi-stage):**
1. `FROM python:3.12-slim AS build`: install build-essential and C headers, then
   `pip wheel --wheel-dir /wheels ".[postgres]"`.
2. `FROM python:3.12-slim AS runtime`: runtime libraries plus `curl` only. Set
   `PYTHONDONTWRITEBYTECODE=1`, `PYTHONUNBUFFERED=1` and `PIP_NO_CACHE_DIR=1`. Run as a
   **non-root user** (uid 10001). Install from `/wheels` with `--no-index`, then delete them.
   Copy `alembic.ini`.
3. `EXPOSE <PORT>` (documentation only). `HEALTHCHECK` curls
   `http://127.0.0.1:${<PFX>_API_PORT:-<PORT>}/healthz`.
4. `ENTRYPOINT ["python", "-m", "<pkg>"]` and `CMD ["serve", "--host", "0.0.0.0"]`. **Never
   hard-code the port in CMD.**

**docker-compose.yml:**
- `api` service: `build: .`; ports `"${<PFX>_API_PORT:-<PORT>}:${<PFX>_API_PORT:-<PORT>}"`;
  non-secret `<PFX>_` defaults listed under `environment` (commented knobs included, so they
  are discoverable); `env_file: [{path: .env, required: false}]` for secrets; a `CMD-SHELL`
  health check; `restart: unless-stopped`; CPU and memory limits.
- `db` service under `profiles: ["local-db"]` (postgres:16-alpine plus a named volume), so it
  only starts when asked for.

## 14. Git hygiene (`.gitignore`)

Ignore: bytecode, build/dist, virtualenvs, tool caches, IDE files, OS noise, `.env` and
`.env.*` (re-include `!.env.example`), keys, `sample_output/`, every **client artifact
extension** and `*.xlsx`/`*.zip` (re-include `tests/fixtures/**` where needed), generated
archive fixtures, logs and scratch. Client content must never land in version control.
Hostile archive fixtures are **generated** by `tests/archives.py`, never committed.

## 15. Packaging and CI/CD

- **PyInstaller spec** (`packaging/<pkg>.spec`): the entry point is `<pkg>/__main__.py`;
  `datas` covers every data directory read through `resources.py`; `hiddenimports` lists what
  static analysis misses; `db/` is excluded and filtered out of `collect_submodules`. **UPX
  off.** One console binary is both the CLI and the server.
- **PyInstaller cannot cross-compile.** Build each OS on that OS (a CI matrix). `build.sh` /
  `build.ps1` build, then smoke-test the **built binary**: `version`, a catalog check, and an
  analysis of `tests/fixtures/mini` followed by `packaging/verify_*.py` on its output. A
  missing `datas` entry is the classic failure (the binary starts, then dies on its first
  analysis).
- **Deploy pipeline** (`azure-pipelines.yml`): triggered on `development`; a self-hosted
  agent pinned by computer name; `rsync -a --delete --exclude=.git --exclude=.env` into
  `DEPLOY_DIR`; `docker compose up -d --build` with a unique `COMPOSE_PROJECT_NAME`; then poll
  `/healthz` and dump `docker compose logs` on failure. Keep an optional security-scan stage.
- Released binaries are unsigned. The README's troubleshooting section covers Gatekeeper,
  SmartScreen and glibc.

## 16. Tests and the build order

**Acceptance gate for every change:** `ruff check . && ruff format --check . && mypy <pkg>
tests && pytest`.

Standard tests every accelerator carries:
- determinism (the same tree analysed twice gives equal objects);
- CLI/API parity, field by field;
- one-shot equals two-step, and the discovery workbook round-trips;
- adversarial input (entities, zip-slip, symlinks, zip bombs, nested-zip depth, bad magic
  bytes, oversize uploads);
- no `findall(".//` / descendant search in the parser;
- no hex colours outside `theme.py`;
- every dashboard/computation cell is a formula that resolves to a real Summary row;
- the wheel carries each resource exactly once;
- the default port is a setting, not a literal;
- `conftest.py` clears `<PFX>_*` variables **and** `env_file`, so a developer's `.env` cannot
  change the suite.

**Build in ten numbered prompts.** Each produces named modules and leaves the gate green.
Later modules exist as stubs with `TODO(prompt NN - title)` docstrings.

| # | Prompt | Produces |
|---|---|---|
| 01 | Scaffold, configuration and domain model | `pyproject.toml`, tree, `config`, `errors`, `models`, `resources`, `version` |
| 02 | Discovery and hardened reader | `discovery.py`, `reader.py`, adversarial fixtures |
| 03 | Parser → inventory and feature counts | `parser.py` |
| 04 | Target-support catalog | `catalog/`, `scripts/build_catalog.py` |
| 05 | Complexity, automation and effort | `estimation/` |
| 06 | Plan, lanes and schedule | `estimation/plan.py` |
| 07 | Theme, assets and data sheets | `excel/theme.py`, `assets/`, `writer.py`, `sheets/` |
| 08 | Dashboard and charts | `excel/dashboard.py`, `charts.py`, hidden helper sheets |
| 09 | Service, CLI and FastAPI | `service.py`, `cli.py`, `api/` |
| 10 | Packaging, CI, end-to-end tests and docs | spec, build scripts, CI, Dockerfile, README, METHODOLOGY |

Persistence, callbacks and Logstash come after 1.0.0 as additive releases, each recorded in
`CHANGELOG.md` and in the invariants section of `CLAUDE.md`.

---

## 17. Template for the new project's `CLAUDE.md`

```markdown
# CLAUDE.md — <SOURCE> Pre-Migration Effort Analyzer (<TARGET> edition)

Read this first in every session.

## 1. Product
<one paragraph: what it reads (<EXT>), what it writes, the three flows table, ships as exe + API>

## 2. Hard constraints
<copy §2 of the blueprint, with placeholders filled in, plus source-specific rules,
 for example which elements the parser must walk rather than search>

### Service, CLI & API invariants
### Database invariants (if the sink exists)
### Packaging invariants
### Catalog invariants
### Estimation invariants
### Workbook / rendering invariants
### Parser invariants

## 3. Layout
<the tree from §3, trimmed to what exists, and the data-flow diagram>

## 4. Build order
<the ten-prompt table with status>

## 5. The numbers
<complexity thresholds, automation rule, rate card, engine decision table>

## 6. Workbook
<sheet table: name, visible/hidden, what it holds, where its values come from>

## 7. Exit codes
<the table from errors.py>

## 8. Working agreements
pip install -e ".[dev]"  /  ruff check . && ruff format --check .  /  mypy <pkg> tests  /  pytest
- Every prompt leaves ruff, mypy and pytest green.
- Python >=3.11,<3.14; line length 100; mypy strict; `from __future__ import annotations`.
- Domain models are frozen. Wire schemas stay separate from domain models.
```

Whenever you record an invariant in `CLAUDE.md`, write down **why** it exists (the failure it
prevents) and name the test that pins it. A rule without its reason gets "simplified" away by
the next session.
