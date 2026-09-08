"""Observable file/network boundary for the isolated worker.

This is a process-local guard used together with a separate worker directory.
It records every denied attempt so E1 can distinguish an exercised boundary
from a claim based only on imports or monkey-patching.
"""
from __future__ import annotations

import json
import pathlib
import socket
from dataclasses import dataclass, field
from urllib.parse import urlparse


class BoundaryViolation(PermissionError):
    pass


@dataclass
class BoundaryAudit:
    file_attempts: list[dict] = field(default_factory=list)
    network_attempts: list[dict] = field(default_factory=list)


class PathBoundary:
    def __init__(self, writable_root: pathlib.Path, readable_roots: list[pathlib.Path], blocked_roots: list[pathlib.Path], audit: BoundaryAudit | None = None):
        self.writable_root = writable_root.resolve()
        self.readable_roots = [p.resolve() for p in readable_roots]
        self.blocked_roots = [p.resolve() for p in blocked_roots]
        self.audit = audit or BoundaryAudit()

    def _inside(self, path: pathlib.Path, root: pathlib.Path) -> bool:
        try:
            path.resolve().relative_to(root)
            return True
        except ValueError:
            return False

    def read_bytes(self, path: pathlib.Path) -> bytes:
        resolved = path.resolve()
        allowed = any(self._inside(resolved, root) for root in self.readable_roots + [self.writable_root])
        blocked = any(self._inside(resolved, root) for root in self.blocked_roots)
        attempt = {"operation": "read", "path": str(resolved), "allowed": bool(allowed and not blocked)}
        self.audit.file_attempts.append(attempt)
        if not allowed or blocked:
            raise BoundaryViolation(f"read blocked: {resolved}")
        return resolved.read_bytes()

    def write_bytes(self, path: pathlib.Path, data: bytes) -> None:
        resolved = path.resolve()
        allowed = self._inside(resolved, self.writable_root)
        attempt = {"operation": "write", "path": str(resolved), "allowed": allowed, "bytes": len(data)}
        self.audit.file_attempts.append(attempt)
        if not allowed:
            raise BoundaryViolation(f"write blocked: {resolved}")
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_bytes(data)

    def read_json(self, path: pathlib.Path) -> dict:
        return json.loads(self.read_bytes(path).decode("utf-8"))


class NetworkBoundary:
    def __init__(self, allowed_hosts: set[str] | None = None, allowed_paths: set[str] | None = None, audit: BoundaryAudit | None = None):
        self.allowed_hosts = {host.lower() for host in (allowed_hosts or set())}
        self.allowed_paths = set(allowed_paths or set())
        self.audit = audit or BoundaryAudit()

    def check(self, url: str) -> None:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        allowed = host in self.allowed_hosts and (not self.allowed_paths or parsed.path in self.allowed_paths)
        attempt = {"url": url, "host": host, "path": parsed.path, "allowed": allowed}
        self.audit.network_attempts.append(attempt)
        if not allowed:
            raise BoundaryViolation(f"network blocked: {url}")

    def resolve_for_probe(self, host: str) -> None:
        """Perform a real DNS/socket boundary probe without connecting to a service."""
        self.check(f"https://{host}/")
        socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)

