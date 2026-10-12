#!/usr/bin/env python3
"""
dbx2fabric_assess.py - Databricks -> Microsoft Fabric PRE-MIGRATION assessment.

Step 1  Inventory : what assets exist (live via REST API, or offline from exported notebooks)
Step 2  Score     : migration-readiness score 0-100 per asset (Easy / Moderate / Hard)
Step 3  Effort    : estimated manual hours + Fabric target + advice per finding
Output  : report.html, assets.csv, assessment.json, dependencies.json

Live  : python dbx2fabric_assess.py --host https://adb-123.azuredatabricks.net --token dapi...
        (or env DATABRICKS_HOST / DATABRICKS_TOKEN)
Offline: python dbx2fabric_assess.py --path ./exported_notebooks
No third-party packages needed (stdlib only). Read-only: nothing is changed in Databricks.
"""
import argparse, csv, html, json, os, posixpath, re, sys, time, base64
import urllib.error, urllib.parse, urllib.request
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

SKIPPED = []  # endpoints we could not read (permissions / not enabled)

# --------------------------------------------------------------------------
# 1. CODE RULES  (id, regex, penalty pts, hours, Fabric advice)
#    Add/tune rules here - this is the knowledge base of the scanner.
# --------------------------------------------------------------------------
M = re.I | re.M
RULES = [
    ("DBU-SECRETS",   r"dbutils\.secrets\.",                   8, 0.5, "Use notebookutils.credentials.getSecret(<AKV url>, <name>); recreate secrets in Azure Key Vault"),
    ("DBU-FS",        r"dbutils\.fs\.(?!mount)",               4, 0.25, "Use notebookutils.fs.* (near 1:1) with abfss:// OneLake paths"),
    ("DBU-MOUNT",     r"dbutils\.fs\.(mount|unmount|mounts)",  10, 1.0, "Mounts not needed: use OneLake shortcuts or abfss:// paths"),
    ("DBU-WIDGETS",   r"dbutils\.widgets\.",                   6, 0.5, "Replace with a Fabric parameter cell + pipeline parameters"),
    ("DBU-NB-RUN",    r"dbutils\.notebook\.(run|exit)",        4, 0.5, "Use notebookutils.notebook.run/exit or a pipeline Notebook activity"),
    ("DBU-TASKVALUES",r"dbutils\.jobs\.taskValues",            8, 1.0, "Use notebook exit values + pipeline activity output expressions"),
    ("DBU-CONTEXT",   r"entry_point|getContext\(\)",          10, 1.0, "Databricks context API has no equivalent; use notebookutils.runtime.context"),
    ("MAGIC-RUN",     r"^\s*(#\s*MAGIC\s+)?%run\b",            3, 0.25, "%run works in Fabric; fix notebook paths/names"),
    ("MAGIC-SH-FS",   r"^\s*(#\s*MAGIC\s+)?%(sh|fs)\b",        6, 0.5, "Rewrite shell/%fs calls with notebookutils or Python"),
    ("DBFS-PATH",     r"dbfs:/|/dbfs/|[\"']/mnt/|FileStore",   10, 1.0, "Repoint to OneLake (abfss://) / Lakehouse Files and move the data"),
    ("ADLS-KEY-CONF", r"fs\.azure\.(account|sas|oauth)",       8, 0.5, "Drop storage keys: use Entra ID / workspace identity, shortcuts"),
    ("UC-3PART",      r"\b(FROM|JOIN|INTO|TABLE|VIEW)\s+`?\w+`?\.`?\w+`?\.`?\w+`?", 5, 0.25, "Map catalog.schema.table -> Lakehouse (schema-enabled) names"),
    ("AUTOLOADER",    r"cloudFiles",                          18, 4.0, "No Auto Loader: use Structured Streaming file source, pipeline triggers or Eventstream"),
    ("DLT",           r"import dlt\b|@dlt\.|dlt\.(read|table|view)|CREATE\s+(OR\s+REFRESH\s+)?(STREAMING|LIVE)\s+(TABLE|VIEW)", 30, 8.0, "No DLT in Fabric: redesign as Materialized Lake Views / Spark jobs"),
    ("COPY-INTO",     r"\bCOPY\s+INTO\b",                     10, 1.5, "Replace with pipeline Copy activity or Spark read + write"),
    ("STREAMING",     r"readStream|writeStream|foreachBatch", 8, 2.0, "Structured Streaming works; re-validate checkpoints, triggers and sinks"),
    ("DBX-SPARKCONF", r"spark\.databricks\.",                 6, 0.5, "Databricks-only Spark configs; remove or map to Fabric equivalents"),
    ("DELTA-ZORDER",  r"\bZORDER\s+BY\b",                     2, 0.25, "Prefer V-Order + OPTIMIZE in Fabric"),
    ("LIQUID-CLUSTER",r"\bCLUSTER\s+BY\b",                    6, 1.0, "Verify liquid clustering support in chosen Fabric runtime"),
    ("GRANTS",        r"^\s*(GRANT|REVOKE|DENY)\b|ALTER\s+\w+\s+\S+\s+OWNER", 6, 1.0, "Re-implement with Fabric workspace roles / OneLake security / SQL permissions"),
    ("DBX-SDK",       r"from databricks\.(sdk|sql|connect)|import databricks_cli|databricks-connect", 12, 2.0, "Replace with Fabric REST APIs / semantic-link / notebookutils"),
    ("FEATURE-STORE", r"databricks\.feature_store|FeatureEngineeringClient|FeatureStoreClient", 25, 6.0, "No Feature Store in Fabric: rebuild as Delta tables + MLflow"),
    ("MLFLOW-DBX",    r"databricks-uc|set_registry_uri\([\"']databricks", 12, 2.0, "Point MLflow at the Fabric workspace tracking/registry"),
    ("MLFLOW",        r"import mlflow",                        3, 0.5, "MLflow is native in Fabric; change experiment/model paths"),
    ("AI-FUNCTIONS",  r"\b(ai_query|ai_classify|ai_extract|ai_gen|ai_summarize|vector_search|http_request)\s*\(", 20, 4.0, "Databricks SQL AI functions: use Fabric AI functions / Azure OpenAI"),
    ("READ-FILES-FN", r"\bread_files\s*\(",                    6, 0.5, "Replace with spark.read on OneLake path"),
    ("DELTA-SHARING", r"delta_sharing|CREATE\s+SHARE",        10, 2.0, "Use OneLake shortcuts / external data sharing in Fabric"),
    ("PIP-INSTALL",   r"%pip install|dbutils\.library",        2, 0.25, "Move to Fabric Environment (public/custom libraries) for repeatability"),
    ("SQL-PROC",      r"\bCREATE\s+(OR\s+REPLACE\s+)?PROCEDURE\b|^\s*CALL\s+\w+\(", 15, 2.0, "Stored procedures: rewrite as T-SQL in Fabric Warehouse or as notebook logic"),
    ("SQL-UDF",       r"\bCREATE\s+(OR\s+REPLACE\s+)?(TEMP(ORARY)?\s+)?FUNCTION\b", 8, 1.0, "SQL UDFs: recreate as Warehouse T-SQL functions or PySpark functions"),
    ("PY-UDF",        r"@udf\b|@pandas_udf\b|\bpandas_udf\(|\budf\(", 3, 0.5, "Python UDFs run in Fabric Spark; validate library dependencies"),
    ("DELTA-CDF",     r"table_changes\(|readChangeFeed|enableChangeDataFeed", 6, 1.0, "Change Data Feed: verify support in the chosen Fabric runtime"),
    ("TIME-TRAVEL",   r"VERSION\s+AS\s+OF|TIMESTAMP\s+AS\s+OF|versionAsOf|timestampAsOf", 2, 0.25, "Time travel works on Lakehouse Delta; confirm log retention after data copy"),
    ("GENERATED-COLS",r"GENERATED\s+(ALWAYS|BY\s+DEFAULT)\s+AS", 6, 1.0, "Identity/generated columns: verify Delta protocol support in Fabric"),
    ("CONSTRAINTS",   r"ADD\s+CONSTRAINT|\bCHECK\s*\(|PRIMARY\s+KEY|FOREIGN\s+KEY", 3, 0.5, "CHECK constraints work on Delta; PK/FK are informational only"),
    ("SPARK-CONF-SET",r"spark\.conf\.set\(", 1, 0.1, "Map session configs to Fabric Environment / %%configure"),
    ("JDBC-ODBC",     r"jdbc:|format\([\"']jdbc|pyodbc|\bodbc\b", 6, 1.0, "Recreate as Fabric connection / on-prem data gateway; move credentials to Key Vault"),
]
COVERAGE = [  # (#, category, coverage, how)
    (1, "Notebooks", "Full", "Workspace export + rule scan (Python/SQL/Scala/R)"),
    (2, "Lakehouse tables (managed Delta)", "Full", "UC tables API: format, Delta features, CDF, types, row/column security"),
    (3, "External tables", "Full", "UC tables + external locations"),
    (4, "Views", "Partial", "UC views + definition scan; session temp views are code only"),
    (5, "Data files", "Partial", "Volumes, external locations, mounts; DBFS root files not listed"),
    (6, "Workflows", "Full", "Jobs API, task-level mapping"),
    (7, "Job tasks", "Full", "Notebook/Python/SQL/JAR/dbt/DLT/run-job/condition/for-each"),
    (8, "Schedules", "Partial", "Detected and flagged; cron complexity not parsed"),
    (9, "Delta Live Tables", "Full", "Pipelines API + DLT code in notebooks"),
    (10, "Unity Catalog", "Full", "Catalogs, schemas, tables, volumes, external locations"),
    (11, "Functions", "Full", "UC functions API + CREATE FUNCTION / UDFs in code"),
    (12, "Stored procedures", "Code scan only", "CREATE PROCEDURE / CALL in notebooks and queries"),
    (13, "SQL queries", "Full", "Saved queries API + SQL scan"),
    (14, "Clusters", "Full", "Init scripts, Docker, GPU, configs, runtime age"),
    (15, "Libraries", "Full", "Cluster library statuses, job libraries, %pip in code"),
    (16, "Secrets", "Full", "Scopes + secret counts (values are not exportable)"),
    (17, "Connections", "Full", "UC connections + JDBC/ODBC usage in code"),
    (18, "Credentials", "Partial", "Storage credentials + service principals; personal access tokens not inventoried"),
    (19, "Mounts", "Full", "/mnt listing + dbutils mount usage"),
    (20, "Volumes", "Full", "UC volumes"),
    (21, "ML assets", "Partial", "UC models + serving endpoints; MLflow experiments not inventoried"),
    (22, "Monitoring", "Partial", "SQL alerts inventoried; job-run history is not migrated"),
    (23, "Permissions", "Partial", "UC catalog/schema grants; table-level and workspace ACLs not covered"),
    (24, "Repos", "Full", "Git folders"),
    (25, "Dashboards", "Partial", "Lakeview dashboards; legacy SQL dashboards not covered"),
    (26, "SQL warehouses", "Full", "Warehouse inventory"),
]
RULES = [(i, re.compile(rx, M), p, h, a) for i, rx, p, h, a in RULES]


