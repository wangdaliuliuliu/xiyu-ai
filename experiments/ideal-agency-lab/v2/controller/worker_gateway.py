"""Controller-side gateway relay for the qualified WSL worker.

The worker receives only a short-lived relay token and structured prompts.  The
provider binding, including the existing credential, is constructed inside a
separate controller gateway process.  This module deliberately keeps the
relay protocol small and records only non-secret request metadata.
"""
from __future__ import annotations

import hashlib
import http.server
import json
import multiprocessing
import pathlib
import secrets
import threading
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

from controller.boundary import NetworkBoundary
from controller.gateway import ProviderResponse
from controller.provider_config import ProviderBinding, build_text_gateway


MAX_REQUEST_BYTES = 2 * 1024 * 1024
DEEPSEEK_PRICE_BASIS_URL = "https://api-docs.deepseek.com/quick_start/pricing"


@dataclass
class SpendGuard:
    """Fail-closed controller-side spend guard for an explicitly bounded run.

    DeepSeek publishes prices in USD per million tokens.  The guard uses the
    current peak rates and a deliberately conservative CNY/USD ceiling, and
    reserves the worst-case cost of the next request before it reaches the
    provider.  It is a safety ceiling, not a claim about the account ledger.
    """

    max_budget_cny: float
    cny_per_usd_ceiling: float = 10.0
    max_output_tokens: int = 512
    input_cache_hit_usd_per_million: float = 0.014
    input_cache_miss_usd_per_million: float = 0.44
    output_usd_per_million: float = 1.32
    # ``spent_usd`` is reserved for costs calculated from complete provider
    # usage.  It must never include a worst-case reservation merely because a
    # request was allowed.  Unknown-cost requests move their reservation to
    # ``unresolved_reserved_usd`` and remain unavailable to later scheduling.
    spent_usd: float = 0.0
    reserved_usd: float = 0.0
    unresolved_reserved_usd: float = 0.0
    released_reserved_usd: float = 0.0
    provider_calls: int = 0
    budget_rejections: int = 0
    _lock: Any = field(default_factory=threading.Lock, repr=False)

    @property
    def max_budget_usd(self) -> float:
        return max(0.0, float(self.max_budget_cny)) / max(0.01, float(self.cny_per_usd_ceiling))

    def _usage_cost_usd(self, usage: Any) -> float | None:
        if not isinstance(usage, dict):
            return None
        def integer(value: Any) -> int:
            try:
                return max(0, int(value or 0))
            except (TypeError, ValueError):
                return 0
        prompt_tokens = integer(usage.get("prompt_tokens"))
        completion_tokens = integer(usage.get("completion_tokens"))
        details = usage.get("prompt_tokens_details")
        details = details if isinstance(details, dict) else {}
        cache_hit = integer(usage.get("prompt_cache_hit_tokens", details.get("cached_tokens")))
        cache_miss = integer(usage.get("prompt_cache_miss_tokens"))
        if cache_hit + cache_miss > prompt_tokens:
            cache_hit = min(cache_hit, prompt_tokens)
            cache_miss = max(0, prompt_tokens - cache_hit)
        if cache_hit + cache_miss < prompt_tokens:
            cache_miss += prompt_tokens - cache_hit - cache_miss
        return (
            cache_hit * self.input_cache_hit_usd_per_million
            + cache_miss * self.input_cache_miss_usd_per_million
            + completion_tokens * self.output_usd_per_million
        ) / 1_000_000

    def _worst_case_usd(self, provider_payload: bytes) -> float:
        # One byte per token is a conservative upper bound for the request
        # body; the provider's max_tokens bounds the response side.
        input_tokens_upper = max(1, len(provider_payload))
        return (
            input_tokens_upper * self.input_cache_miss_usd_per_million
            + max(1, int(self.max_output_tokens)) * self.output_usd_per_million
        ) / 1_000_000

    def reserve(self, provider_payload: bytes) -> dict[str, Any]:
        worst_case_usd = self._worst_case_usd(provider_payload)
        with self._lock:
            remaining = self.max_budget_usd - self.spent_usd - self.reserved_usd - self.unresolved_reserved_usd
            if worst_case_usd > remaining:
                self.budget_rejections += 1
                return {"allowed": False, "reason": "cost_budget_exhausted", "worst_case_usd": worst_case_usd, "remaining_usd": max(0.0, remaining)}
            self.reserved_usd += worst_case_usd
            return {"allowed": True, "reserved_usd": worst_case_usd, "remaining_usd": max(0.0, remaining - worst_case_usd)}

    def settle(self, reservation: dict[str, Any], response: ProviderResponse, *, provider_call: bool) -> dict[str, Any]:
        reserved = float(reservation.get("reserved_usd", 0.0) or 0.0)
        observed = self._usage_cost_usd(response.usage) if provider_call else 0.0
        usage_complete = bool(provider_call and response.http_status == 200 and observed is not None)
        # Complete usage is settled at the verified token price.  The
        # difference between the worst-case reservation and that estimate is
        # released.  If usage is unknown, the reservation remains pending and
        # continues to consume the budget until an independent billing record
        # resolves it; it is deliberately not called actual spend.
        actual_usage_usd = float(observed) if usage_complete and observed is not None else None
        released_usd = max(0.0, reserved - actual_usage_usd) if actual_usage_usd is not None else 0.0
        unresolved_usd = reserved if provider_call and not usage_complete else 0.0
        with self._lock:
            self.reserved_usd = max(0.0, self.reserved_usd - reserved)
            if actual_usage_usd is not None:
                self.spent_usd += actual_usage_usd
                self.released_reserved_usd += released_usd
            elif unresolved_usd:
                self.unresolved_reserved_usd += unresolved_usd
            if provider_call:
                self.provider_calls += 1
        return {
            "reserved_usd": reserved,
            "usage_status": "complete" if usage_complete else "unknown",
            "actual_usage_usd": actual_usage_usd,
            "actual_usage_cny_at_safety_rate": actual_usage_usd * self.cny_per_usd_ceiling if actual_usage_usd is not None else None,
            "released_reserved_usd": released_usd,
            "released_reserved_cny_at_safety_rate": released_usd * self.cny_per_usd_ceiling,
            "unresolved_reserved_usd": unresolved_usd,
            "unresolved_reserved_cny_at_safety_rate": unresolved_usd * self.cny_per_usd_ceiling,
            "account_billing_amount": None,
        }

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "currency": "CNY",
                "max_budget_cny": float(self.max_budget_cny),
                "cny_per_usd_ceiling": float(self.cny_per_usd_ceiling),
                "max_budget_usd_at_safety_rate": self.max_budget_usd,
                "actual_usage_spent_usd": self.spent_usd,
                "actual_usage_spent_cny_at_safety_rate": self.spent_usd * self.cny_per_usd_ceiling,
                "active_reserved_usd": self.reserved_usd,
                "active_reserved_cny_at_safety_rate": self.reserved_usd * self.cny_per_usd_ceiling,
                "unresolved_reserved_usd": self.unresolved_reserved_usd,
                "unresolved_reserved_cny_at_safety_rate": self.unresolved_reserved_usd * self.cny_per_usd_ceiling,
                "released_reserved_usd": self.released_reserved_usd,
                "released_reserved_cny_at_safety_rate": self.released_reserved_usd * self.cny_per_usd_ceiling,
                "provider_calls": self.provider_calls,
                "budget_rejections": self.budget_rejections,
                "max_output_tokens": int(self.max_output_tokens),
                "price_basis_url": DEEPSEEK_PRICE_BASIS_URL,
                "price_basis": {"input_cache_hit_usd_per_million": self.input_cache_hit_usd_per_million, "input_cache_miss_usd_per_million": self.input_cache_miss_usd_per_million, "output_usd_per_million": self.output_usd_per_million, "rate_class": "peak_conservative"},
            }


