"""A local fake Databricks workspace: serves the mini fixture through the real REST paths.

Used to test the live client and collector end to end (HTTP, paging, auth, errors) without a
real workspace. Paged endpoints return one item per page to exercise the paging code.
"""

from __future__ import annotations

import base64
import json
import threading
import urllib.parse
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

FIXTURE = Path(__file__).parent / "fixtures" / "mini" / "snapshot.json"
TOKEN = "dapi-test-token"

Json = dict[str, Any]


def _q(query: dict[str, list[str]], key: str, default: str = "") -> str:
    return query.get(key, [default])[0]


@dataclass
class FakeWorkspace:
    sections: dict[str, list[Json]]
    token: str = TOKEN
    forbidden: set[str] = field(default_factory=set)  # paths answering 403
    flaky: dict[str, int] = field(default_factory=dict)  # path -> number of 500s first
    calls: list[str] = field(default_factory=list)
    methods: set[str] = field(default_factory=set)
    oauth: tuple[str, str] | None = None  # (client_id, secret) accepted on /oidc/v1/token

    @classmethod
    def from_fixture(cls) -> FakeWorkspace:
        data = json.loads(FIXTURE.read_text("utf-8"))
        return cls(sections=data["sections"])

    # ------------------------------------------------------------------ helpers
    def _page(self, items: list[Json], key: str, query: dict[str, list[str]]) -> Json:
        start = int(_q(query, "page_token", "0") or 0)
        out: Json = {key: items[start : start + 1]}
        if start + 1 < len(items):
            out["next_page_token"] = str(start + 1)
        return out

    def _sec(self, name: str) -> list[Json]:
        return self.sections.get(name, [])

    # ------------------------------------------------------------------ routing
    def route(self, path: str, query: dict[str, list[str]]) -> tuple[int, Json]:
        s = self._sec
        if path in self.forbidden:
            return 403, {"error_code": "PERMISSION_DENIED"}
        if self.flaky.get(path, 0) > 0:
            self.flaky[path] -= 1
            return 500, {"error_code": "INTERNAL"}
        if path == "/api/2.0/workspace/list":
            return self._workspace_list(_q(query, "path", "/"))
        if path == "/api/2.0/workspace/export":
            want = _q(query, "path")
            for nb in s("notebooks"):
                if self._ws_path(nb) == want and nb.get("source") is not None:
                    content = base64.b64encode(nb["source"].encode()).decode()
                    return 200, {"content": content, "file_type": "py"}
            return 404, {"error_code": "RESOURCE_DOES_NOT_EXIST"}
        if path == "/api/2.0/repos":
            return 200, self._page(s("repos"), "repos", query)
        if path == "/api/2.1/jobs/list":
            return 200, self._page(s("jobs"), "jobs", query)
        if path == "/api/2.0/pipelines":
            return 200, self._page(
                [{k: v for k, v in p.items() if k != "spec"} for p in s("pipelines")],
                "statuses",
                query,
            )
        if path.startswith("/api/2.0/pipelines/"):
            pid = path.rsplit("/", 1)[-1]
            for p in s("pipelines"):
                if p.get("pipeline_id") == pid:
                    return 200, p
            return 404, {}
        if path == "/api/2.1/clusters/list":
            return 404, {}  # force the 2.0 fallback
        if path == "/api/2.0/clusters/list":
            return 200, {"clusters": s("clusters")}
        if path == "/api/2.0/instance-pools/list":
            return 200, {"instance_pools": s("instance_pools")}
        if path == "/api/2.0/policies/clusters/list":
            return 200, {"policies": s("cluster_policies")}
        if path == "/api/2.0/sql/warehouses":
            return 200, {"warehouses": s("warehouses")}
        if path == "/api/2.1/unity-catalog/metastore_summary":
            return 200, {
                "name": "metastore_westeurope",
                "metastore_id": "11111111-2222",
                "region": "westeurope",
                "cloud": "azure",
            }
        if path == "/api/2.0/preview/scim/v2/Me":
            return 200, {"userName": "ana@contoso.com"}
        if path == "/api/2.1/unity-catalog/catalogs":
            return 200, self._page(s("catalogs"), "catalogs", query)
        if path == "/api/2.1/unity-catalog/schemas":
            cat = _q(query, "catalog_name")
            return 200, self._page(
                [x for x in s("schemas") if x.get("catalog_name") == cat], "schemas", query
            )
        if path in {
            "/api/2.1/unity-catalog/tables",
            "/api/2.1/unity-catalog/volumes",
            "/api/2.1/unity-catalog/functions",
        }:
            kind = path.rsplit("/", 1)[-1]
            cat, sch = _q(query, "catalog_name"), _q(query, "schema_name")
            items = [
                x for x in s(kind) if x.get("catalog_name") == cat and x.get("schema_name") == sch
            ]
            if kind == "functions":
                items = [{k: v for k, v in f.items() if k != "input_params"} for f in items]
            return 200, self._page(items, kind, query)
        if path.startswith("/api/2.1/unity-catalog/functions/"):
            full = urllib.parse.unquote(path.rsplit("/", 1)[-1])
            for f in s("functions"):
                if f.get("full_name") == full:
                    return 200, f
            return 404, {}
        if path == "/api/2.1/unity-catalog/external-locations":
            return 200, self._page(s("external_locations"), "external_locations", query)
        if path == "/api/2.1/unity-catalog/storage-credentials":
            return 200, self._page(s("storage_credentials"), "storage_credentials", query)
        if path == "/api/2.1/unity-catalog/connections":
            return 200, self._page(s("connections"), "connections", query)
        if path.startswith("/api/2.1/unity-catalog/permissions/"):
            _, kind, name = path.rsplit("/", 2)
            name = urllib.parse.unquote(name)
            pas = [
                {k: v for k, v in g.items() if k in {"principal", "privileges"}}
                for g in s("grants")
                if g.get("securable_type") == kind and g.get("securable") == name
            ]
            return 200, {"privilege_assignments": pas}
        if path == "/api/2.0/sql/queries":
            return 200, self._page(s("queries"), "results", query)
        if path == "/api/2.0/lakeview/dashboards":
            items = [
                {k: v for k, v in d.items() if k != "_kind"}
                for d in s("dashboards")
                if d.get("_kind") != "Legacy SQL"
            ]
            return 200, self._page(items, "dashboards", query)
        if path == "/api/2.0/preview/sql/dashboards":
            items = [
                {k: v for k, v in d.items() if k != "_kind"}
                for d in s("dashboards")
                if d.get("_kind") == "Legacy SQL"
            ]
            return 200, {
                "results": items if _q(query, "page", "1") == "1" else [],
                "count": len(items),
            }
        if path == "/api/2.0/sql/alerts":
            return 200, self._page(s("alerts"), "results", query)
        if path == "/api/2.0/alerts":
            return 200, self._page(s("alerts"), "alerts", query)  # duplicates are de-duplicated
        if path == "/api/2.1/unity-catalog/models":
            return 200, self._page(
                [m for m in s("models") if "_registry" not in m], "registered_models", query
            )
        if path == "/api/2.0/mlflow/registered-models/search":
            items = [
                {k: v for k, v in m.items() if k != "_registry"}
                for m in s("models")
                if m.get("_registry") == "workspace"
            ]
            return 200, self._page(items, "registered_models", query)
        if path == "/api/2.0/serving-endpoints":
            return 200, {"endpoints": s("serving_endpoints")}
        if path == "/api/2.0/mlflow/experiments/search":
            return 200, self._page(s("experiments"), "experiments", query)
        if path == "/api/2.0/libraries/all-cluster-statuses":
            return 200, {"statuses": s("library_statuses")}
        if path == "/api/2.0/secrets/scopes/list":
            return 200, {
                "scopes": [{k: v for k, v in x.items() if k != "keys"} for x in s("secret_scopes")]
            }
        if path == "/api/2.0/secrets/list":
            scope = _q(query, "scope")
            for x in s("secret_scopes"):
                if x["name"] == scope:
                    return 200, {"secrets": [{"key": k} for k in x["keys"]]}
            return 404, {}
        if path == "/api/2.0/dbfs/list":
            return 200, {"files": [{"path": m["path"], "is_dir": True} for m in s("mounts")]}
        if path.startswith("/api/2.0/preview/scim/v2/"):
            resource = path.rsplit("/", 1)[-1]
            key = {"Users": "users", "Groups": "groups", "ServicePrincipals": "service_principals"}[
                resource
            ]
            items = s(key)
            start = int(_q(query, "startIndex", "1"))
            page = items[start - 1 : start]  # one per page
            return 200, {"Resources": page, "totalResults": len(items)}
        return 404, {"error_code": "ENDPOINT_NOT_FOUND"}

    @staticmethod
    def _ws_path(nb: Json) -> str:
        return str(nb["path"])

    def _workspace_list(self, folder: str) -> tuple[int, Json]:
        folder = folder.rstrip("/") or "/"
        objects: dict[str, Json] = {}
        for nb in self._sec("notebooks"):
            path = self._ws_path(nb)
            if not path.startswith(folder if folder.endswith("/") else folder + "/"):
                continue
            rest = path[len(folder.rstrip("/")) + 1 :]
            head = rest.split("/", 1)[0]
            full = folder.rstrip("/") + "/" + head
            if "/" in rest:
                objects[full] = {"path": full, "object_type": "DIRECTORY"}
            else:
                objects[full] = {
                    "path": full,
                    "object_type": "NOTEBOOK",
                    "language": nb.get("language"),
                    "modified_at": nb.get("modified_at"),
                }
        if folder == "/":
            objects["/Shared/init.sh"] = {
                "path": "/Shared/init.sh",
                "object_type": "FILE",
                "size": 10,
            }
        return 200, {"objects": list(objects.values())}


