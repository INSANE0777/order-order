"""Language models, reached only through a narrow interface.

The engine never imports a provider. It asks for something that turns a prompt into a validated
Pydantic object, and this module supplies one, built from configuration:

    LLM_PRIMARY=google_genai:gemini-2.5-flash
    LLM_FALLBACKS=groq:openai/gpt-oss-120b,cerebras:gpt-oss-120b,ollama:qwen3.5:4b

Two reasons the indirection earns its place. Free tiers rate-limit, so a call must be able to fail over
to the next provider mid-run, which `with_fallbacks` does. And the engine has to be testable without a
network or an API key, which a stub satisfying `StructuredModel` does.

Structured output method differs by provider: Gemini and Ollama support native JSON-schema decoding,
while the open-weight endpoints are more reliable coerced through tool calling.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel

from orderorder.config import get_settings

OLLAMA_DEFAULT_HOST = "http://localhost:11434"
OLLAMA_PROBE_TIMEOUT = 1.0


@lru_cache(maxsize=4)
def ollama_running(host: str | None = None) -> bool:
    """Whether a local Ollama server is actually listening.

    Ollama needs no API key, so a key check would call it available even when nothing is running and
    every request would fail at the point of use. Probe once and cache the answer.
    """
    import httpx

    base = host or os.environ.get("OLLAMA_HOST") or OLLAMA_DEFAULT_HOST
    if not base.startswith("http"):
        base = f"http://{base}"
    try:
        response = httpx.get(f"{base.rstrip('/')}/api/tags", timeout=OLLAMA_PROBE_TIMEOUT)
        return response.status_code == 200
    except Exception:  # noqa: BLE001 - any failure means it is not usable
        return False

# Which structured-output method each provider handles best.
STRUCTURED_METHOD = {
    "google_genai": "json_schema",
    "ollama": "json_schema",
    "openai": "json_schema",
    "groq": "function_calling",
    "cerebras": "function_calling",
    "mistralai": "function_calling",
}
# Providers that need a key in the environment before they can be built.
PROVIDER_ENV = {
    "google_genai": "GOOGLE_API_KEY",
    "groq": "GROQ_API_KEY",
    "cerebras": "CEREBRAS_API_KEY",
    "mistralai": "MISTRAL_API_KEY",
    "openai": "OPENAI_API_KEY",
    "ollama": None,  # runs locally, no key
}


@runtime_checkable
class StructuredModel(Protocol):
    """Anything that turns a prompt into an instance of the requested schema."""

    def invoke(self, prompt: str) -> BaseModel: ...


@dataclass
class ProviderSpec:
    provider: str
    model: str

    @property
    def as_string(self) -> str:
        return f"{self.provider}:{self.model}"

    @property
    def env_var(self) -> str | None:
        return PROVIDER_ENV.get(self.provider)

    @property
    def is_available(self) -> bool:
        if self.provider == "ollama":
            return ollama_running()
        env = self.env_var
        return True if env is None else bool(os.environ.get(env))

    @property
    def structured_method(self) -> str:
        return STRUCTURED_METHOD.get(self.provider, "function_calling")


def parse_spec(text: str) -> ProviderSpec | None:
    """Parse "provider:model". The model half may itself contain colons or slashes."""
    text = (text or "").strip()
    if ":" not in text:
        return None
    provider, _, model = text.partition(":")
    provider, model = provider.strip(), model.strip()
    return ProviderSpec(provider, model) if provider and model else None


def available_specs() -> list[ProviderSpec]:
    """Configured providers that could actually be called right now, primary first."""
    settings = get_settings()
    specs = [parse_spec(settings.llm_primary), *(parse_spec(s) for s in settings.fallback_models)]
    seen: set[str] = set()
    out: list[ProviderSpec] = []
    for spec in specs:
        if spec is None or spec.as_string in seen:
            continue
        seen.add(spec.as_string)
        if spec.is_available:
            out.append(spec)
    return out


def _build_one(spec: ProviderSpec, schema: type[BaseModel], **kwargs: Any):
    from langchain.chat_models import init_chat_model

    model = init_chat_model(spec.model, model_provider=spec.provider, temperature=0, **kwargs)
    return model.with_structured_output(schema, method=spec.structured_method)


def build_structured(schema: type[BaseModel], *, specs: list[ProviderSpec] | None = None, **kwargs: Any):
    """A runnable that returns `schema`, with the configured fallback chain behind it.

    Returns None when no configured provider has a key, so callers can degrade to the model-free
    checks and say so, rather than failing at the point of use.
    """
    specs = specs if specs is not None else available_specs()
    if not specs:
        return None
    primary = _build_one(specs[0], schema, **kwargs)
    rest = [_build_one(s, schema, **kwargs) for s in specs[1:]]
    return primary.with_fallbacks(rest) if rest else primary


def describe_providers() -> list[tuple[str, str, bool]]:
    """(provider string, env var or '-', usable) for every configured provider, for `doctor`."""
    settings = get_settings()
    rows: list[tuple[str, str, bool]] = []
    for text in [settings.llm_primary, *settings.fallback_models]:
        spec = parse_spec(text)
        if spec is None:
            continue
        requirement = spec.env_var or ("server running" if spec.provider == "ollama" else "-")
        rows.append((spec.as_string, requirement, spec.is_available))
    return rows