@dataclass
class Asset:
    type: str
    name: str
    location: str = ""
    target: str = ""
    penalty: int = 0
    hours: float = 0.0
    findings: list = field(default_factory=list)
    deps: list = field(default_factory=list)   # (relation, target)
    unsupported: bool = False
    meta: dict = field(default_factory=dict)   # source details used by the migration tool

    def add(self, rid, pen, hrs, advice):
        self.findings.append(dict(id=rid, penalty=pen, hours=round(hrs, 2), advice=advice))
        self.penalty += pen
        self.hours += hrs

    @property
    def score(self):
        return max(0, 100 - self.penalty)

    @property
    def bucket(self):
        if self.unsupported:
            return "Unsupported"
        return "Compatible" if self.score >= 80 else "Partial" if self.score >= 50 else "Manual"


def norm_path(p, base=""):
    """/Workspace/Shared/x -> /Shared/x ; resolve ./ and ../ against the calling notebook's folder."""
    p = (p or "").strip().strip("\"'")
    if p.startswith("/Workspace/"):
        p = p[len("/Workspace"):]
    if p and not p.startswith("/") and base.startswith("/"):
        p = posixpath.normpath(posixpath.join(posixpath.dirname(base), p))
    return p


def scan_code(asset, text, lang=""):
    base = asset.location if asset.type == "Notebook" else ""
    for m in re.finditer(r"%run\s+(\S+)", text):
        asset.deps.append(("runs_notebook", norm_path(m.group(1), base)))
    for m in re.finditer(r"dbutils\.notebook\.run\(\s*[\"']([^\"']+)[\"']", text):
        asset.deps.append(("runs_notebook", norm_path(m.group(1), base)))
    for rid, rx, pen, hrs, advice in RULES:
        n = len(rx.findall(text))
        if n:
            asset.add(rid, pen, hrs * (1 + 0.1 * (min(n, 10) - 1)), advice + (f" [{n}x]" if n > 1 else ""))
    lang = (lang or "").upper()
    if lang == "SCALA":
        asset.add("LANG-SCALA", 4, 1.0, "Scala is supported in Fabric notebooks; replace Databricks-specific APIs")
    if lang == "R":
        asset.add("LANG-R", 4, 1.0, "SparkR/R supported in Fabric; verify packages and sparklyr usage")


