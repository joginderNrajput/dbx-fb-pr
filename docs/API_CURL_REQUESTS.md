# API test requests (curl → Postman)

Every request of the REST API as a ready-to-paste `curl`. In Postman: **Import → Raw text**,
paste one block, **Continue → Import**, then **Send**. Each block also runs as-is in a
terminal.

Full reference (fields, statuses, settings): [API.md](API.md).

---

## 0. Before you start

**Start the API** (port **7073**):

```bash
pip install -e ".[api,postgres]"
python discovery.py serve --host 0.0.0.0          # without Docker
# or
docker compose up -d --build                       # with Docker (add --profile local-db for Postgres)
```

**Replace these placeholders** in the requests:

| Placeholder | Put here |
|---|---|
| `http://localhost:7073` | the API address (change host / port if it runs elsewhere) |
| `/path/to/databricks_discovery.xlsx` | a discovery workbook written by this tool (`python discovery.py discover …`) |
| `https://adb-0000000000000000.0.azuredatabricks.net` | your Databricks workspace URL |
| `<CLIENT_ID>` / `<CLIENT_SECRET>` | service principal (OAuth M2M) application id and secret |
| `<PERSONAL_ACCESS_TOKEN>` | a Databricks personal access token (alternative to the service principal) |
| `<RUN_ID>` | the `runId` returned by a POST request |
| `<API_KEY>` | only if the server sets `DBXF_API_KEY` |

**Postman tips**

- *File uploads*: after importing a request with `--form 'file=@…'`, open **Body → form-data**
  and pick the file again in the `file` row (Postman cannot read the path from the curl).
- *Downloads* (section 4): use **Send → Send and Download** to save the `.xlsx`.
- *Long runs*: a live Databricks discovery with `wait=true` can take minutes; raise
  **Settings → General → Request timeout** or use `wait=false` and poll (section 3).
- *Variables*: to switch servers easily, replace `http://localhost:7073` with `{{baseUrl}}`
  after importing and define `baseUrl` in a Postman environment.
- *API key*: when the server sets `DBXF_API_KEY`, add the header
  `X-API-Key: <API_KEY>` to every `/v1` request (see section 6).
- *Credentials*: never save real secrets in a shared Postman collection; use Postman
  environment variables of type *secret*.

**Saving to the database**: when the server has `DBXF_DATABASE_URL` set, every run is saved
to Postgres unless the request sends `persist` = `false`; without a database, runs are not
saved and `persist` = `true` is refused with 503.

The flow is always: **POST** (get `runId`) → **GET run** until `status` is `succeeded` or
`failed` → **GET** the workbooks.

---

## 1. Health

### 1.1 Health check (no API key needed)

```bash
curl --location 'http://localhost:7073/healthz'
```

Expected **200**: `{"status":"ok","version":"0.2.0","database":"not configured"}` (or the
database `host:port/db` when `DBXF_DATABASE_URL` is set).

---

## 2. Start an assessment

### 2.1 Upload a discovery workbook (assessment only), background run

```bash
curl --location 'http://localhost:7073/v1/assessments' \
--form 'organizationId="org-123"' \
--form 'jobId="job-001"' \
--form 'file=@"/path/to/databricks_discovery.xlsx"'
```

Expected **202** with `runId`, `status: "queued"`, `mode: "workbook"` and `links`.

### 2.2 Upload a discovery workbook and wait for the result

```bash
curl --location 'http://localhost:7073/v1/assessments' \
--form 'organizationId="org-123"' \
--form 'jobId="job-002"' \
--form 'wait="true"' \
--form 'file=@"/path/to/databricks_discovery.xlsx"'
```

Expected **200** with `status: "succeeded"`, the `assessment` summary (assets, Simple / Medium /
Complex, automation levels, hours, `saving_pct`) and download `links`.

### 2.3 Upload a discovery workbook and save to Postgres

Needs `DBXF_DATABASE_URL` on the server and `python discovery.py db-init` run once.

```bash
curl --location 'http://localhost:7073/v1/assessments' \
--form 'organizationId="org-123"' \
--form 'jobId="job-003"' \
--form 'persist="true"' \
--form 'wait="true"' \
--form 'file=@"/path/to/databricks_discovery.xlsx"'
```

