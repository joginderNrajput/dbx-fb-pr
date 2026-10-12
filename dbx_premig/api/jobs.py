"""In-memory run store (single instance). Finished runs expire after a TTL -> 410 Gone."""

from __future__ import annotations

import shutil
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

__all__ = ["Run", "RunConflict", "RunExpired", "RunStore"]


class RunConflict(Exception):
    """A run for the same (organization_id, job_id) is still queued or running."""


class RunExpired(Exception):
    """The run existed but its TTL has passed (its files are deleted)."""


@dataclass
class Run:
    run_id: str
    organization_id: str
    job_id: str
    mode: str
    folder: Path
    created_at: str = field(default_factory=lambda: _now())
    status: str = "queued"
    finished_at: str | None = None
    finished_mono: float | None = None
    error: str | None = None
    discovery_workbook: Path | None = None
    assessment_workbook: Path | None = None
    discovery: dict[str, Any] | None = None
    assessment: dict[str, Any] | None = None
    persisted: dict[str, Any] | None = None

    @property
    def active(self) -> bool:
        return self.status in {"queued", "running"}


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


class RunStore:
    def __init__(self, root: Path, ttl_s: int) -> None:
        self.root = root
        self.ttl_s = ttl_s
        self._runs: dict[str, Run] = {}
        self._expired: set[str] = set()
        self._lock = threading.Lock()

    def create(self, organization_id: str, job_id: str, mode: str) -> Run:
        with self._lock:
            self._sweep()
            for run in self._runs.values():
                if run.active and (run.organization_id, run.job_id) == (organization_id, job_id):
                    raise RunConflict(run.run_id)
            run_id = uuid.uuid4().hex
            run = Run(run_id, organization_id, job_id, mode, self.root / run_id)
            run.folder.mkdir(parents=True, exist_ok=True)
            self._runs[run_id] = run
            return run

    def get(self, run_id: str) -> Run | None:
        with self._lock:
            self._sweep()
            if run_id in self._expired:
                raise RunExpired(run_id)
            return self._runs.get(run_id)

    def finish(self, run: Run, status: str, error: str | None = None) -> None:
        with self._lock:
            run.status = status
            run.error = error
            run.finished_at = _now()
            run.finished_mono = time.monotonic()

    def _sweep(self) -> None:
        now = time.monotonic()
        for run_id, run in list(self._runs.items()):
            if run.finished_mono is not None and now - run.finished_mono > self.ttl_s:
                shutil.rmtree(run.folder, ignore_errors=True)
                del self._runs[run_id]
                self._expired.add(run_id)