# --------------------------------------------------------------------------
# 2. DATABRICKS REST CLIENT (read-only GETs)
# --------------------------------------------------------------------------
class Dbx:
    def __init__(self, host, token):
        self.host = host.rstrip("/")
        self.h = {"Authorization": f"Bearer {token}"}

    def get(self, _endpoint, **params):
        q = {k: v for k, v in params.items() if v not in (None, "")}
        url = self.host + _endpoint + ("?" + urllib.parse.urlencode(q) if q else "")
        for i in range(4):
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers=self.h), timeout=90) as r:
                    return json.loads(r.read() or b"{}")
            except urllib.error.HTTPError as e:
                if e.code == 401:
                    sys.exit("401 Unauthorized - check host/token")
                if e.code == 429 or e.code >= 500:
                    time.sleep(2 ** i)
                    continue
                return {"_error": e.code}
            except Exception as e:  # network blips
                time.sleep(2 ** i)
                last = str(e)
        return {"_error": "retries exhausted"}


def paged(c, path, key, **p):
    tok = None
    while True:
        r = c.get(path, page_token=tok, **p)
        if "_error" in r:
            SKIPPED.append(f"{path} (HTTP {r['_error']})")
            return
        yield from r.get(key, [])
        tok = r.get("next_page_token")
        if not tok or r.get("has_more") is False:
            return


# --------------------------------------------------------------------------
# 3. COLLECTORS - one per asset type
# --------------------------------------------------------------------------
def collect_notebooks(c, a):
    out, stack = [], ["/"]
    while stack and len(out) < a.max_notebooks:
        p = stack.pop()
        r = c.get("/api/2.0/workspace/list", path=p)
        if "_error" in r:
            SKIPPED.append(f"workspace/list {p} (HTTP {r['_error']})")
            continue
        for o in r.get("objects", []):
            t, path = o["object_type"], o["path"]
            if t == "DIRECTORY":
                if "/." in path or (a.skip_repos and path.startswith("/Repos")):
                    continue
                stack.append(path)
            elif t == "NOTEBOOK" or (t == "FILE" and path.lower().endswith((".py", ".sql"))):
                ex = c.get("/api/2.0/workspace/export", path=path, format="SOURCE" if t == "NOTEBOOK" else "AUTO")
                if "_error" in ex:
                    SKIPPED.append(f"export {path} (HTTP {ex['_error']})")
                    continue
                text = base64.b64decode(ex.get("content", "")).decode("utf-8", "ignore")
                n = text.count("\n") + 1
                nb = Asset("Notebook", path.split("/")[-1], norm_path(path), "Fabric Notebook", hours=0.25 + n / 1000)
                nb.meta = {"language": o.get("language"), "source_path": path}
                scan_code(nb, text, o.get("language"))
                out.append(nb)
    return out


TASKS = {  # task type -> (penalty, hours, Fabric target)
    "notebook_task": (0, 0.25, "Pipeline: Notebook activity"),
    "spark_python_task": (3, 1.0, "Spark Job Definition"),
    "python_wheel_task": (6, 2.0, "Spark Job Definition + Environment wheel"),
    "spark_jar_task": (6, 2.0, "Spark Job Definition (JAR)"),
    "spark_submit_task": (10, 3.0, "Spark Job Definition (rewrite)"),
    "sql_task": (6, 1.5, "Pipeline: Script/Warehouse activity"),
    "dbt_task": (20, 6.0, "dbt in Fabric (manual setup)"),
    "pipeline_task": (25, 6.0, "DLT -> Materialized Lake Views (manual)"),
    "run_job_task": (3, 0.5, "Pipeline: Invoke Pipeline"),
    "condition_task": (3, 0.5, "Pipeline: If Condition"),
    "for_each_task": (3, 0.5, "Pipeline: ForEach"),
}


