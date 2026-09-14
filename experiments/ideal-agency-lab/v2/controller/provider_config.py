"""Explicit provider bindings for the formal experiment gateway.

The production provider registry is a reference for provider names and
protocols only.  This module never loads ``.env``, SQLite settings, or a
production provider module.  A run can use a provider only when its endpoint,
model, and (where required) experiment-scoped credential are explicitly
bound to the gateway process.
"""
from __future__ import annotations

import os
import pathlib
import sqlite3
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit


EXPERIMENT_TEXT_ENV = {
    "provider": "IDEAL_LAB_PROVIDER_NAME",
    "endpoint": "IDEAL_LAB_PROVIDER_ENDPOINT",
    "model": "IDEAL_LAB_PROVIDER_MODEL",
    "api_key": "IDEAL_LAB_PROVIDER_API_KEY",
}
EXPERIMENT_IMAGE_ENV = {
    "provider": "IDEAL_LAB_IMAGE_PROVIDER_NAME",
    "endpoint": "IDEAL_LAB_IMAGE_ENDPOINT",
    "model": "IDEAL_LAB_IMAGE_MODEL",
    "api_key": "IDEAL_LAB_IMAGE_API_KEY",
}

# This is a non-secret protocol snapshot of the production registry.  Native
# Anthropic/Gemini APIs are intentionally not advertised here because the v2
# gateway currently speaks the OpenAI-compatible request/response contract.
KNOWN_OPENAI_COMPATIBLE_PROVIDERS = {
    "deepseek": {"base_url": "https://api.deepseek.com", "api_key_env": "DEEPSEEK_API_KEY", "default_model": "deepseek-chat"},
    "openai": {"base_url": "https://api.openai.com/v1", "api_key_env": "OPENAI_API_KEY", "default_model": "gpt-4o-mini"},
    "xai": {"base_url": "https://api.x.ai/v1", "api_key_env": "XAI_API_KEY", "default_model": "grok-3-mini"},
    "zhipu": {"base_url": "https://open.bigmodel.cn/api/paas/v4", "api_key_env": "ZHIPU_API_KEY", "default_model": "glm-4-flash"},
    "doubao": {"base_url": "https://ark.cn-beijing.volces.com/api/v3", "api_key_env": "DOUBAO_API_KEY", "default_model": ""},
    "qwen": {"base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "api_key_env": "QWEN_API_KEY", "default_model": "qwen-plus"},
    "kimi": {"base_url": "https://api.moonshot.cn/v1", "api_key_env": "KIMI_API_KEY", "default_model": "moonshot-v1-8k"},
    "wenxin": {"base_url": "https://qianfan.baidubce.com/v2", "api_key_env": "WENXIN_API_KEY", "default_model": ""},
    "minimax": {"base_url": "https://api.minimax.chat/v1", "api_key_env": "MINIMAX_API_KEY", "default_model": ""},
    "stepfun": {"base_url": "https://api.stepfun.com/v1", "api_key_env": "STEPFUN_API_KEY", "default_model": ""},
    "openai-compatible": {"base_url": "", "api_key_env": "OPENAI_COMPATIBLE_API_KEY", "default_model": ""},
    "ollama": {"base_url": "http://127.0.0.1:11434/v1", "api_key_env": "OLLAMA_API_KEY", "default_model": ""},
}
KNOWN_IMAGE_PROVIDERS = {
    "iotwq": {
        "base_url": "https://api.iotwq.top/v1",
        "api_key_env": "XAI_API_KEY",
        "alternate_api_key_env": "IOTWQ_API_KEY",
        "base_url_env": "GROK_MODELS_BASE_URL",
        "alternate_base_url_env": "IOTWQ_BASE_URL",
        "default_model": "grok-imagine-image-quality",
    },
    "openai": {"base_url": "https://api.openai.com/v1", "api_key_env": "OPENAI_API_KEY"},
    "zhipu": {"base_url": "https://open.bigmodel.cn/api/paas/v4", "api_key_env": "ZHIPU_API_KEY"},
    "doubao": {"base_url": "https://ark.cn-beijing.volces.com/api/v3", "api_key_env": "DOUBAO_API_KEY"},
}


@dataclass(frozen=True)
class ProviderBinding:
    kind: str
    provider: str | None
    model: str | None
    endpoint: str | None
    api_key: str | None
    source: str

    @property
    def ready(self) -> bool:
        return bool(self.provider and self.model and self.endpoint and self.api_key)

    def safe_record(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "provider": self.provider,
            "model": self.model,
            "endpoint": self.endpoint,
            "endpoint_host": urlsplit(self.endpoint).hostname if self.endpoint else None,
            "endpoint_path": urlsplit(self.endpoint).path if self.endpoint else None,
            "credential_present": bool(self.api_key),
            "credential_scope": "gateway_only" if self.api_key else "not_bound",
            "credential_source": f"{self.source}:api_key" if self.api_key else None,
            "worker_receives_credential": False,
            "status": "ready" if self.ready else "incomplete",
        }


def normalise_endpoint(value: str | None, *, kind: str) -> str | None:
    if not value:
        return None
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return value.strip()
    path = parsed.path.rstrip("/")
    if kind == "text" and not path.endswith("/chat/completions"):
        path = f"{path}/chat/completions" if path else "/v1/chat/completions"
    if kind == "image" and not path.endswith("/images/generations"):
        path = f"{path}/images/generations" if path else "/v1/images/generations"
    return urlunsplit((parsed.scheme, parsed.netloc, path, parsed.query, parsed.fragment))


def _resolve(kind: str, *, provider: str | None, endpoint: str | None, model: str | None, api_key: str | None) -> ProviderBinding:
    env = EXPERIMENT_TEXT_ENV if kind == "text" else EXPERIMENT_IMAGE_ENV
    resolved_provider = provider or os.environ.get(env["provider"])
    resolved_endpoint = endpoint or os.environ.get(env["endpoint"])
    resolved_model = model or os.environ.get(env["model"])
    resolved_key = api_key if api_key is not None else os.environ.get(env["api_key"])
    source = "explicit_argument" if any(value is not None for value in (provider, endpoint, model, api_key)) else "experiment_process_env"
    resolved_provider = resolved_provider.lower() if resolved_provider else None
    catalog = KNOWN_OPENAI_COMPATIBLE_PROVIDERS if kind == "text" else KNOWN_IMAGE_PROVIDERS
    if not resolved_endpoint and resolved_provider in catalog and catalog[resolved_provider].get("base_url"):
        base_url = str(catalog[resolved_provider]["base_url"]).rstrip("/")
        resolved_endpoint = f"{base_url}/{'chat/completions' if kind == 'text' else 'images/generations'}"
        source = f"{source}:provider_catalog"
    return ProviderBinding(kind, resolved_provider, resolved_model, normalise_endpoint(resolved_endpoint, kind=kind), resolved_key, source)


def resolve_text_binding(*, provider: str | None = None, endpoint: str | None = None, model: str | None = None, api_key: str | None = None) -> ProviderBinding:
    return _resolve("text", provider=provider, endpoint=endpoint, model=model, api_key=api_key)


def resolve_image_binding(*, provider: str | None = None, endpoint: str | None = None, model: str | None = None, api_key: str | None = None) -> ProviderBinding:
    return _resolve("image", provider=provider, endpoint=endpoint, model=model, api_key=api_key)


def _parse_env_file(path: pathlib.Path) -> dict[str, str]:
    """Parse only assignment lines; never return or log this mapping to callers."""
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key] = value
    return values