def _json_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _response_payload(response: ProviderResponse) -> dict[str, Any]:
    return {
        "request_id": response.request_id,
        "model": response.model,
        "content": response.content,
        "finish_reason": response.finish_reason,
        "usage": response.usage,
        "latency_ms": response.latency_ms,
        "error": response.error,
        "http_status": response.http_status,
    }


class _RelayServer(http.server.ThreadingHTTPServer):
    allow_reuse_address = True


class _ControlGateway:
    """Non-semantic controller response for worker qualification only."""

    def __init__(self, model: str):
        self.model_name = model

    def complete(self, _prompt: dict[str, Any], *, attempt: int = 1) -> ProviderResponse:
        return ProviderResponse(
            request_id=str(uuid.uuid4()), model=self.model_name,
            content={
                "operation": "new", "intention_ref": None, "desired_change": "worker control probe", "basis_refs": [],
                "action": {"type": "deliver", "args": {}, "expected_result": "control-flow-only"},
                "strategy_reason": "worker qualification control probe; excluded from semantic acceptance",
                "expected_participation": None, "reconsider_condition": "worker control probe complete",
                "messages": ["worker control probe"], "concern_ref": None, "task_ref": None, "concern_updates": [],
            },
            finish_reason="stop", usage={"input_tokens": 0, "output_tokens": 0}, latency_ms=0,
        )