def collect_jobs(c, a):
    out = []
    for j in paged(c, "/api/2.1/jobs/list", "jobs", limit=25, expand_tasks="true"):
        s = j.get("settings", {})
        tasks = s.get("tasks", [])
        ja = Asset("Job", s.get("name", str(j.get("job_id"))), f"job_id={j.get('job_id')}",
                   "Data Factory pipeline in Fabric", hours=1.0 + 0.5 * len(tasks))
        ja.meta = {"job_id": j.get("job_id"), "settings": s}
        seen = set()
        for t in tasks:
            if "notebook_task" in t:
                ja.deps.append(("runs_notebook", norm_path(t["notebook_task"].get("notebook_path", ""))))
            if "pipeline_task" in t:
                ja.deps.append(("runs_dlt_pipeline", t["pipeline_task"].get("pipeline_id", "")))
            if "run_job_task" in t:
                ja.deps.append(("runs_job", str(t["run_job_task"].get("job_id", ""))))
            q = ((t.get("sql_task") or {}).get("query") or {}).get("query_id")
            if q:
                ja.deps.append(("runs_sql_query", q))
            for k, (pen, hrs, tgt) in TASKS.items():
                if k in t and k not in seen:
                    seen.add(k)
                    if pen:
                        ja.add("JOB-" + k.upper(), pen, hrs, tgt)
            if t.get("libraries") and "libs" not in seen:
                seen.add("libs")
                ja.add("JOB-LIBRARIES", 3, 0.5, "Move cluster libraries to a Fabric Environment")
        if s.get("schedule"):
            ja.add("JOB-SCHEDULE", 2, 0.25, "Quartz cron -> Fabric pipeline schedule (interval/daily/weekly); complex cron needs manual mapping")
        if s.get("continuous"):
            ja.add("JOB-CONTINUOUS", 10, 2.0, "Continuous job: use streaming notebook/Spark Job Definition with retry policy")
        trig = s.get("trigger") or {}
        if any(k in trig for k in ("file_arrival", "table_update", "table")):
            ja.add("JOB-EVENT-TRIGGER", 8, 2.0, "Use Fabric storage-event triggers / Activator")
        if s.get("webhook_notifications") or s.get("email_notifications", {}).get("on_failure"):
            ja.add("JOB-ALERTS", 3, 0.5, "Add Teams/Outlook activity on failure path")
        for jc in s.get("job_clusters", []):
            if jc.get("new_cluster", {}).get("init_scripts"):
                ja.add("JOB-INIT-SCRIPTS", 8, 1.0, "Init scripts unsupported: move to Environment")
                break
        out.append(ja)
    return out


def collect_clusters(c, a):
    out = []
    for k in c.get("/api/2.0/clusters/list").get("clusters", []):
        if k.get("cluster_source") in ("JOB", "PIPELINE", "PIPELINE_MAINTENANCE"):
            continue  # ephemeral, covered by jobs/pipelines
        ca = Asset("Cluster", k.get("cluster_name", k.get("cluster_id")), k.get("cluster_id", ""),
                   "Fabric Environment + Spark pool", hours=0.5)
        ca.meta = {"spark_version": k.get("spark_version"), "node_type_id": k.get("node_type_id"), "spark_conf": k.get("spark_conf", {})}
        if k.get("init_scripts"):
            ca.add("CLU-INIT-SCRIPTS", 10, 1.5, "Init scripts unsupported: move to Fabric Environment")
        if k.get("docker_image"):
            ca.add("CLU-DOCKER", 15, 3.0, "Custom Docker images unsupported")
        if re.search(r"\b(NC|ND)\d|g[4-6]\.|p[3-5]\.", k.get("node_type_id", "")) or "gpu" in k.get("spark_version", ""):
            ca.add("CLU-GPU", 15, 3.0, "GPU compute: Fabric has no GPU Spark pools; use Azure ML/AI Foundry")
        if any(x.startswith("spark.databricks") for x in k.get("spark_conf", {})):
            ca.add("CLU-SPARKCONF", 4, 0.5, "Databricks-only Spark confs")
        m = re.match(r"(\d+)\.", k.get("spark_version", ""))
        if m and int(m.group(1)) < 12:
            ca.add("CLU-OLD-RUNTIME", 4, 1.0, "Old runtime: code may need updates for Fabric Runtime 1.3+")
        out.append(ca)
    return out


def collect_warehouses(c, a):
    out = []
    for w in c.get("/api/2.0/sql/warehouses").get("warehouses", []):
        wa = Asset("SQL Warehouse", w.get("name", ""), w.get("id", ""),
                   "Fabric Warehouse / Lakehouse SQL endpoint", hours=4.0)
        wa.add("WH-SQL-DIALECT", 15, 0, "Spark SQL vs T-SQL dialect: queries/views need translation for Warehouse")
        out.append(wa)
    return out


def collect_pipelines(c, a):
    out = []
    for p in paged(c, "/api/2.0/pipelines", "statuses", max_results=100):
        da = Asset("DLT Pipeline", p.get("name", ""), p.get("pipeline_id", ""),
                   "Materialized Lake Views / Spark jobs (redesign)", hours=16.0)
        da.add("DLT-NO-EQUIVALENT", 40, 0, "No direct DLT equivalent: expectations, CDC (APPLY CHANGES), streaming tables need redesign")
        out.append(da)
    return out


def is_managed(name):
    return (name or "").startswith(("__databricks", "databricks-"))


SKIP_CATALOGS = {"system", "samples", "__databricks_internal", "hive_metastore"}


