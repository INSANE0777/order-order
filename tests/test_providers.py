"""Reaching a model, and knowing when one cannot be reached.

The engine never imports a provider; it asks for something that returns a schema. What these tests
protect is the seam that makes that true: an OpenAI-compatible endpoint — a router, a gateway, or the
self-hosted server the production profile calls for — is a setting, not a code change.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import langchain.chat_models as chat_models
import pytest

from orderorder.engine import providers
from orderorder.engine.providers import ProviderSpec, parse_spec
from orderorder.engine.schemas import ScopeAssessment


@pytest.fixture
def captured(monkeypatch):
    """Record what would have been handed to LangChain, without building anything.

    Settings are stubbed rather than read, so the developer's own `.env` — which may well point at a
    local gateway — cannot decide whether these tests pass.
    """
    seen: dict = {}

    def fake_init(model, model_provider=None, **kwargs):
        seen.update({"model": model, "provider": model_provider, **kwargs})

        class Built:
            def with_structured_output(self, schema, method=None):
                seen["method"] = method
                return "bound"

        return Built()

    monkeypatch.setattr(chat_models, "init_chat_model", fake_init)

    def with_base_url(url: str) -> None:
        monkeypatch.setattr(providers, "get_settings", lambda: SimpleNamespace(llm_base_url=url))

    seen["_set_base_url"] = with_base_url
    with_base_url("")
    yield seen


def test_an_openai_compatible_endpoint_is_a_setting(captured) -> None:
    """A router, a gateway, or an SGLang box: same seam, no code change."""
    captured["_set_base_url"]("https://gateway.example/api/v1")
    providers._build_one(ProviderSpec("openai", "qwen/qwen3-32b"), ScopeAssessment)
    assert captured["provider"] == "openai"
    assert captured["model"] == "qwen/qwen3-32b"
    assert captured["base_url"] == "https://gateway.example/api/v1"


def test_the_endpoint_is_not_forced_on_other_providers(captured) -> None:
    """Gemini and Groq have their own hosts; pointing them at a gateway would break them."""
    captured["_set_base_url"]("https://gateway.example/api/v1")
    providers._build_one(ProviderSpec("groq", "openai/gpt-oss-120b"), ScopeAssessment)
    assert "base_url" not in captured


def test_without_the_setting_openai_means_openai(captured) -> None:
    providers._build_one(ProviderSpec("openai", "gpt-4o-mini"), ScopeAssessment)
    assert "base_url" not in captured


def test_the_structured_output_method_travels_with_the_provider(captured) -> None:
    """The engine's answers are schema-constrained; how that is asked for differs by endpoint."""
    providers._build_one(ProviderSpec("openai", "gpt-4o-mini"), ScopeAssessment)
    assert captured["method"] == "json_schema"

    captured.clear()
    providers._build_one(ProviderSpec("groq", "openai/gpt-oss-120b"), ScopeAssessment)
    assert captured["method"] == "function_calling"


def test_a_model_name_may_carry_slashes_and_colons() -> None:
    """Routers name models "vendor/model"; Ollama names them "model:tag"."""
    assert parse_spec("openai:qwen/qwen3-32b") == ProviderSpec("openai", "qwen/qwen3-32b")
    assert parse_spec("ollama:qwen3.5:4b") == ProviderSpec("ollama", "qwen3.5:4b")
    assert parse_spec("nonsense") is None


def test_a_spec_may_name_the_variable_holding_its_key() -> None:
    """A free tier is per account, so a second key is how a daily ceiling moves."""
    spec = parse_spec("google_genai:gemini-3.6-flash#GOOGLE_API_KEY_2")
    assert spec == ProviderSpec("google_genai", "gemini-3.6-flash", "GOOGLE_API_KEY_2")
    assert spec.env_var == "GOOGLE_API_KEY_2"
    # The variable is part of the identity, so two accounts are two rungs and not one deduped away.
    assert spec.as_string == "google_genai:gemini-3.6-flash#GOOGLE_API_KEY_2"
    assert spec.as_string != parse_spec("google_genai:gemini-3.6-flash").as_string