class _RelayHandler(http.server.BaseHTTPRequestHandler):
    server: _RelayServer

    def log_message(self, _format: str, *_args: Any) -> None:
        return

    def _write(self, status: int, payload: dict[str, Any]) -> None:
        raw = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _authenticated(self) -> bool:
        supplied = self.headers.get("X-J05-Relay-Token", "")
        expected = str(getattr(self.server, "relay_token", ""))
        return bool(supplied) and secrets.compare_digest(supplied, expected)

    def do_GET(self) -> None:  # noqa: N802
        if self.path != "/health":
            self._write(404, {"status": "not_found"})
            return
        self._write(200, {"status": "ready", "model": self.server.model_name, "credential_scope": "gateway_only"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/complete":
            self._write(404, {"status": "not_found"})
            return
        if not self._authenticated():
            self._write(403, {"status": "rejected", "reason": "relay_auth_failed"})
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            size = 0
        if size <= 0 or size > MAX_REQUEST_BYTES:
            self._write(413, {"status": "rejected", "reason": "request_size_invalid"})
            return
        try:
            request = json.loads(self.rfile.read(size).decode("utf-8"))
            prompt = request.get("prompt")
            if not isinstance(prompt, dict):
                raise ValueError("prompt must be an object")
            if request.get("model") not in {None, self.server.model_name}:
                raise ValueError("model_mismatch")
            attempt = int(request.get("attempt", 1))
        except (ValueError, TypeError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            self._write(400, {"status": "rejected", "reason": type(exc).__name__})
            return

        request_id = str(request.get("request_id") or uuid.uuid4())
        spend_guard = getattr(self.server, "spend_guard", None)
        reservation: dict[str, Any] | None = None
        if spend_guard is not None:
            provider_payload = json.dumps(self.server.provider_gateway._payload(prompt, attempt), ensure_ascii=False).encode("utf-8")
            reservation = spend_guard.reserve(provider_payload)
            if not reservation.get("allowed"):
                response = ProviderResponse(request_id, self.server.model_name, {}, finish_reason="error", usage=None, latency_ms=0, error="cost_budget_exhausted", http_status=429)
                row = {
                    "request_id": request_id,
                    "action_id": request.get("action_id"),
                    "prompt_sha256": _json_hash(prompt),
                    "attempt": attempt,
                    "provider_request_id": None,
                    "provider_call": False,
                    "http_status": 429,
                    "error": response.error,
                    "usage": None,
                    "latency_ms": 0,
                    "relay_elapsed_ms": 0,
                    "budget": {**reservation, "guard": spend_guard.snapshot()},
                }
                self.server.log_path.parent.mkdir(parents=True, exist_ok=True)
                with self.server.log_path.open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
                self._write(200, {**_response_payload(response), "provider_call": False, "budget": row["budget"]})
                return

        started = time.perf_counter()
        response = self.server.provider_gateway.complete(prompt, attempt=attempt)
        settlement = spend_guard.settle(reservation or {}, response, provider_call=True) if spend_guard is not None else None
        row = {
            "request_id": request_id,
            "action_id": request.get("action_id"),
            "prompt_sha256": _json_hash(prompt),
            "attempt": attempt,
            "provider_request_id": response.request_id,
            "provider_call": True,
            "http_status": response.http_status,
            "error": response.error,
            "usage": response.usage,
            "latency_ms": response.latency_ms,
            "relay_elapsed_ms": int((time.perf_counter() - started) * 1000),
            "cost": settlement,
        }
        self.server.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.server.log_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
        self._write(200, {**_response_payload(response), "provider_call": True, "cost": settlement, "budget": spend_guard.snapshot() if spend_guard is not None else None})


def _run_relay_process(
    *,
    provider: str,
    model: str,
    endpoint: str,
    api_key: str,
    token: str,
    port: int,
    log_path: str,
    scripted: bool,
    max_budget_cny: float | None,
    cny_per_usd_ceiling: float,
    max_output_tokens: int | None,
    ready_conn: Any,
    stop_event: Any,
) -> None:
    """Process target.  The provider key is passed in memory only."""
    if scripted:
        gateway = _ControlGateway(model)
    else:
        parsed = urlsplit(endpoint)
        boundary = NetworkBoundary({parsed.hostname or ""}, {parsed.path})
        binding = ProviderBinding("text", provider, model, endpoint, api_key, "controller_gateway_process")
        gateway = build_text_gateway(binding, network_boundary=boundary, max_output_tokens=max_output_tokens)
    server = _RelayServer(("0.0.0.0", port), _RelayHandler)
    server.relay_token = token
    server.model_name = model
    server.provider_gateway = gateway
    server.spend_guard = SpendGuard(max_budget_cny=max_budget_cny, cny_per_usd_ceiling=cny_per_usd_ceiling, max_output_tokens=max_output_tokens or 512) if max_budget_cny is not None else None
    server.max_output_tokens = max_output_tokens
    server.log_path = pathlib.Path(log_path)
    server.timeout = 0.5
    try:
        ready_conn.send({"status": "ready", "host": "0.0.0.0", "port": server.server_port, "pid": __import__("os").getpid()})
        while not stop_event.is_set():
            server.handle_request()
    finally:
        server.server_close()
        try:
            ready_conn.close()
        except OSError:
            pass


@dataclass
class RelayProcess:
    process: Any
    stop_event: Any
    base_url: str
    token: str
    model: str
    pid: int

    def stop(self) -> None:
        self.stop_event.set()
        try:
            self.process.join(timeout=5)
        except Exception:
            pass
        if self.process.is_alive():
            self.process.terminate()
            self.process.join(timeout=5)


def start_relay(binding: ProviderBinding | None, *, log_path: pathlib.Path, model: str | None = None, scripted: bool = False, advertised_host: str = "127.0.0.1", max_budget_cny: float | None = None, cny_per_usd_ceiling: float = 10.0, max_output_tokens: int | None = None) -> RelayProcess:
    if not scripted and (binding is None or not binding.ready):
        raise ValueError("controller gateway binding is incomplete")
    if scripted and not model:
        model = "worker-control-probe"
    assert model is not None
    context = multiprocessing.get_context("spawn")
    stop_event = context.Event()
    parent_conn, child_conn = context.Pipe(duplex=False)
    token = secrets.token_urlsafe(32)
    process = context.Process(
        target=_run_relay_process,
        kwargs={
            "provider": str(binding.provider) if binding else "controller-control", "model": str(model), "endpoint": str(binding.endpoint) if binding else "http://127.0.0.1/unused",
            "api_key": str(binding.api_key) if binding else "", "token": token, "port": 0, "log_path": str(log_path), "scripted": scripted,
            "max_budget_cny": max_budget_cny, "cny_per_usd_ceiling": cny_per_usd_ceiling, "max_output_tokens": max_output_tokens,
            "ready_conn": child_conn, "stop_event": stop_event,
        },
        name="ideal-lab-controller-gateway",
    )
    process.start()
    child_conn.close()
    if not parent_conn.poll(30):
        process.terminate()
        process.join(timeout=5)
        raise RuntimeError("controller gateway relay did not become ready")
    ready = parent_conn.recv()
    parent_conn.close()
    if ready.get("status") != "ready":
        process.terminate()
        process.join(timeout=5)
        raise RuntimeError("controller gateway relay failed to start")
    return RelayProcess(process, stop_event, f"http://{advertised_host}:{int(ready['port'])}", token, str(model), int(ready["pid"]))


class RelayGateway:
    """Worker-side ModelGateway that has no provider credential field."""

    def __init__(self, *, base_url: str, token: str, model_name: str):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.model_name = model_name
        self.calls: list[dict[str, Any]] = []
        self.provider_calls: list[dict[str, Any]] = []

    def complete(self, prompt: dict[str, Any], *, attempt: int = 1) -> ProviderResponse:
        request_id = str(uuid.uuid4())
        payload = {"request_id": request_id, "action_id": prompt.get("action_id"), "model": self.model_name, "prompt": prompt, "attempt": attempt}
        request = urllib.request.Request(
            f"{self.base_url}/complete",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json", "X-J05-Relay-Token": self.token},
            method="POST",
        )
        started = time.perf_counter()
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                value = json.loads(response.read().decode("utf-8"))
            provider_call = bool(value.get("provider_call", True))
            record = {"request_id": request_id, "prompt_sha256": _json_hash(prompt), "attempt": attempt, "relay_http_status": 200, "provider_call": provider_call, "response_error": value.get("error"), "response_http_status": value.get("http_status"), "cost": value.get("cost"), "budget": value.get("budget")}
            self.calls.append(record)
            if provider_call:
                self.provider_calls.append(record)
            return ProviderResponse(
                str(value.get("request_id") or request_id), str(value.get("model") or self.model_name), value.get("content"),
                finish_reason=value.get("finish_reason"), usage=value.get("usage"), latency_ms=int(value.get("latency_ms") or (time.perf_counter() - started) * 1000),
                error=value.get("error"), http_status=value.get("http_status"),
            )
        except (OSError, ValueError, urllib.error.URLError) as exc:
            self.calls.append({"request_id": request_id, "prompt_sha256": _json_hash(prompt), "attempt": attempt, "relay_http_status": None, "error": type(exc).__name__})
            return ProviderResponse(request_id, self.model_name, {}, finish_reason="error", error=type(exc).__name__, latency_ms=int((time.perf_counter() - started) * 1000))