def collect_uc(c, a):
    out = []
    for cat in paged(c, "/api/2.1/unity-catalog/catalogs", "catalogs"):
        cn = cat["name"]
        if cn in SKIP_CATALOGS or (a.catalogs and cn not in a.catalogs):
            continue
        for sc in paged(c, "/api/2.1/unity-catalog/schemas", "schemas", catalog_name=cn):
            sn = sc["name"]
            if sn == "information_schema":
                continue
            fq = f"{cn}.{sn}"
            for t in paged(c, "/api/2.1/unity-catalog/tables", "tables", catalog_name=cn, schema_name=sn, max_results=500):
                tt, fmt = t.get("table_type", ""), (t.get("data_source_format") or "").upper()
                ta = Asset("Table/View", f"{fq}.{t['name']}", t.get("storage_location", ""),
                           "OneLake shortcut / Mirrored Databricks catalog / Lakehouse Delta", hours=0.1)
                cols = t.get("columns", [])
                ta.meta = {"table_type": tt, "format": fmt, "storage_location": t.get("storage_location"),
                           "columns": [{"name": x.get("name"), "type": x.get("type_text")} for x in cols],
                           "partition_columns": [x["name"] for x in sorted((x for x in cols if x.get("partition_index") is not None),
                                                                           key=lambda x: x["partition_index"])],
                           "view_definition": t.get("view_definition")}
                if tt == "VIEW":
                    ta.add("TBL-VIEW", 10, 1.0, "View SQL must be re-created/translated")
                elif tt == "MATERIALIZED_VIEW":
                    ta.add("TBL-MV", 25, 4.0, "Rebuild as Fabric Materialized Lake View")
                elif tt == "STREAMING_TABLE":
                    ta.add("TBL-STREAMING", 30, 6.0, "Rebuild as streaming Spark job")
                elif tt == "FOREIGN":
                    ta.add("TBL-FOREIGN", 15, 2.0, "Federated table: use Fabric mirroring/shortcut to source")
                elif fmt and fmt != "DELTA":
                    ta.add("TBL-NON-DELTA", 5, 0.5, f"{fmt} table: convert to Delta or shortcut as files")
                if t.get("row_filter") or any(col.get("mask") for col in t.get("columns", [])):
                    ta.add("TBL-ROW-COL-SECURITY", 15, 3.0, "Row filters/column masks: redo as OneLake security / RLS")
                props = t.get("properties", {})
                if any(k.startswith("delta.feature.") or k == "delta.enableDeletionVectors" for k in props):
                    ta.add("TBL-DELTA-FEATURES", 5, 0.5, "Advanced Delta protocol features: verify Fabric runtime compatibility")
                if str(props.get("delta.enableChangeDataFeed", "")).lower() == "true":
                    ta.add("TBL-CDF", 6, 1.0, "Change Data Feed enabled: verify support in the chosen Fabric runtime")
                if any((col.get("type_name") or "").upper() in ("VARIANT", "INTERVAL", "GEOGRAPHY", "GEOMETRY", "OBJECT") for col in t.get("columns", [])):
                    ta.add("TBL-TYPE", 8, 1.0, "Unsupported/newer data type: convert the column before migration")
                if t.get("view_definition"):
                    scan_code(ta, t["view_definition"])
                out.append(ta)
            for v in paged(c, "/api/2.1/unity-catalog/volumes", "volumes", catalog_name=cn, schema_name=sn):
                va = Asset("Volume", f"{fq}.{v['name']}", v.get("storage_location", ""),
                           "Lakehouse Files / OneLake shortcut", hours=0.25)
                va.meta = {"storage_location": v.get("storage_location"), "volume_type": v.get("volume_type")}
                va.add("VOL-FILES", 3, 0, "Copy files or shortcut the underlying storage")
                out.append(va)
    for e in paged(c, "/api/2.1/unity-catalog/external-locations", "external_locations"):
        if is_managed(e.get("name")):
            continue
        ea = Asset("External Location", e["name"], e.get("url", ""), "OneLake shortcut (ADLS Gen2)", hours=0.5)
        ea.meta = {"url": e.get("url")}
        ea.add("EXTLOC", 3, 0, "Create ADLS shortcut; grant Fabric identity access")
        out.append(ea)
    return out


def collect_models(c, a):
    out = []
    for m in paged(c, "/api/2.1/unity-catalog/models", "registered_models"):
        cat = (m.get("catalog_name") or m.get("full_name", "").split(".")[0])
        if cat in SKIP_CATALOGS or (a.catalogs and cat not in a.catalogs):
            continue
        ma = Asset("ML Model", m.get("full_name", m.get("name", "")), "", "Fabric ML model (MLflow)", hours=2.0)
        ma.add("MODEL-REGISTRY", 10, 0, "Re-register model artifacts in Fabric MLflow registry")
        out.append(ma)
    for e in c.get("/api/2.0/serving-endpoints").get("endpoints", []):
        if e.get("name", "").startswith("databricks-"):
            continue
        sa = Asset("Serving Endpoint", e.get("name", ""), "", "Azure ML / AI Foundry endpoint", hours=16.0)
        sa.add("SERVING-NO-EQUIVALENT", 60, 0, "No native Fabric model serving: rehost on Azure ML/AI Foundry")
        sa.unsupported = True
        out.append(sa)
    return out


def collect_secrets(c, a):
    out = []
    for s in c.get("/api/2.0/secrets/scopes/list").get("scopes", []):
        keys = [x.get("key") for x in c.get("/api/2.0/secrets/list", scope=s["name"]).get("secrets", [])]
        n = len(keys)
        sa = Asset("Secret Scope", s["name"], f"{n} secrets", "Azure Key Vault", hours=0.5 + 0.1 * n)
        sa.meta = {"scope": s["name"], "keys": keys}
        sa.add("SECRET-VALUES", 25, 0, "Secret values cannot be exported: re-enter into Key Vault")
        out.append(sa)
    return out


def collect_dashboards(c, a):
    out = []
    for d in paged(c, "/api/2.0/lakeview/dashboards", "dashboards"):
        da = Asset("Dashboard", d.get("display_name", ""), d.get("dashboard_id", ""), "Power BI report / semantic model", hours=8.0)
        da.add("DASH-REBUILD", 45, 0, "Manual rebuild in Power BI (datasets -> semantic model, visuals -> report)")
        out.append(da)
    return out