def _read_app_settings(path: pathlib.Path) -> tuple[dict[str, str], dict[str, dict[str, object]]]:
    """Read production settings through SQLite read-only URI, without prod imports."""
    if not path.exists():
        return {}, {"database": {"path": str(path.resolve()), "status": "absent"}}
    # ``immutable=1`` prevents a read-only resolver from creating/touching
    # SQLite -wal/-shm sidecars.  This keeps the provider preflight truly
    # non-mutating while the database itself remains read-only.
    uri = f"file:{path.resolve().as_posix()}?mode=ro&immutable=1"
    values: dict[str, str] = {}
    metadata: dict[str, dict[str, object]] = {}
    connection = sqlite3.connect(uri, uri=True)
    try:
        rows = connection.execute("SELECT key, value, secret FROM app_settings").fetchall()
        for key, value, secret in rows:
            if value is None:
                continue
            values[str(key)] = str(value)
            metadata[str(key)] = {"source": "sqlite_app_settings", "secret": bool(secret), "value_present": bool(str(value))}
    finally:
        connection.close()
    return values, {"database": {"path": str(path.resolve()), "status": "read_only", "keys_observed": sorted(metadata)}, "keys": metadata}


def _secret_fact(value: str | None) -> dict[str, object]:
    return {"present": bool(value), "length": len(value) if value else 0}


