"""Read-only Databricks REST client (standard library only).

This is the live half of the reader stage: it only issues GETs against the workspace (plus,
for service-principal auth, the OAuth token request). It never creates, changes or runs
anything. Responses are untrusted input; callers get plain dicts.

Authentication, first match wins:
1. explicit settings / CLI flags (``host`` + ``token``, or ``client_id`` + ``client_secret``)
2. ``DATABRICKS_HOST`` / ``DATABRICKS_TOKEN`` / ``DATABRICKS_CLIENT_ID`` / ``..._SECRET``
3. a profile in ``~/.databrickscfg`` (``--profile``, default ``DEFAULT``)

Tokens are never logged, echoed or put in an error message.
"""

from __future__ import annotations

import base64
import configparser
import json
import os
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from dbx_premig.config import Settings
from dbx_premig.errors import ConfigError, ConnectionFailedError
from dbx_premig.logging import get_logger
from dbx_premig.version import APP_VERSION, DIST_NAME

__all__ = [
    "ApiClient",
    "Credentials",
    "DatabricksClient",
    "EndpointUnavailable",
    "paged",
    "resolve_credentials",
]

log = get_logger("client")


class EndpointUnavailable(Exception):
    """An endpoint answered 4xx (no permission, feature not enabled) or kept failing."""

    def __init__(self, path: str, status: int | str) -> None:
        super().__init__(f"{path} (HTTP {status})")
        self.path = path
        self.status = status


class ApiClient(Protocol):
    """What the collector needs; tests provide a fake."""

    host: str

    def get(self, endpoint: str, /, **params: Any) -> dict[str, Any]: ...


@dataclass(frozen=True)
class Credentials:
    host: str
    token: str | None = None
    client_id: str | None = None
    client_secret: str | None = None
    source: str = "settings"

    @property
    def auth_kind(self) -> str:
        return "OAuth service principal" if self.client_id else "Personal access token"


def _read_profile(profile: str | None) -> dict[str, str]:
    cfg_path = Path(os.environ.get("DATABRICKS_CONFIG_FILE", "~/.databrickscfg")).expanduser()
    if not cfg_path.is_file():
        if profile:
            raise ConfigError(f"Profile {profile} requested but {cfg_path.name} was not found.")
        return {}
    # default_section is renamed so [DEFAULT] is an ordinary profile, not inherited by others.
    parser = configparser.ConfigParser(default_section="__dbxf_no_default__")
    try:
        parser.read(cfg_path, encoding="utf-8")
    except configparser.Error as exc:
        raise ConfigError(f"{cfg_path.name} could not be parsed.") from exc
    name = profile or "DEFAULT"
    if not parser.has_section(name):
        if profile:
            raise ConfigError(f"Profile {name} is not defined in {cfg_path.name}.")
        return {}
    section = parser[name]
    return {k: v for k, v in section.items() if v}


def resolve_credentials(settings: Settings) -> Credentials:
    """Work out host and secret from settings, the environment or ~/.databrickscfg.

    Explicit settings (CLI flags / DBXF_*) always win. With ``--profile`` the rest comes from
    that profile only; otherwise from DATABRICKS_* variables, then the DEFAULT profile.
    """
    explicit = {
        "host": settings.host,
        "token": settings.token.get_secret_value() if settings.token else None,
        "client_id": settings.client_id,
        "client_secret": (
            settings.client_secret.get_secret_value() if settings.client_secret else None
        ),
    }
    if settings.profile:
        fallback = _read_profile(settings.profile)
        source = f"profile {settings.profile}"
    else:
        env = os.environ
        fallback = {
            "host": env.get("DATABRICKS_HOST", ""),
            "token": env.get("DATABRICKS_TOKEN", ""),
            "client_id": env.get("DATABRICKS_CLIENT_ID", ""),
            "client_secret": env.get("DATABRICKS_CLIENT_SECRET", ""),
        }
        source = "settings / environment"
        merged = {k: explicit[k] or fallback.get(k) for k in explicit}
        if not (merged["host"] and (merged["token"] or merged["client_id"])):
            profile = _read_profile(None)
            if profile:
                fallback = {k: fallback.get(k) or profile.get(k, "") for k in explicit}
                source = "profile DEFAULT"
    values = {k: explicit[k] or fallback.get(k) or None for k in explicit}
    host = values["host"]
    if not host:
        raise ConfigError("No Databricks workspace URL: pass --host or set DATABRICKS_HOST.")
    host = host.strip().rstrip("/")
    if not host.startswith(("https://", "http://")):
        host = "https://" + host
    token, client_id, secret = values["token"], values["client_id"], values["client_secret"]
    if not token and not (client_id and secret):
        raise ConfigError(
            "No Databricks credentials: pass --token (personal access token) or "
            "--client-id/--client-secret, or set DATABRICKS_TOKEN."
        )
    if token:
        return Credentials(host, token, None, None, source)
    return Credentials(host, None, client_id, secret, source)