def collect_repos(c, a):
    out = []
    for r in paged(c, "/api/2.0/repos", "repos"):
        out.append(Asset("Repo", r.get("path", ""), r.get("url", ""), "Fabric Git integration (Azure DevOps/GitHub)", hours=0.25))
    return out


def uc_schemas(c, a):
    for cat in paged(c, "/api/2.1/unity-catalog/catalogs", "catalogs"):
        cn = cat["name"]
        if cn in SKIP_CATALOGS or (a.catalogs and cn not in a.catalogs):
            continue
        for sc in paged(c, "/api/2.1/unity-catalog/schemas", "schemas", catalog_name=cn):
            if sc["name"] != "information_schema":
                yield cn, sc["name"]


def collect_functions(c, a):
    out = []
    for cn, sn in uc_schemas(c, a):
        for f in paged(c, "/api/2.1/unity-catalog/functions", "functions", catalog_name=cn, schema_name=sn):
            if not (f.get("input_params") or {}).get("parameters") and f.get("full_name"):
                # the list call can omit parameters: fetch the full function
                g = c.get("/api/2.1/unity-catalog/functions/" + urllib.parse.quote(f["full_name"]))
                if "_error" not in g:
                    f = g
            py = (f.get("external_language") or "").upper() == "PYTHON" or f.get("routine_body") == "EXTERNAL"
            fa = Asset("Function", f.get("full_name", f.get("name", "")), "", "Warehouse T-SQL function / PySpark function", hours=1.0)
            fa.meta = {"language": "PYTHON" if py else "SQL", "definition": f.get("routine_definition"), "full_name": f.get("full_name"),
                       "input_params": [{"name": x.get("name"), "type": x.get("type_text")} for x in (f.get("input_params") or {}).get("parameters", [])],
                       "return_type": f.get("full_data_type") or f.get("data_type"), "is_table": bool(f.get("return_params"))}
            fa.add("FUNC-PYTHON" if py else "FUNC-SQL", 10 if py else 8, 1.0, "Recreate function; body needs translation and validation")
            scan_code(fa, f.get("routine_definition") or "")
            out.append(fa)
    return out


def collect_permissions(c, a):
    out, seen = [], set()

    def grant(kind, name):
        r = c.get(f"/api/2.1/unity-catalog/permissions/{kind}/{name}")
        if "_error" in r:
            SKIPPED.append(f"permissions {kind} {name} (HTTP {r['_error']})")
            return
        pa = r.get("privilege_assignments", [])
        if pa:
            g = Asset("Permission", f"{kind}:{name}", f"{len(pa)} principals",
                      "Fabric workspace roles / item permissions / OneLake security", hours=0.25 * len(pa))
            g.meta = {"securable": f"{kind}:{name}", "grants": pa}
            g.add("PERM-REMAP", 30, 0, "Map principals/privileges to Fabric roles; there is no 1:1 GRANT model")
            out.append(g)

    for cn, sn in uc_schemas(c, a):
        if cn not in seen:
            seen.add(cn)
            grant("catalog", cn)
        grant("schema", f"{cn}.{sn}")
    return out


def collect_queries(c, a):
    out = []
    for q in paged(c, "/api/2.0/sql/queries", "results", page_size=100):
        qa = Asset("SQL Query", q.get("display_name", q.get("name", "")), q.get("id", ""), "Fabric SQL query / notebook", hours=0.5)
        scan_code(qa, q.get("query_text", ""))
        qa.meta = {"query_text": q.get("query_text", "")}
        qa.add("QUERY-DIALECT", 10, 0, "Spark SQL vs T-SQL: verify dialect if moved to Warehouse")
        out.append(qa)
    return out


def collect_alerts(c, a):
    out, seen = [], set()
    # query-based alerts and alerts created in the new alert editor live on different endpoints
    for path, key in (("/api/2.0/sql/alerts", "results"), ("/api/2.0/alerts", "alerts")):
        for al in paged(c, path, key, page_size=100):
            aid = al.get("id")
            if aid in seen:
                continue
            seen.add(aid)
            aa = Asset("Alert", al.get("display_name", ""), aid or "", "Fabric Activator / pipeline notification", hours=2.0)
            scan_code(aa, al.get("query_text") or "")
            aa.add("ALERT-REBUILD", 20, 0, "Rebuild in Activator or a pipeline with Teams/Outlook activity")
            out.append(aa)
    return out


LIB_PEN = dict(pypi=0, requirements=2, whl=3, jar=5, cran=6, maven=8, egg=8)


def collect_libraries(c, a):
    seen, out = set(), []
    for st in c.get("/api/2.0/libraries/all-cluster-statuses").get("statuses", []):
        for ls in st.get("library_statuses", []):
            lib = ls.get("library", {})
            kind = next((k for k in LIB_PEN if k in lib), "other")
            v = lib.get(kind, "")
            name = v if isinstance(v, str) else (v.get("package") or v.get("coordinates") or str(v))
            if (kind, name) in seen:
                continue
            seen.add((kind, name))
            la = Asset("Library", name, kind, "Fabric Environment library", hours=0.25)
            la.meta = {"kind": kind, "name": name}
            if LIB_PEN.get(kind, 5):
                la.add("LIB-" + kind.upper(), LIB_PEN.get(kind, 5), 0.25,
                       "Add to Fabric Environment: PyPI/whl/jar OK; Maven must be downloaded as jar; egg unsupported")
            out.append(la)
    return out


def collect_connections(c, a):
    out = []
    for x in paged(c, "/api/2.1/unity-catalog/connections", "connections"):
        ca = Asset("Connection", x.get("name", ""), x.get("connection_type", ""), "Fabric connection / on-prem data gateway", hours=1.0)
        ca.meta = {"connection_type": x.get("connection_type")}
        ca.add("CONN-RECREATE", 15, 0, "Recreate connection; credentials cannot be exported")
        out.append(ca)
    return out