def resolve_production_text_binding(*, production_root: pathlib.Path) -> tuple[ProviderBinding, dict[str, object]]:
    """Resolve the effective production text channel without importing production code.

    The resolver intentionally follows the observed production contract: env >
    app_settings > registry defaults.  The returned binding contains the key
    only in memory for the gateway; ``record`` is safe for evidence files.
    """
    root = production_root.resolve()
    env_path = root / ".env"
    env_values = _parse_env_file(env_path)
    db_value = env_values.get("DB_PATH") or "./data/bot.db"
    db_path = pathlib.Path(db_value)
    if not db_path.is_absolute():
        db_path = root / db_path
    try:
        settings, settings_meta = _read_app_settings(db_path)
    except (OSError, sqlite3.Error) as exc:
        settings = {}
        settings_meta = {"database": {"path": str(db_path.resolve()), "status": "read_error", "error_type": type(exc).__name__}}

    def choose(key: str, *, default: str | None = None) -> tuple[str | None, str]:
        if env_values.get(key):
            return env_values[key], f"env:{env_path.name}:{key}"
        if settings.get(key):
            return settings[key], f"sqlite_app_settings:{db_path.name}:{key}"
        return default, "registry_default" if default is not None else "missing"

    provider, provider_source = choose("CHAT_PROVIDER", default="deepseek")
    provider = provider.lower() if provider else None
    catalog = KNOWN_OPENAI_COMPATIBLE_PROVIDERS.get(provider or "", {})
    model, model_source = choose("CHAT_MODEL", default=catalog.get("default_model"))
    key_env = str(catalog.get("api_key_env") or "")
    api_key, key_source = choose(key_env)
    base_url_key = f"{provider.upper()}_BASE_URL" if provider else ""
    if provider == "openai-compatible":
        base_url_key = "OPENAI_COMPATIBLE_BASE_URL"
    base_url, endpoint_source = choose(base_url_key, default=catalog.get("base_url"))
    endpoint = normalise_endpoint(base_url, kind="text")
    if endpoint and not urlsplit(endpoint).path.endswith("/chat/completions"):
        endpoint = normalise_endpoint(endpoint, kind="text")
    binding = ProviderBinding("text", provider, model, endpoint, api_key, "production_effective_config")
    record = {
        "schemaVersion": "effective-provider-v1",
        "status": "ready" if binding.ready else "incomplete",
        "kind": "text",
        "provider": provider,
        "model": model,
        "endpoint": endpoint,
        "endpoint_host": urlsplit(endpoint).hostname if endpoint else None,
        "endpoint_path": urlsplit(endpoint).path if endpoint else None,
        "resolution_priority": ["process_environment", "sqlite_app_settings", "provider_registry_default"],
        "resolved_fields": {
            "provider": {"source": provider_source, "value_present": bool(provider)},
            "model": {"source": model_source, "value_present": bool(model)},
            "endpoint": {"source": endpoint_source, "value_present": bool(endpoint)},
            "credential": {"source": key_source if api_key else None, "key_name": key_env or None, **_secret_fact(api_key)},
        },
        "production_materials": {
            "root": str(root),
            "env_file": {"path": str(env_path), "status": "read_only", "text_provider_values_used": [key for key in ("CHAT_PROVIDER", "CHAT_MODEL", base_url_key) if key and env_values.get(key)]},
            "sqlite": settings_meta,
            "credential_value_persisted_only_in_memory": True,
        },
        "gateway_binding": {
            "process_reference": "controller.provider_config.build_text_gateway",
            "credential_scope": "gateway_only",
            "worker_receives_credential": False,
            "worker_or_bot_invoked": False,
        },
        "availability": "not_probed",
    }
    return binding, record


