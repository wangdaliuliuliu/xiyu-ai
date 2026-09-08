"""Lifecycle records and cleanup for one isolated run."""
from __future__ import annotations

import json
import pathlib
import time
from dataclasses import dataclass

from .boundary import BoundaryAudit, NetworkBoundary, PathBoundary


@dataclass
class WorkerLifecycle:
    run_root: pathlib.Path
    worker_root: pathlib.Path
    audit: BoundaryAudit
    paths: PathBoundary
    network: NetworkBoundary

    @classmethod
    def create(cls, run_root: pathlib.Path, snapshot_root: pathlib.Path, repo_root: pathlib.Path | None = None) -> "WorkerLifecycle":
        worker_root = run_root / "worker"
        worker_root.mkdir(parents=True, exist_ok=True)
        audit = BoundaryAudit()
        repo = repo_root.resolve() if repo_root else run_root.parents[3]
        paths = PathBoundary(worker_root, [snapshot_root], [repo / "src", repo / "config", repo / "index.mjs"], audit)
        network = NetworkBoundary(set(), set(), audit)
        return cls(run_root, worker_root, audit, paths, network)

    def write_audit(self, status: str = "completed") -> pathlib.Path:
        payload = {
            "status": status,
            "production_write_attempts": [a for a in self.audit.file_attempts if a["operation"] == "write" and not a["allowed"]],
            "file_attempts": self.audit.file_attempts,
            "network_attempts": self.audit.network_attempts,
            "processes": [],
            "recorded_at": time.time(),
        }
        path = self.run_root / "isolation.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return path

    def cleanup(self) -> None:
        self.write_audit("completed")