def collect_credentials(c, a):
    out = []
    for sc in paged(c, "/api/2.1/unity-catalog/storage-credentials", "storage_credentials"):
        if is_managed(sc.get("name")):
            continue
        x = Asset("Credential", sc.get("name", ""), "storage credential", "Fabric workspace identity / Entra service principal", hours=1.0)
        x.add("CRED-STORAGE", 20, 0, "Grant the Fabric identity access to the storage; secrets are not exportable")
        out.append(x)
    r = c.get("/api/2.0/preview/scim/v2/ServicePrincipals", count=1000)
    if "_error" in r:
        SKIPPED.append(f"scim ServicePrincipals (HTTP {r['_error']})")
    for sp in r.get("Resources", []):
        x = Asset("Credential", sp.get("displayName", sp.get("applicationId", "")), "service principal",
                  "Entra service principal + Fabric connection", hours=1.0)
        x.add("CRED-SP", 20, 0, "Enable SPs in Fabric tenant settings; recreate secrets")
        out.append(x)
    return out


def collect_mounts(c, a):
    out = []
    r = c.get("/api/2.0/dbfs/list", path="/mnt")
    if "_error" in r:
        SKIPPED.append("dbfs/list /mnt (HTTP 404: no mounts, normal for Unity Catalog-only workspaces)" if r["_error"] == 404
                       else f"dbfs/list /mnt (HTTP {r['_error']})")
        return out
    for f in r.get("files", []):
        if f.get("is_dir"):
            m = Asset("DBFS Mount", f["path"], "", "OneLake shortcut / abfss:// path", hours=1.0)
            m.meta = {"mount": f["path"]}
            m.add("MOUNT-REPLACE", 10, 0, "Replace the mount with a shortcut; update every /mnt path in code")
            out.append(m)
    return out


COLLECTORS = dict(notebooks=collect_notebooks, jobs=collect_jobs, clusters=collect_clusters,
                  warehouses=collect_warehouses, pipelines=collect_pipelines, uc=collect_uc,
                  models=collect_models, secrets=collect_secrets, dashboards=collect_dashboards, repos=collect_repos,
                  functions=collect_functions, permissions=collect_permissions, queries=collect_queries,
                  alerts=collect_alerts, libraries=collect_libraries, connections=collect_connections,
                  credentials=collect_credentials, mounts=collect_mounts)


# --------------------------------------------------------------------------
# 4. OFFLINE MODE - scan exported notebooks (.py .sql .scala .r .ipynb)
# --------------------------------------------------------------------------
LANG = {".py": "PYTHON", ".sql": "SQL", ".scala": "SCALA", ".r": "R", ".ipynb": "PYTHON"}


def collect_offline(root):
    out = []
    for p in Path(root).rglob("*"):
        if p.suffix.lower() not in LANG or not p.is_file():
            continue
        text = p.read_text("utf-8", "ignore")
        if p.suffix.lower() == ".ipynb":
            try:
                nb = json.loads(text)
                text = "\n".join("".join(cell.get("source", [])) for cell in nb.get("cells", []))
            except Exception:
                continue
        n = Asset("Notebook", p.name, str(p), "Fabric Notebook", hours=0.25 + (text.count("\n") + 1) / 1000)
        scan_code(n, text, LANG[p.suffix.lower()])
        out.append(n)
    return out


# --------------------------------------------------------------------------
# 5. SCORING + REPORT
# --------------------------------------------------------------------------
def summarize(assets):
    tot_h = sum(max(a.hours, 0.1) for a in assets) or 1
    overall = round(sum(a.score * max(a.hours, 0.1) for a in assets) / tot_h) if assets else 0
    by_type = defaultdict(list)
    for a in assets:
        by_type[a.type].append(a)
    rows = []
    for t, L in sorted(by_type.items()):
        b = Counter(x.bucket for x in L)
        rows.append(dict(type=t, count=len(L), avg=round(sum(x.score for x in L) / len(L)),
                         compatible=b["Compatible"], partial=b["Partial"], manual=b["Manual"], unsupported=b["Unsupported"],
                         hours=round(sum(x.hours for x in L), 1)))
    rules = defaultdict(lambda: dict(assets=0, hours=0.0, advice=""))
    for a in assets:
        for f in a.findings:
            r = rules[f["id"]]
            r["assets"] += 1
            r["hours"] += f["hours"]
            r["advice"] = f["advice"]
    top = sorted(rules.items(), key=lambda kv: -kv[1]["hours"])
    b = Counter(x.bucket for x in assets)
    return dict(overall=overall, total=len(assets), compatible=b["Compatible"], partial=b["Partial"],
                manual=b["Manual"], unsupported=b["Unsupported"],
                hours=round(sum(x.hours for x in assets), 1), by_type=rows,
                top_findings=[dict(v, id=k, hours=round(v["hours"], 1)) for k, v in top])