Expected **200**, `persisted.rows` = `{"totals":1,"inventory":…,"finding":…,"estimation":…,"computation":1}`.
Without a database configured: **503**. Sending the same `organizationId` + `jobId` again
replaces that pair's rows (`replacedPreviousRun: true`).

### 2.4 Databricks credentials, JSON, service principal (discovery + assessment)

Uses Kanerika platform field names (`workspaceId` = workspace URL, `databricksCatalog`,
`databricksSchema`).

```bash
curl --location 'http://localhost:7073/v1/assessments/databricks' \
--header 'Content-Type: application/json' \
--data '{
  "organizationId": "org-123",
  "jobId": "job-010",
  "workspaceId": "https://adb-0000000000000000.0.azuredatabricks.net",
  "clientId": "<CLIENT_ID>",
  "clientSecret": "<CLIENT_SECRET>",
  "databricksCatalog": "my_catalog",
  "databricksSchema": "default"
}'
```

Expected **202** with `runId`, `mode: "databricks"`. Poll with section 3.

### 2.5 Databricks credentials, JSON, personal access token, wait for the result

```bash
curl --location 'http://localhost:7073/v1/assessments/databricks' \
--header 'Content-Type: application/json' \
--data '{
  "organizationId": "org-123",
  "jobId": "job-011",
  "workspaceUrl": "https://adb-0000000000000000.0.azuredatabricks.net",
  "token": "<PERSONAL_ACCESS_TOKEN>",
  "wait": true
}'
```

Expected **200** (`status: "succeeded"`, `discovery` + `assessment` summaries) or **422** with
`status: "failed"` and an `error` sentence (for example rejected credentials).

### 2.6 Databricks credentials, JSON, several catalogs / schemas, save snapshot and persist

`catalogs` / `schemas` accept a list or a comma-separated string; snake_case keys work too.

```bash
curl --location 'http://localhost:7073/v1/assessments/databricks' \
--header 'Content-Type: application/json' \
--data '{
  "organization_id": "org-123",
  "job_id": "job-012",
  "workspace_url": "https://adb-0000000000000000.0.azuredatabricks.net",
  "client_id": "<CLIENT_ID>",
  "client_secret": "<CLIENT_SECRET>",
  "catalogs": ["sales", "finance"],
  "schemas": ["sales.default", "finance.reporting"],
  "saveSnapshot": true,
  "persist": true
}'
```

Expected **202** (or **503** if no database is configured, because `persist` is true).

### 2.7 Databricks credentials as multipart form (same endpoint as the upload)

```bash
curl --location 'http://localhost:7073/v1/assessments' \
--form 'organizationId="org-123"' \
--form 'jobId="job-013"' \
--form 'workspaceUrl="https://adb-0000000000000000.0.azuredatabricks.net"' \
--form 'clientId="<CLIENT_ID>"' \
--form 'clientSecret="<CLIENT_SECRET>"' \
--form 'catalogs="my_catalog"' \
--form 'schemas="default"'
```

Expected **202**, `mode: "databricks"`. A personal access token works too: replace the
`clientId` / `clientSecret` rows with `--form 'token="<PERSONAL_ACCESS_TOKEN>"'`.

---

## 3. Follow a run

### 3.1 Run status and results

```bash
curl --location 'http://localhost:7073/v1/runs/<RUN_ID>'
```

Expected **200**. `status` goes `queued` → `running` → `succeeded` | `failed`. When finished:
`discovery` (counts per item type), `assessment` (portfolio computation), `persisted` (if
saved) and `links` to the workbooks. Unknown id: **404**; expired run (after
`DBXF_API_RUN_TTL_S`, default 24 h): **410**.

---

## 4. Download the workbooks

In Postman use **Send and Download**.

### 4.1 Assessment workbook

```bash
curl --location 'http://localhost:7073/v1/runs/<RUN_ID>/assessment' \
--output databricks_assessment.xlsx
```

### 4.2 Discovery workbook (the uploaded one, or the one the run generated)

