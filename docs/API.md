# REST API

Runs the assessment from either an uploaded **discovery workbook** or **Databricks
credentials** (then the discovery runs first), returns both workbooks for download, and
optionally writes the database tables (see [ASSESSMENT.md](ASSESSMENT.md)).

## Run it

The database is the existing **Azure Database for PostgreSQL**, configured in `.env`
(`DBXF_DATABASE_URL`, `DBXF_DB_SCHEMA`, `DBXF_DB_TABLE_PREFIX`; template: `.env.example`).
No Postgres container is used.

```bash
pip install -e ".[api,postgres]"
python discovery.py db-init                      # Alembic: create / upgrade the tables (idempotent)
python discovery.py serve --host 0.0.0.0         # port DBXF_API_PORT (7073)
```

Docker: `docker compose up -d --build`. The container reads `.env` and applies the Alembic
migrations on start-up (`DBXF_DB_AUTO_MIGRATE=true`), then serves on 7073.
Interactive docs: `http://localhost:7073/docs`.

| Setting | Default | |
|---|---|---|
| `DBXF_API_PORT` / `DBXF_API_HOST` | 7073 / 127.0.0.1 | listening address |
| `DBXF_API_KEY` | off | when set, every `/v1` call needs header `X-API-Key` |
| `DBXF_DATABASE_URL` | off | Postgres; when set, runs persist by default |
| `DBXF_DB_SCHEMA` | `databricks_to_fabric_premigration` | schema of the tables |
| `DBXF_DB_TABLE_PREFIX` | empty | e.g. `dbx_` when the schema is shared with another accelerator |
| `DBXF_DB_SSLMODE` | `require` (remote) / `prefer` (localhost) | Azure needs TLS |
| `DBXF_DB_AUTO_MIGRATE` | false (true in docker-compose) | run the migrations when the API starts |
| `DBXF_ASSESSMENT_RULES` | bundled | rules file used by every run |
| `DBXF_API_RUN_TTL_S` | 86400 | finished runs (and their workbooks) expire → 410 |
| `DBXF_MAX_UPLOAD_BYTES` | 100 MB | upload cap, enforced while streaming |
| `DBXF_API_MAX_WORKERS` | 2 | runs in parallel |

Ready-to-paste curl requests for every endpoint (Postman **Import → Raw text**):
[API_CURL_REQUESTS.md](API_CURL_REQUESTS.md).

## Endpoints

| Method | Path | |
|---|---|---|
| GET | `/healthz` | liveness; never needs a key |
| POST | `/v1/assessments` | **multipart**: `file` (discovery `.xlsx`) **or** `workspaceUrl` + `token` / `clientId` + `clientSecret` |
| POST | `/v1/assessments/databricks` | **JSON**: Databricks credentials → discovery → assessment |
| GET | `/v1/runs/{runId}` | status, discovery summary + item counts, computation, persistence outcome |
| GET | `/v1/runs/{runId}/discovery` | discovery workbook (uploaded or generated) |
| GET | `/v1/runs/{runId}/assessment` | assessment workbook |

Common fields: `organizationId`, `jobId` (required, ≤ 128 chars), `persist` (default: true
when a database is configured; `true` without one → 503), `wait` (default false: answer
**202** at once and run in the background; true: answer when done, **200** or **422**).
Only one run per (`organizationId`, `jobId`) at a time (**409** otherwise). Re-posting the same
pair replaces its database rows.

### 1. Upload a discovery workbook (assessment only)

```bash
curl -X POST http://localhost:7073/v1/assessments \
  -F organizationId=org-123 -F jobId=job-42 \
  -F file=@databricks_discovery_adb-123_20261012_1700.xlsx
```

### 2. Databricks credentials (discovery + assessment), JSON

Field names of Kanerika's platform are accepted as they are (`workspaceId` = workspace URL,
`databricksCatalog`, `databricksSchema`); camelCase and snake_case both work.

```bash
curl -X POST http://localhost:7073/v1/assessments/databricks \
  -H 'Content-Type: application/json' \
  -d '{
        "organizationId": "org-123",
        "jobId": "job-43",
        "workspaceId": "https://adb-0000000000000000.0.azuredatabricks.net",
        "clientId": "<service principal application id>",
        "clientSecret": "<service principal OAuth secret>",
        "databricksCatalog": "my_catalog",
        "databricksSchema": "default",
        "wait": false
      }'
```

`token` (personal access token) can replace `clientId` / `clientSecret`. `catalogs` /
`schemas` (list or comma string) limit Unity Catalog collection; workspace-level objects
(notebooks, jobs, compute, dashboards …) are always collected. Credentials are used for the
run only: never stored, logged or returned.

### 3. Poll and download

```bash
curl http://localhost:7073/v1/runs/<runId>
curl -o assessment.xlsx http://localhost:7073/v1/runs/<runId>/assessment
curl -o discovery.xlsx  http://localhost:7073/v1/runs/<runId>/discovery
```

Response (abridged):

```json
{
  "runId": "9f1c…", "status": "succeeded", "mode": "databricks",
  "organizationId": "org-123", "jobId": "job-43",
  "discovery": {"assessableObjects": 41, "byReadiness": {"Compatible": 25, "…": 0},
                "warnings": 3, "counts": {"notebooks": 6, "jobs": 3, "tables": 4, "…": 0}},
  "assessment": {"total_assets": 41, "simple_count": 22, "medium_count": 14,
                 "complex_count": 5, "fully_automated": 24, "partially_automated": 13,
                 "manual": 4, "total_manual_hours": 218.92,
                 "total_automation_hours": 151.23, "hours_saved": 67.69,
                 "saving_pct": 0.3092, "rules_version": "assessment_rules.yaml v1 (…)"},
  "persisted": {"scanId": 7, "target": "db.example.com:5432/premig",
                "rows": {"totals": 1, "inventory": 41, "finding": 70, "estimation": 41,
                         "computation": 1}, "replacedPreviousRun": false},
  "links": {"status": "…/v1/runs/9f1c…", "discoveryWorkbook": "…/discovery",
            "assessmentWorkbook": "…/assessment"}
}
```

`status` is `queued` → `running` → `succeeded` | `failed` (with `error`: a sentence naming
what failed, never client data or secrets).

## Status codes

| Code | When |
|---|---|
| 200 / 202 | finished (`wait=true`) / accepted |
| 401 | missing or wrong `X-API-Key` |
| 404 / 410 | unknown run / run expired (TTL) |
| 409 | a run for this organizationId + jobId is still in progress |
| 413 / 415 | upload too large / not an `.xlsx` (extension and file signature are checked) |
| 422 | missing fields, both or neither of file and credentials, or (`wait=true`) the run failed |
| 503 | `persist=true` but no database configured |
