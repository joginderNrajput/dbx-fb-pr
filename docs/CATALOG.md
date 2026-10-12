# The support catalog

`dbx_premig/catalog/data/features.yaml` is the knowledge base: which Databricks features
need work in Microsoft Fabric, how much, and what to do. It is data, not code.

## Sections

* `asset_targets` — asset type → Fabric target shown on every sheet (*Fabric target*).
* `job_task_types` — job task type → Fabric pipeline activity, and the feature id it raises.
* `features[]` — one entry per feature:

```yaml
- id: AUTOLOADER                 # unique; shown on Findings / Assets
  category: ingestion            # grouping on Findings
  applies: code                  # code = regex over source; structural = emitted by parser.py
  pattern: 'cloudFiles'          # code only: case-insensitive, multi-line regex
  penalty: 18                    # readiness points taken off (see METHODOLOGY.md)
  support: manual                # supported | partial | manual | unsupported
  guidance: No Auto Loader; use a Structured Streaming file source, ...
```

## Changing it

1. Edit the YAML (add a code pattern, tune a penalty, change guidance).
2. `python discovery.py catalog-info` validates it (unique ids, regex compiles, verdicts,
   task-type references).
3. `pytest tests/test_catalog.py` — also checks that every feature id `parser.py` can emit
   exists in the catalog.
4. Re-run a discovery (a saved snapshot is enough: `--input snapshot.json`).

A structural feature needs a matching line in `parser.py`; a code feature needs only the
YAML entry. A feature id the parser emits that the catalog lacks (for example a new job task
type) is not dropped: it is classified `unknown`, adds no penalty, and is listed on the
Warnings sheet so it gets added here.
