"""Provider gateway interfaces. Credentials never enter the worker loop."""
from __future__ import annotations

import base64
import hashlib
import json
import pathlib
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
    http_status: int | None = None


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
    def __init__(self, *, model_name: str, endpoint: str, network_boundary, api_key: str | None = None, provider_name: str | None = None, max_output_tokens: int | None = None):
        self.model_name = model_name
        self.endpoint = endpoint
        self.network_boundary = network_boundary
        self.api_key = api_key
        self.provider_name = provider_name
        self.max_output_tokens = int(max_output_tokens) if max_output_tokens is not None else None

    def _payload(self, prompt: dict[str, Any], attempt: int) -> dict[str, Any]:
        """Translate the worker prompt to the production-compatible chat shape.

        The worker still owns the original structured prompt.  Only this
        gateway adapter serializes it as system/user JSON for the provider;
        credentials and provider-specific transport details remain outside the
        worker loop.
        """
        system = prompt.get("system", {})
        user_payload = {key: value for key, value in prompt.items() if key != "system"}
        payload = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": json.dumps(system, ensure_ascii=False)},
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
            ],
            "temperature": 0,
            "top_p": 1,
        }
        if self.max_output_tokens is not None:
            payload["max_tokens"] = self.max_output_tokens
        return payload

    def complete(self, prompt: dict[str, Any], *, attempt: int = 1) -> ProviderResponse:
        import urllib.error
        import urllib.request

        self.network_boundary.check(self.endpoint)
        payload = json.dumps(self._payload(prompt, attempt), ensure_ascii=False).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = urllib.request.Request(self.endpoint, data=payload, headers=headers, method="POST")
        started = time.perf_counter()
        request_id = str(uuid.uuid4())
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                return None

        try:
            opener = urllib.request.build_opener(NoRedirect)
            with opener.open(request, timeout=90) as response:  # endpoint was checked above
                raw = response.read()
            envelope = json.loads(raw.decode("utf-8"))
            usage = envelope.get("usage") if isinstance(envelope, dict) else None
            content: Any = envelope
            if isinstance(envelope, dict) and isinstance(envelope.get("choices"), list) and envelope["choices"]:
                choice = envelope["choices"][0]
                message = choice.get("message", {}) if isinstance(choice, dict) else {}
                content = message.get("content", choice.get("text") if isinstance(choice, dict) else None)
                if isinstance(content, str):
                    try:
                        content = json.loads(content)
                    except json.JSONDecodeError:
                        pass
            return ProviderResponse(request_id, self.model_name, content, usage=usage, latency_ms=int((time.perf_counter() - started) * 1000), http_status=200)
        except urllib.error.HTTPError as exc:
            # Preserve the provider status class so the loop can distinguish a
            # permanent auth/not-found error from a retryable service failure.
            return ProviderResponse(request_id, self.model_name, {}, finish_reason="error", usage=None, latency_ms=int((time.perf_counter() - started) * 1000), error=f"http_{exc.code}", http_status=int(exc.code))
        except (OSError, ValueError, urllib.error.URLError) as exc:
            return ProviderResponse(request_id, self.model_name, {}, finish_reason="error", usage=None, latency_ms=int((time.perf_counter() - started) * 1000), error=type(exc).__name__)


@dataclass
class ImageProviderResponse:
    request_id: str
    model: str
    asset_path: str | None = None
    asset_sha256: str | None = None
    usage: dict[str, Any] | None = None
    latency_ms: int = 0
    raw_response_ref: str | None = None
    error: str | None = None


class ImageGateway(Protocol):
    model_name: str

    def generate(self, prompt: str, *, references: list[str] | None = None, attempt: int = 1) -> ImageProviderResponse:
        ...


class HttpImageGateway:
    """Image provider boundary that only accepts provider-returned local bytes.

    A remote URL is deliberately not followed by the worker.  The provider
    must return base64 image bytes, which this gateway writes under the current
    trajectory's asset root and records as a hashable local artifact.
    """

    def __init__(self, *, model_name: str, endpoint: str, network_boundary, asset_root: pathlib.Path, raw_root: pathlib.Path | None = None, api_key: str | None = None, provider_name: str | None = None):
        self.model_name = model_name
        self.endpoint = endpoint
        self.network_boundary = network_boundary
        self.asset_root = asset_root
        self.raw_root = raw_root
        self.api_key = api_key
        self.provider_name = provider_name

    def _write_raw(self, request_id: str, value: Any) -> str | None:
        if self.raw_root is None:
            return None
        self.raw_root.mkdir(parents=True, exist_ok=True)
        raw_path = self.raw_root / f"image-{request_id}.json"
        if raw_path.exists():
            raw_path = self.raw_root / f"image-{request_id}-{uuid.uuid4().hex[:8]}.json"
        raw_path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
        return str(raw_path)

    def generate(self, prompt: str, *, references: list[str] | None = None, attempt: int = 1) -> ImageProviderResponse:
        import urllib.error
        import urllib.request

        self.network_boundary.check(self.endpoint)
        request_id = str(uuid.uuid4())
        payload: dict[str, Any] = {"model": self.model_name, "prompt": prompt}
        if references:
            payload["references"] = references
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = urllib.request.Request(self.endpoint, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"), headers=headers, method="POST")
        started = time.perf_counter()

        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                return None

        try:
            opener = urllib.request.build_opener(NoRedirect)
            with opener.open(request, timeout=180) as response:
                raw = response.read()
            envelope = json.loads(raw.decode("utf-8"))
            raw_ref = self._write_raw(request_id, envelope)
            item = envelope.get("data", [{}])[0] if isinstance(envelope, dict) and isinstance(envelope.get("data"), list) and envelope.get("data") else envelope
            encoded = item.get("b64_json") if isinstance(item, dict) else None
            if not encoded and isinstance(envelope, dict):
                encoded = envelope.get("b64_json")
            if not encoded:
                return ImageProviderResponse(request_id, self.model_name, usage=envelope.get("usage") if isinstance(envelope, dict) else None, latency_ms=int((time.perf_counter() - started) * 1000), raw_response_ref=raw_ref, error="image_response_not_local")
            image_bytes = base64.b64decode(encoded, validate=True)
            if not image_bytes:
                return ImageProviderResponse(request_id, self.model_name, usage=envelope.get("usage") if isinstance(envelope, dict) else None, latency_ms=int((time.perf_counter() - started) * 1000), raw_response_ref=raw_ref, error="image_response_empty")
            self.asset_root.mkdir(parents=True, exist_ok=True)
            asset_path = self.asset_root / f"{request_id}.png"
            with asset_path.open("xb") as stream:
                stream.write(image_bytes)
            digest = hashlib.sha256(image_bytes).hexdigest()
            return ImageProviderResponse(request_id, self.model_name, str(asset_path), digest, envelope.get("usage") if isinstance(envelope, dict) else None, int((time.perf_counter() - started) * 1000), raw_ref)
        except urllib.error.HTTPError as exc:
            raw_ref = self._write_raw(request_id, {"error": f"http_{exc.code}", "status": exc.code})
            return ImageProviderResponse(request_id, self.model_name, latency_ms=int((time.perf_counter() - started) * 1000), raw_response_ref=raw_ref, error=f"http_{exc.code}")
        except (OSError, ValueError, base64.binascii.Error, urllib.error.URLError) as exc:
            raw_ref = self._write_raw(request_id, {"error": type(exc).__name__})
            return ImageProviderResponse(request_id, self.model_name, latency_ms=int((time.perf_counter() - started) * 1000), raw_response_ref=raw_ref, error=type(exc).__name__)