def write_outputs(assets, S, out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "assets.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["type", "name", "location", "fabric_target", "score", "bucket", "est_hours", "findings"])
        for a in sorted(assets, key=lambda x: x.score):
            w.writerow([a.type, a.name, a.location, a.target, a.score, a.bucket, round(a.hours, 1),
                        "; ".join(f["id"] for f in a.findings)])
    (out / "assessment.json").write_text(json.dumps(dict(summary=S, skipped=SKIPPED,
        assets=[dict(type=a.type, name=a.name, location=a.location, target=a.target, score=a.score,
                     bucket=a.bucket, hours=round(a.hours, 1), findings=a.findings, meta=a.meta) for a in assets]), indent=2), "utf-8")
    edges = [{"from": f"{a.type}:{a.name}", "rel": r, "to": t} for a in assets for r, t in a.deps]
    (out / "dependencies.json").write_text(json.dumps(edges, indent=2), "utf-8")
    e = html.escape
    color = {"Compatible": "#1a7f37", "Partial": "#b7791f", "Manual": "#c0392b", "Unsupported": "#6b21a8"}
    trows = "".join(f"<tr><td>{e(r['type'])}</td><td>{r['count']}</td><td>{r['avg']}</td><td>{r['compatible']}</td>"
                    f"<td>{r['partial']}</td><td>{r['manual']}</td><td>{r['unsupported']}</td><td>{r['hours']}</td></tr>" for r in S["by_type"])
    frows = "".join(f"<tr><td>{e(f['id'])}</td><td>{f['assets']}</td><td>{f['hours']}</td><td>{e(f['advice'])}</td></tr>"
                    for f in S["top_findings"][:25])
    hard = [a for a in sorted(assets, key=lambda x: x.score) if a.bucket != "Compatible"][:200]
    hrows = "".join(f"<tr><td>{e(a.type)}</td><td>{e(a.name)}</td><td style='color:{color[a.bucket]}'><b>{a.score}</b> {a.bucket}</td>"
                    f"<td>{round(a.hours,1)}</td><td>{e(a.target)}</td><td>{e(', '.join(f['id'] for f in a.findings))}</td></tr>" for a in hard)
    cov = "".join(f"<tr><td>{n}<td>{e(cat)}<td>{e(st)}<td>{e(how)}</tr>" for n, cat, st, how in COVERAGE)
    skipped = "".join(f"<li>{e(s)}</li>" for s in SKIPPED) or "<li>none</li>"
    (out / "report.html").write_text(f"""<!doctype html><meta charset=utf-8><title>Databricks to Fabric - Pre-Migration Report</title>
<style>body{{font:14px system-ui;margin:32px;color:#222}}table{{border-collapse:collapse;margin:12px 0;width:100%}}
td,th{{border:1px solid #ddd;padding:6px 9px;text-align:left}}th{{background:#f3f4f6}}
.c{{display:inline-block;margin:0 14px 14px 0;padding:14px 20px;border-radius:10px;background:#f3f4f6}}
.c b{{font-size:28px;display:block}}</style>
<h1>Databricks &rarr; Fabric Pre-Migration Report</h1>
<div><span class=c><b>{S['overall']}/100</b>Readiness score</span><span class=c><b>{S['total']}</b>Assets</span>
<span class=c style='color:#1a7f37'><b>{S['compatible']}</b>Compatible</span><span class=c style='color:#b7791f'><b>{S['partial']}</b>Partial (convert + configure)</span>
<span class=c style='color:#c0392b'><b>{S['manual']}</b>Manual intervention</span><span class=c style='color:#6b21a8'><b>{S['unsupported']}</b>Unsupported</span><span class=c><b>{S['hours']}</b>Est. effort (hrs)</span></div>
<p>Score: 100 minus penalties per finding. Compatible &ge;80, Partial 50-79, Manual &lt;50, Unsupported = no Fabric equivalent. Overall = effort-weighted average. Hours are planning estimates - tune the RULES table.</p>
<h2>By asset type</h2><table><tr><th>Type<th>Count<th>Avg score<th>Compatible<th>Partial<th>Manual<th>Unsupported<th>Hours</tr>{trows}</table>
<h2>Top migration blockers (by effort)</h2><table><tr><th>Rule<th>Assets<th>Hours<th>What to do in Fabric</tr>{frows}</table>
<h2>Assets needing assisted / manual work</h2><table><tr><th>Type<th>Name<th>Score<th>Hours<th>Fabric target<th>Findings</tr>{hrows}</table>
<h2>Coverage vs Databricks asset inventory</h2><table><tr><th>#<th>Asset category<th>Coverage<th>How</tr>{cov}</table>
<h2>Not scanned (permissions / not enabled)</h2><ul>{skipped}</ul>
<p>Not covered: hive_metastore tables, legacy SQL dashboards, Genie spaces, vector search, DBFS root files, job-run history, notebook/job/cluster ACLs. Job and notebook dependency edges are in dependencies.json.</p>""", "utf-8")


def main():
    ap = argparse.ArgumentParser(description="Databricks -> Fabric pre-migration assessment")
    ap.add_argument("--host", default=os.getenv("DATABRICKS_HOST"))
    ap.add_argument("--token", default=os.getenv("DATABRICKS_TOKEN"))
    ap.add_argument("--path", help="offline: folder of exported notebooks")
    ap.add_argument("--out", default="assessment_out")
    ap.add_argument("--only", help=f"comma list of: {','.join(COLLECTORS)}")
    ap.add_argument("--catalogs", type=lambda s: set(s.split(",")), help="limit Unity Catalog to these catalogs")
    ap.add_argument("--max-notebooks", type=int, default=2000)
    ap.add_argument("--skip-repos", action="store_true")
    a = ap.parse_args()

    if a.path:
        assets = collect_offline(a.path)
    else:
        if not (a.host and a.token):
            sys.exit("Need --host and --token (or env vars) or --path for offline mode")
        c = Dbx(a.host, a.token)
        names = a.only.split(",") if a.only else list(COLLECTORS)
        assets = []
        for n in names:
            print(f"collecting {n} ...", flush=True)
            try:
                got = COLLECTORS[n](c, a)
            except Exception as ex:
                SKIPPED.append(f"{n}: {ex}")
                got = []
            print(f"  {len(got)} assets")
            assets += got
    S = summarize(assets)
    write_outputs(assets, S, a.out)
    print(f"\nReadiness {S['overall']}/100 | {S['total']} assets | Compatible {S['compatible']} / Partial {S['partial']} / "
          f"Manual {S['manual']} / Unsupported {S['unsupported']} | ~{S['hours']} hrs\nReport: {Path(a.out) / 'report.html'}")


if __name__ == "__main__":
    main()
