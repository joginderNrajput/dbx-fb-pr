"""Error hierarchy and the fixed process exit codes.

The exit codes are a contract that CI pipelines branch on. Never renumber them.

| Code | Meaning                                         |
|------|-------------------------------------------------|
| 0    | success                                         |
| 1    | uncaught internal error (a bug)                 |
| 2    | unsupported file type                           |
| 3    | malformed artifact                              |
| 4    | unsafe archive                                  |
| 5    | catalog or assessment-rules error               |
| 6    | report write error                              |
| 7    | nothing found to analyse                        |
| 8    | invalid discovery workbook / snapshot           |
| 9    | database error                                  |
| 10   | Databricks connection or authentication error   |
| 11   | invalid configuration                           |
"""

from __future__ import annotations

__all__ = [
    "ArchiveSafetyError",
    "CatalogError",
    "ConfigError",
    "ConnectionFailedError",
    "DatabaseError",
    "DiscoveryError",
    "InvalidSnapshotError",
    "InvalidWorkbookError",
    "MalformedArtifactError",
    "NothingFoundError",
    "ReportWriteError",
    "RulesError",
    "UnsupportedFileError",
]


class DiscoveryError(Exception):
    """Base class. `message` names the file or setting at fault and never quotes content."""

    exit_code: int = 1

    def __init__(self, message: str, detail: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail


class UnsupportedFileError(DiscoveryError):
    exit_code = 2


class MalformedArtifactError(DiscoveryError):
    exit_code = 3


class ArchiveSafetyError(DiscoveryError):
    exit_code = 4


class CatalogError(DiscoveryError):
    exit_code = 5


class RulesError(CatalogError):
    """The assessment rules file is unreadable or invalid (same exit code as the catalog)."""


class ReportWriteError(DiscoveryError):
    exit_code = 6


class NothingFoundError(DiscoveryError):
    exit_code = 7


class InvalidSnapshotError(DiscoveryError):
    exit_code = 8


class InvalidWorkbookError(InvalidSnapshotError):
    """The file given to ``assess`` is not a readable discovery workbook."""


class DatabaseError(DiscoveryError):
    exit_code = 9


class ConnectionFailedError(DiscoveryError):
    exit_code = 10


class ConfigError(DiscoveryError):
    exit_code = 11
