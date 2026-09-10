"""Language models, reached only through a narrow interface.

The engine never imports a provider. It asks for something that turns a prompt into a validated
Pydantic object, and this module supplies one, built from configuration:

    LLM_PRIMARY=google_genai:gemini-3.6-flash
    LLM_FALLBACKS=groq:openai/gpt-oss-120b,cerebras:gpt-oss-120b,ollama:qwen3:4b

Two reasons the indirection earns its place. Free tiers rate-limit, so a call must be able to fail over
to the next provider mid-run, which `with_fallbacks` does. And the engine has to be testable without a
network or an API key, which a stub satisfying `StructuredModel` does.

**One provider, several accounts.** A free tier is per account, so the way to raise a daily ceiling is
usually a second key rather than a fifth provider. Each SDK reads one fixed variable from the
environment, which is the assumption that breaks, so an entry may name its own:

    LLM_FALLBACKS=google_genai:gemini-3.6-flash#GOOGLE_API_KEY_2,groq:openai/gpt-oss-120b

Worth knowing what this does and does not buy. `with_fallbacks` moves to the next rung when a call
raises, so an exhausted key costs one failed request *per call* for the rest of the run rather than
being remembered and skipped. There is no cooldown and no circuit breaker. And every failure the
chain cannot cover degrades to *not assessed* by design, so a chain exhausted end to end produces a
page of honest abstentions that reads exactly like a corpus with nothing to say. Longer chains make
that more likely, not less: watch the abstention rate, and probe before a run.

Structured output method differs by provider: Gemini and Ollama support native JSON-schema decoding,
while the open-weight endpoints are more reliable coerced through tool calling.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel

from orderorder import logs
from orderorder.config import get_settings

log = logs.get_logger(__name__)

OLLAMA_DEFAULT_HOST = "http://localhost:11434"
OLLAMA_PROBE_TIMEOUT = 1.0


@lru_cache(maxsize=4)
def ollama_models(host: str | None = None) -> tuple[str, ...]:
    """The models a local Ollama server actually holds, or an empty tuple if it is not listening.

    Ollama needs no API key, so a key check would call it available even when nothing is running and
    every request would fail at the point of use. A running server with nothing pulled fails just as
    surely, which is what an empty tuple records. Probe once and cache the answer.
    """
    import httpx

    base = host or os.environ.get("OLLAMA_HOST") or OLLAMA_DEFAULT_HOST
    if not base.startswith("http"):
        base = f"http://{base}"
    try:
        response = httpx.get(f"{base.rstrip('/')}/api/tags", timeout=OLLAMA_PROBE_TIMEOUT)
        if response.status_code != 200:
            return ()
        return tuple(m.get("name", "") for m in response.json().get("models", []))
    except Exception:  # noqa: BLE001 - any failure means it is not usable
        return ()


def ollama_running(host: str | None = None) -> bool:
    """Whether a local Ollama server is listening at all, whatever it holds."""
    return bool(ollama_models(host))


def ollama_has_model(model: str, host: str | None = None) -> bool:
    """Whether one particular model is pulled. Ollama tags default to ':latest' when unqualified."""
    wanted = model if ":" in model else f"{model}:latest"
    return any(name in (wanted, model) for name in ollama_models(host))

# Which structured-output method each provider handles best.
STRUCTURED_METHOD = {
    "google_genai": "json_schema",
    "ollama": "json_schema",
    "openai": "json_schema",
    "groq": "function_calling",
    "cerebras": "function_calling",
    "mistralai": "function_calling",
}
# Separates a provider string from the environment variable holding its key, so that one provider
# can appear on the chain more than once against different accounts. `#` because no model identifier
# uses it, while `:` and `/` both appear in them (`ollama:qwen3:4b`, `groq:openai/gpt-oss-120b`).
KEY_SEPARATOR = "#"

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
    # Which environment variable holds this entry's key, when it is not the provider's default one.
    # `None` means the default, which is the ordinary case.
    key_env: str | None = None

    @property
    def as_string(self) -> str:
        # The key variable is part of the identity: two entries for the same model on different
        # accounts are two different rungs of the chain, and `available_specs` dedupes on this
        # string. The *name* appears in logs and in `doctor`; the value never does.
        if self.key_env:
            return f"{self.provider}:{self.model}{KEY_SEPARATOR}{self.key_env}"
        return f"{self.provider}:{self.model}"

    @property
    def env_var(self) -> str | None:
        return self.key_env or PROVIDER_ENV.get(self.provider)

    @property
    def is_available(self) -> bool:
        if self.provider == "ollama":
            # A server that is up but has not pulled this model is not usable: the failure would
            # otherwise arrive mid-run as a provider error, which reads as "checked and could not
            # confirm" when the truth is that nothing was ever configured.
            return ollama_has_model(self.model)
        env = self.env_var
        return True if env is None else bool(os.environ.get(env))

    @property
    def structured_method(self) -> str:
        return STRUCTURED_METHOD.get(self.provider, "function_calling")


def parse_spec(text: str) -> ProviderSpec | None:
    """Parse "provider:model" or "provider:model#KEY_ENV_VAR".

    The model half may itself contain colons or slashes (`ollama:qwen3:4b`,
    `groq:openai/gpt-oss-120b`), so the provider is taken from the first colon. The optional key
    suffix is taken from the last `#`, which no model identifier uses.

    The suffix is what lets one provider appear more than once on different accounts:

        LLM_FALLBACKS=google_genai:gemini-3.6-flash#GOOGLE_API_KEY_2,groq:openai/gpt-oss-120b

    Naming the provider's own default variable is the same as omitting it, so the two spellings do
    not become two rungs of the chain pointing at one key.
    """
    text = (text or "").strip()
    key_env: str | None = None
    if KEY_SEPARATOR in text:
        text, _, key_env = text.rpartition(KEY_SEPARATOR)
        key_env = key_env.strip() or None
    text = text.strip()
    if ":" not in text:
        return None
    provider, _, model = text.partition(":")
    provider, model = provider.strip(), model.strip()
    if not (provider and model):
        return None
    if key_env and key_env == PROVIDER_ENV.get(provider):
        key_env = None
    return ProviderSpec(provider, model, key_env)


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


# How long one model call may take before it is abandoned. Generous, because a long paragraph and
# a schema to fill is real work, and a routed gateway adds a hop; but finite, because the engine
# has an honest answer for a check it could not run and none for one that never returned.
REQUEST_TIMEOUT_SECONDS = 90.0
MAX_RETRIES = 1


def _build_one(spec: ProviderSpec, schema: type[BaseModel], **kwargs: Any):
    from langchain.chat_models import init_chat_model

    # An OpenAI-compatible endpoint — a router, a gateway, or the self-hosted SGLang box the
    # production profile calls for — is reached by pointing the `openai` provider somewhere else.
    # Nothing above this line changes: the engine still asks for something that returns a schema.
    base_url = get_settings().llm_base_url
    if spec.provider == "openai" and base_url and "base_url" not in kwargs:
        kwargs["base_url"] = base_url

    # A request that never answers is worse than one that fails, because nothing downstream can tell
    # the difference between slow and stopped. A gateway in front of a routed model does hang: a batch
    # of eighty calls, each answering in about thirteen seconds, ran for over an hour on one of them.
    # With a deadline the fallback chain takes over, and where there is no fallback the caller gets an
    # error it can record as "not checked" — which is a state this engine already has and knows how to
    # report honestly.
    kwargs.setdefault("timeout", REQUEST_TIMEOUT_SECONDS)
    kwargs.setdefault("max_retries", MAX_RETRIES)

    # A spec naming its own key variable has to be handed the value: the provider SDKs each read one
    # fixed variable from the environment, which is exactly the assumption a second account breaks.
    # `api_key` is the alias every one of these classes accepts, so there is no per-provider mapping
    # to keep in step. Nothing is passed for the default variable -- the SDK finds that itself -- and
    # nothing is passed for a variable that is empty, so a misconfigured entry fails as an unusable
    # provider rather than as a confusing authentication error.
    if spec.key_env and PROVIDER_ENV.get(spec.provider) is not None and "api_key" not in kwargs:
        secret = os.environ.get(spec.key_env)
        if secret:
            kwargs["api_key"] = secret

    model = init_chat_model(spec.model, model_provider=spec.provider, temperature=0, **kwargs)
    return model.with_structured_output(schema, method=spec.structured_method)


@dataclass
class _Reported:
    """A structured model that says something on the way out when a call fails.

    The engine's contract is that a failed model call becomes *not assessed* rather than a wrong
    answer, and all nine call sites already implement it: they catch, record the exception's type on
    the verdict, and carry on. What none of them can do is tell whoever is running the box, because a
    verdict is read by an advocate and a log is read by an operator. A provider refusing every call
    and a corpus with nothing to say produce the same page.

    So the report goes here rather than into nine `except` blocks: one wrapper, at the only place a
    model is built. It **re-raises**, so every caller's handling is exactly as it was and the engine's
    behaviour does not change — this only writes down the sentence nobody was writing down.

    The prompt is not logged. It carries the brief.
    """

    inner: Any
    label: str

    def invoke(self, *args: Any, **kwargs: Any):
        try:
            return self.inner.invoke(*args, **kwargs)
        except Exception as exc:
            log.warning("model call failed [%s] %s", self.label, logs.reason(exc))
            raise


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
    chain = primary.with_fallbacks(rest) if rest else primary
    # Named for the whole chain, because by the time this raises every fallback has been tried too,
    # and "all of them failed" is the fact the operator needs.
    return _Reported(chain, " → ".join(s.as_string for s in specs))


def describe_providers() -> list[tuple[str, str, bool]]:
    """(provider string, env var or '-', usable) for every configured provider, for `doctor`."""
    settings = get_settings()
    rows: list[tuple[str, str, bool]] = []
    for text in [settings.llm_primary, *settings.fallback_models]:
        spec = parse_spec(text)
        if spec is None:
            continue
        requirement = spec.env_var or ("server + model pulled" if spec.provider == "ollama" else "-")
        rows.append((spec.as_string, requirement, spec.is_available))
    return rows