class _Handler(BaseHTTPRequestHandler):
    server: _Server

    def log_message(self, *args: Any) -> None:  # silence
        pass

    def _send(self, status: int, body: Json) -> None:
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:
        ws = self.server.workspace
        ws.methods.add("GET")
        url = urllib.parse.urlparse(self.path)
        ws.calls.append(url.path)
        auth = self.headers.get("Authorization", "")
        if auth not in {f"Bearer {ws.token}", "Bearer oauth-access-token"}:
            self._send(401, {"error_code": "UNAUTHENTICATED"})
            return
        status, body = ws.route(url.path, urllib.parse.parse_qs(url.query))
        self._send(status, body)

    def do_POST(self) -> None:
        ws = self.server.workspace
        ws.methods.add("POST")
        if self.path == "/oidc/v1/token" and ws.oauth:
            expected = base64.b64encode(f"{ws.oauth[0]}:{ws.oauth[1]}".encode()).decode()
            if self.headers.get("Authorization") == f"Basic {expected}":
                self._send(200, {"access_token": "oauth-access-token", "expires_in": 3600})
                return
            self._send(401, {"error": "invalid_client"})
            return
        self._send(405, {})


class _Server(ThreadingHTTPServer):
    workspace: FakeWorkspace


@contextmanager
def serve(workspace: FakeWorkspace) -> Iterator[str]:
    """Run the fake workspace on a free localhost port; yields its base URL."""
    server = _Server(("127.0.0.1", 0), _Handler)
    server.workspace = workspace
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