```bash
curl --location 'http://localhost:7073/v1/runs/<RUN_ID>/discovery' \
--output databricks_discovery.xlsx
```

Expected **200** with an `.xlsx`. Before the run has produced it: **404**.

---

## 5. Error cases (expected failures)

### 5.1 Neither a workbook nor credentials → 422

```bash
curl --location 'http://localhost:7073/v1/assessments' \
--form 'organizationId="org-123"' \
--form 'jobId="job-020"'
```

### 5.2 Both a workbook and credentials → 422

```bash
curl --location 'http://localhost:7073/v1/assessments' \
--form 'organizationId="org-123"' \
--form 'jobId="job-021"' \
--form 'workspaceUrl="https://adb-0000000000000000.0.azuredatabricks.net"' \
--form 'token="<PERSONAL_ACCESS_TOKEN>"' \
--form 'file=@"/path/to/databricks_discovery.xlsx"'
```

### 5.3 Workspace URL without a token or client secret → 422

```bash
curl --location 'http://localhost:7073/v1/assessments/databricks' \
--header 'Content-Type: application/json' \
--data '{
  "organizationId": "org-123",
  "jobId": "job-022",
  "workspaceUrl": "https://adb-0000000000000000.0.azuredatabricks.net"
}'
```

### 5.4 Missing organizationId / jobId → 422

```bash
curl --location 'http://localhost:7073/v1/assessments/databricks' \
--header 'Content-Type: application/json' \
--data '{
  "workspaceUrl": "https://adb-0000000000000000.0.azuredatabricks.net",
  "token": "<PERSONAL_ACCESS_TOKEN>"
}'
```

### 5.5 Upload that is not an .xlsx → 415

Pick any `.csv` / `.txt` file.

```bash
curl --location 'http://localhost:7073/v1/assessments' \
--form 'organizationId="org-123"' \
--form 'jobId="job-023"' \
--form 'file=@"/path/to/any_file.csv"'
```

### 5.6 An .xlsx that is not a discovery workbook → 422 (run fails)

Pick any other Excel file.

```bash
curl --location 'http://localhost:7073/v1/assessments' \
--form 'organizationId="org-123"' \
--form 'jobId="job-024"' \
--form 'wait="true"' \
--form 'file=@"/path/to/some_other_workbook.xlsx"'
```

Expected **422**, `status: "failed"`, `error` names the problem (for example
*"… is not a discovery workbook (no Assets, Findings sheet)."*).

### 5.7 Same organizationId + jobId while a run is still in progress → 409

Send 2.4 (background run), then immediately send it again with the same `jobId`.

### 5.8 persist=true but no database configured → 503

```bash
curl --location 'http://localhost:7073/v1/assessments/databricks' \
--header 'Content-Type: application/json' \
--data '{
  "organizationId": "org-123",
  "jobId": "job-025",
  "workspaceUrl": "https://adb-0000000000000000.0.azuredatabricks.net",
  "token": "<PERSONAL_ACCESS_TOKEN>",
  "persist": true
}'
```

### 5.9 Unknown run id → 404

```bash
curl --location 'http://localhost:7073/v1/runs/does-not-exist'
```

---

## 6. With an API key

Only when the server is started with `DBXF_API_KEY=<API_KEY>`. Every `/v1` request needs the
header; `/healthz` never does.

### 6.1 Request with the key → normal response

```bash
curl --location 'http://localhost:7073/v1/assessments' \
--header 'X-API-Key: <API_KEY>' \
--form 'organizationId="org-123"' \
--form 'jobId="job-030"' \
--form 'file=@"/path/to/databricks_discovery.xlsx"'
```

### 6.2 Without (or with a wrong) key → 401

```bash
curl --location 'http://localhost:7073/v1/runs/<RUN_ID>' \
--header 'X-API-Key: wrong-key'
```

---

## 7. Interactive documentation

The server also publishes its OpenAPI description, which Postman can import as a whole
collection (**Import → Link**):

```bash
curl --location 'http://localhost:7073/openapi.json'
```

Swagger UI in a browser: `http://localhost:7073/docs`.
