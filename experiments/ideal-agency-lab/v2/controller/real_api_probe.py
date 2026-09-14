"""P0 real-provider probe for the handoff.

This module deliberately stops before the worker, AgencyLoop, production
database, Bot sink, or any enterprise snapshot.  It exercises only the
trusted controller's read-only production-config resolver and the experiment
HTTP gateway.
"""
from __future__ import annotations

import json
import pathlib
import time
from typing import Any

from controller.boundary import NetworkBoundary
from controller.provider_config import build_text_gateway, resolve_production_image_binding, resolve_production_text_binding


TRANSIENT_HTTP = {408, 425, 429, 500, 502, 503, 504}


def _safe_content(value: Any, limit: int = 4000) -> dict[str, Any]:
    encoded = json.dumps(value, ensure_ascii=False, default=str)
    return {"text": encoded[:limit], "truncated": len(encoded) > limit, "sha256": __import__("hashlib").sha256(encoded.encode("utf-8")).hexdigest()}


def _is_transient(response: Any) -> bool:
    status = getattr(response, "http_status", None)
    if status in TRANSIENT_HTTP:
        return True
    error = str(getattr(response, "error", "") or "")
    return error in {"TimeoutError", "URLError", "ConnectionError", "ConnectionResetError", "BrokenPipeError", "OSError"}


def run_provider_probe(*, run_root: pathlib.Path, production_root: pathlib.Path) -> dict[str, Any]:
    effective_path = run_root / "effective-provider.json"
    probe_path = run_root / "provider-probe.json"
    if effective_path.exists() or probe_path.exists():
        return {"status": "refused_existing_evidence", "reason": "provider probe evidence is immutable; use a fresh run directory", "effective_provider": str(effective_path), "probe": str(probe_path)}

    binding, effective = resolve_production_text_binding(production_root=production_root)
    image_binding, image_effective = resolve_production_image_binding(production_root=production_root)
    effective["probe_scope"] = "P0_sample_generation_technical_only"
    effective["no_enterprise_data"] = True
    effective["no_worker_or_bot"] = True
    effective["availability"] = "not_attempted" if not binding.ready else "attempt_pending"
    effective["image_binding"] = image_effective
    effective_path.write_text(json.dumps(effective, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (run_root / "effective-image-provider.json").write_text(json.dumps(image_effective, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    result: dict[str, Any] = {
        "schemaVersion": "provider-probe-v1",
        "status": "not_started",
        "scope": "P0_sample_generation_technical_only",
        "provider_calls": 0,
        "retry_limit": 1,
        "credential_value_recorded": False,
        "credential_in_worker": False,
        "worker_or_bot_invoked": False,
        "production_state_written": False,
        "effective_provider": str(effective_path),
        "effective_image_provider": str(run_root / "effective-image-provider.json"),
        "image_binding": image_binding.safe_record(),
        "attempts": [],
    }
    if not binding.ready:
        result.update({"status": "incomplete", "reason": "effective production provider binding is incomplete", "binding": binding.safe_record()})
        probe_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return result

    from urllib.parse import urlsplit
    parsed = urlsplit(str(binding.endpoint))
    boundary = NetworkBoundary({parsed.hostname or ""}, {parsed.path})
    gateway = build_text_gateway(binding, network_boundary=boundary)
    # This prompt is intentionally generic and contains no enterprise facts,
    # user identity, relationship state, scenario text, or hidden oracle.
    prompt = {
        "system": {"role": "technical probe", "instruction": "Return a short acknowledgement that the API channel is reachable."},
        "probe": "channel_reachability",
        "response_format": "plain_text",
    }
    started = time.perf_counter()
    max_attempts = 2
    for attempt in range(1, max_attempts + 1):
        response = gateway.complete(prompt, attempt=attempt)
        row = {
            "attempt": attempt,
            "request_id": response.request_id,
            "model": response.model,
            "http_status": response.http_status,
            "finish_reason": response.finish_reason,
            "usage": response.usage,
            "latency_ms": response.latency_ms,
            "error": response.error,
            "response": _safe_content(response.content) if not response.error else None,
            "network_boundary": {"allowed_hosts": sorted(boundary.allowed_hosts), "allowed_paths": sorted(boundary.allowed_paths)},
        }
        result["attempts"].append(row)
        result["provider_calls"] = attempt
        if not response.error:
            result.update({"status": "passed", "reason": "real provider returned a response", "model": response.model, "http_status": response.http_status, "finish_reason": response.finish_reason, "usage": response.usage, "latency_ms": response.latency_ms, "response": _safe_content(response.content), "total_elapsed_ms": int((time.perf_counter() - started) * 1000)})
            effective["availability"] = "probe_succeeded"
            effective["probe_request_id"] = response.request_id
            effective["probe_http_status"] = response.http_status
            break
        if attempt >= max_attempts or not _is_transient(response):
            result.update({"status": "failed", "reason": "real provider request failed; no channel switch or further retry", "error": response.error, "http_status": response.http_status, "total_elapsed_ms": int((time.perf_counter() - started) * 1000)})
            effective["availability"] = "probe_failed"
            break
    effective_path.write_text(json.dumps(effective, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    probe_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result