def resolve_production_image_binding(*, production_root: pathlib.Path) -> tuple[ProviderBinding, dict[str, object]]:
    """Resolve the production image channel without importing production code.

    ``src/providers/image.mjs`` uses the same env-over-SQLite convention as the
    text provider, with provider-specific endpoint/key names for the existing
    iotwq/Grok channel.  The key is returned only in the in-memory binding; the
    accompanying record is safe to persist.
    """
    root = production_root.resolve()
    env_path = root / ".env"
    env_values = _parse_env_file(env_path)
    db_value = env_values.get("DB_PATH") or "./data/bot.db"
    db_path = pathlib.Path(db_value)
    if not db_path.is_absolute():
        db_path = root / db_path
    try:
        settings, settings_meta = _read_app_settings(db_path)
    except (OSError, sqlite3.Error) as exc:
        settings = {}
        settings_meta = {"database": {"path": str(db_path.resolve()), "status": "read_error", "error_type": type(exc).__name__}}

    def choose(key: str, *, default: str | None = None) -> tuple[str | None, str]:
        if env_values.get(key):
            return env_values[key], f"env:{env_path.name}:{key}"
        if settings.get(key):
            return settings[key], f"sqlite_app_settings:{db_path.name}:{key}"
        return default, "registry_default" if default is not None else "missing"

    def choose_any(keys: tuple[str, ...]) -> tuple[str | None, str, str | None]:
        for key in keys:
            value, source = choose(key)
            if value:
                return value, source, key
        return None, "missing", None

    provider, provider_source = choose("IMAGE_PROVIDER", default="zhipu")
    provider = provider.lower() if provider else None
    catalog = KNOWN_IMAGE_PROVIDERS.get(provider or "", {})
    model, model_source = choose("IMAGE_MODEL", default=catalog.get("default_model"))
    api_key_names = tuple(name for name in (catalog.get("api_key_env"), catalog.get("alternate_api_key_env")) if name)
    api_key, key_source, key_name = choose_any(api_key_names)
    endpoint_keys = tuple(name for name in (catalog.get("base_url_env"), catalog.get("alternate_base_url_env")) if name)
    base_url, endpoint_source, endpoint_key = choose_any(endpoint_keys)
    if not base_url:
        base_url, endpoint_source = choose("IMAGE_BASE_URL", default=catalog.get("base_url"))
        endpoint_key = "IMAGE_BASE_URL" if base_url and endpoint_source != "registry_default" else None
    endpoint = normalise_endpoint(base_url, kind="image")
    binding = ProviderBinding("image", provider, model, endpoint, api_key, "production_effective_config:image")
    record = {
        "schemaVersion": "effective-provider-v1",
        "status": "ready" if binding.ready else "incomplete",
        "kind": "image",
        "provider": provider,
        "model": model,
        "endpoint": endpoint,
        "endpoint_host": urlsplit(endpoint).hostname if endpoint else None,
        "endpoint_path": urlsplit(endpoint).path if endpoint else None,
        "resolution_priority": ["process_environment", "sqlite_app_settings", "provider_registry_default"],
        "resolved_fields": {
            "provider": {"source": provider_source, "value_present": bool(provider)},
            "model": {"source": model_source, "value_present": bool(model)},
            "endpoint": {"source": endpoint_source, "key_name": endpoint_key, "value_present": bool(endpoint)},
            "credential": {"source": key_source if api_key else None, "key_name": key_name, **_secret_fact(api_key)},
        },
        "production_materials": {
            "root": str(root),
            "env_file": {"path": str(env_path), "status": "read_only", "image_values_used": [key for key in ("IMAGE_PROVIDER", "IMAGE_MODEL", *endpoint_keys) if key and env_values.get(key)]},
            "sqlite": settings_meta,
            "credential_value_persisted_only_in_memory": True,
        },
        "gateway_binding": {
            "process_reference": "controller.provider_config.build_image_gateway",
            "credential_scope": "gateway_only",
            "worker_receives_credential": False,
            "worker_or_bot_invoked": False,
        },
        "availability": "not_probed",
    }
    return binding, record


def build_text_gateway(binding: ProviderBinding, *, network_boundary, max_output_tokens: int | None = None):
    if not binding.ready:
        raise ValueError("experiment text provider binding is incomplete")
    from controller.gateway import HttpProviderGateway

    return HttpProviderGateway(
        model_name=str(binding.model),
        endpoint=str(binding.endpoint),
        network_boundary=network_boundary,
        api_key=binding.api_key,
        provider_name=str(binding.provider),
        max_output_tokens=max_output_tokens,
    )


def build_image_gateway(binding: ProviderBinding, *, network_boundary, asset_root: pathlib.Path, raw_root: pathlib.Path):
    if not binding.ready:
        raise ValueError("experiment image provider binding is incomplete")
    from controller.gateway import HttpImageGateway

    return HttpImageGateway(
        model_name=str(binding.model),
        endpoint=str(binding.endpoint),
        network_boundary=network_boundary,
        asset_root=asset_root,
        raw_root=raw_root,
        api_key=binding.api_key,
        provider_name=str(binding.provider),
    )