def test_naming_the_default_variable_is_the_same_as_not_naming_it() -> None:
    """Otherwise the two spellings are two rungs of the chain pointing at one key."""
    explicit = parse_spec("groq:openai/gpt-oss-120b#GROQ_API_KEY")
    implied = parse_spec("groq:openai/gpt-oss-120b")
    assert explicit.key_env is None
    assert explicit == implied
    assert explicit.as_string == implied.as_string


def test_the_key_suffix_survives_a_model_name_full_of_punctuation() -> None:
    """`ollama:qwen3:4b` and `groq:openai/gpt-oss-120b` are why the suffix is `#` and taken last."""
    spec = parse_spec("ollama:qwen3:4b#SOMETHING")
    assert spec.provider == "ollama"
    assert spec.model == "qwen3:4b"
    assert spec.key_env == "SOMETHING"
    assert parse_spec("groq:openai/gpt-oss-120b#K").model == "openai/gpt-oss-120b"


def test_a_second_account_is_only_usable_when_its_variable_is_set(monkeypatch) -> None:
    spec = parse_spec("google_genai:gemini-3.6-flash#GOOGLE_API_KEY_2")
    monkeypatch.delenv("GOOGLE_API_KEY_2", raising=False)
    # A key in the *default* variable does not make the second account available.
    monkeypatch.setenv("GOOGLE_API_KEY", "the-first-account")
    assert spec.is_available is False
    monkeypatch.setenv("GOOGLE_API_KEY_2", "the-second-account")
    assert spec.is_available is True


def test_the_named_key_is_handed_to_the_provider(captured, monkeypatch) -> None:
    """The SDKs each read one fixed variable, which is the assumption a second account breaks."""
    monkeypatch.setenv("GOOGLE_API_KEY_2", "second-account-key")
    providers._build_one(
        parse_spec("google_genai:gemini-3.6-flash#GOOGLE_API_KEY_2"), ScopeAssessment
    )
    assert captured["api_key"] == "second-account-key"


def test_the_default_variable_is_left_to_the_sdk(captured, monkeypatch) -> None:
    """Passing it explicitly would buy nothing and give the value one more place to be."""
    monkeypatch.setenv("GOOGLE_API_KEY", "the-only-account")
    providers._build_one(parse_spec("google_genai:gemini-3.6-flash"), ScopeAssessment)
    assert "api_key" not in captured


def test_an_empty_named_variable_passes_no_key_at_all(captured, monkeypatch) -> None:
    """Better an unusable provider than a confusing authentication error mid-run."""
    monkeypatch.setenv("GOOGLE_API_KEY_2", "")
    providers._build_one(
        parse_spec("google_genai:gemini-3.6-flash#GOOGLE_API_KEY_2"), ScopeAssessment
    )
    assert "api_key" not in captured


def test_one_provider_twice_on_two_accounts_is_two_rungs(monkeypatch) -> None:
    """The whole point: `available_specs` must not dedupe the second account away."""
    monkeypatch.setattr(
        providers,
        "get_settings",
        lambda: SimpleNamespace(
            llm_primary="google_genai:gemini-3.6-flash",
            fallback_models=[
                "google_genai:gemini-3.6-flash#GOOGLE_API_KEY_2",
                "google_genai:gemini-3.6-flash",  # a duplicate of the primary, still dropped
            ],
            llm_base_url="",
        ),
    )
    monkeypatch.setenv("GOOGLE_API_KEY", "first")
    monkeypatch.setenv("GOOGLE_API_KEY_2", "second")
    specs = providers.available_specs()
    assert [s.env_var for s in specs] == ["GOOGLE_API_KEY", "GOOGLE_API_KEY_2"]


def test_no_configured_provider_yields_no_model() -> None:
    """The engine degrades to its model-free checks and says so, rather than failing at the call."""
    with patch.object(providers, "available_specs", return_value=[]):
        assert providers.build_structured(ScopeAssessment) is None
