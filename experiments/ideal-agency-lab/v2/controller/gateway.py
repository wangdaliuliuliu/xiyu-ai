"""Provider gateway interfaces. Credentials never enter the worker loop."""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass
class ProviderResponse:
    request_id: str
    model: str
    content: Any
    finish_reason: str | None = "stop"
    usage: dict[str, Any] | None = None
    latency_ms: int = 0
    error: str | None = None


class ModelGateway(Protocol):
    model_name: str

    def complete(self, prompt: dict[str, Any], *, attempt: int = 1) -> ProviderResponse:
        ...


class ScriptedGateway:
    """Deterministic gateway for E2 and harness self-tests.

    Scripts are structured provider responses, not assistant answer fixtures.
    The test caller is responsible for stating that these runs are injected.
    """
    model_name = "deterministic-injected"

    def __init__(self, responses: list[Any]):
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def complete(self, prompt: dict[str, Any], *, attempt: int = 1) -> ProviderResponse:
        started = time.perf_counter()
        self.calls.append({"prompt": prompt, "attempt": attempt})
        if not self.responses:
            return ProviderResponse(str(uuid.uuid4()), self.model_name, {}, finish_reason="error", usage=None, error="script_exhausted")
        response = self.responses.pop(0)
        if isinstance(response, ProviderResponse):
            return response
        if isinstance(response, Exception):
            return ProviderResponse(str(uuid.uuid4()), self.model_name, {}, finish_reason="error", error=type(response).__name__)
        latency = int((time.perf_counter() - started) * 1000)
        return ProviderResponse(str(uuid.uuid4()), self.model_name, response, usage={"input_tokens": 0, "output_tokens": 0}, latency_ms=latency)


class HttpProviderGateway:
    """Minimal provider adapter; URL checks are done before any request.

    The concrete provider payload is intentionally configured by the caller.
    This gateway does not accept redirects and never logs authorization data.
    """
    def __init__(self, *, model_name: str, endpoint: str, network_boundary, api_key: str | None = None):
        self.model_name = model_name
        self.endpoint = endpoint
        self.network_boundary = network_boundary
        self.api_key = api_key

    def complete(self, prompt: dict[str, Any], *, attempt: int = 1) -> ProviderResponse:
        import urllib.error
        import urllib.request

        self.network_boundary.check(self.endpoint)
        payload = json.dumps(prompt, ensure_ascii=False).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = urllib.request.Request(self.endpoint, data=payload, headers=headers, method="POST")
        started = time.perf_counter()
        request_id = str(uuid.uuid4())
        try:
            with urllib.request.urlopen(request, timeout=90) as response:  # nosec B310 - endpoint checked above
                raw = response.read()
            content = json.loads(raw.decode("utf-8"))
            return ProviderResponse(request_id, self.model_name, content, usage=None, latency_ms=int((time.perf_counter() - started) * 1000))
        except (OSError, ValueError, urllib.error.URLError) as exc:
            return ProviderResponse(request_id, self.model_name, {}, finish_reason="error", usage=None, latency_ms=int((time.perf_counter() - started) * 1000), error=type(exc).__name__)