class DatabricksClient:
    """Read-only GET client with retries, back-off and OAuth M2M support."""

    def __init__(self, credentials: Credentials, settings: Settings) -> None:
        self.host = credentials.host
        self._creds = credentials
        self._settings = settings
        self._ssl = ssl.create_default_context()
        if not settings.verify_tls:
            self._ssl.check_hostname = False
            self._ssl.verify_mode = ssl.CERT_NONE
        self._bearer: str | None = credentials.token
        self.calls = 0

    # -------------------------------------------------------------- auth
    def _oauth_token(self) -> str:
        assert self._creds.client_id and self._creds.client_secret
        basic = base64.b64encode(
            f"{self._creds.client_id}:{self._creds.client_secret}".encode()
        ).decode()
        body = urllib.parse.urlencode({"grant_type": "client_credentials", "scope": "all-apis"})
        req = urllib.request.Request(
            self.host + "/oidc/v1/token",
            data=body.encode(),
            headers={
                "Authorization": f"Basic {basic}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(
                req, timeout=self._settings.request_timeout_s, context=self._ssl
            ) as resp:
                data = json.loads(resp.read() or b"{}")
        except urllib.error.HTTPError as exc:
            raise ConnectionFailedError(
                f"OAuth token request to the workspace failed (HTTP {exc.code}); "
                "check the service principal's client id and secret."
            ) from None
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise ConnectionFailedError(
                f"Cannot reach {self.host} for an OAuth token ({type(exc).__name__})."
            ) from None
        token = data.get("access_token")
        if not isinstance(token, str):
            raise ConnectionFailedError("The OAuth token response held no access token.")
        return token

    def _headers(self) -> dict[str, str]:
        if self._bearer is None:
            self._bearer = self._oauth_token()
        return {
            "Authorization": f"Bearer {self._bearer}",
            "Accept": "application/json",
            "User-Agent": f"{DIST_NAME}/{APP_VERSION}",
        }

    # -------------------------------------------------------------- GET
    def get(self, endpoint: str, /, **params: Any) -> dict[str, Any]:
        """GET ``endpoint`` and return the JSON object. Raises EndpointUnavailable on 4xx."""
        path = endpoint
        query = {k: v for k, v in params.items() if v not in (None, "")}
        url = self.host + path + ("?" + urllib.parse.urlencode(query, doseq=True) if query else "")
        last: int | str = "no response"
        for attempt in range(self._settings.max_retries + 1):
            self.calls += 1
            try:
                req = urllib.request.Request(url, headers=self._headers(), method="GET")
                with urllib.request.urlopen(
                    req, timeout=self._settings.request_timeout_s, context=self._ssl
                ) as resp:
                    payload = resp.read()
                data = json.loads(payload or b"{}")
                return data if isinstance(data, dict) else {"_value": data}
            except urllib.error.HTTPError as exc:
                last = exc.code
                exc.close()
                if exc.code == 401:
                    raise ConnectionFailedError(
                        f"The workspace {self.host} rejected the credentials (HTTP 401)."
                    ) from None
                if exc.code == 429 or exc.code >= 500:
                    self._sleep(attempt)
                    continue
                raise EndpointUnavailable(path, exc.code) from None
            except ValueError:
                raise EndpointUnavailable(path, "invalid JSON") from None
            except (urllib.error.URLError, OSError) as exc:
                last = type(exc).__name__
                if attempt == 0 and self.calls == 1:
                    # The very first call cannot connect at all: fail fast with a clear message.
                    raise ConnectionFailedError(
                        f"Cannot connect to {self.host} ({type(exc).__name__}). Check the URL, "
                        "network access and proxy settings."
                    ) from None
                self._sleep(attempt)
        raise EndpointUnavailable(path, f"{last}, retries exhausted")

    def _sleep(self, attempt: int) -> None:
        time.sleep(self._settings.retry_backoff_s * (2**attempt))


def paged(
    client: ApiClient,
    endpoint: str,
    key: str,
    /,
    *,
    token_param: str = "page_token",
    **params: Any,
) -> Iterator[dict[str, Any]]:
    """Iterate a list endpoint that pages with ``next_page_token`` (or ``has_more``/offset)."""
    token: str | None = None
    seen_tokens: set[str] = set()
    while True:
        data = client.get(endpoint, **{token_param: token}, **params)
        items = data.get(key) or []
        for item in items:
            if isinstance(item, dict):
                yield item
        token = data.get("next_page_token")
        if not token or token in seen_tokens or data.get("has_more") is False:
            return
        seen_tokens.add(token)
