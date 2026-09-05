"""Reaching a model, and knowing when one cannot be reached.

The engine never imports a provider; it asks for something that returns a schema. What these tests
protect is the seam that makes that true: an OpenAI-compatible endpoint — a router, a gateway, or the
self-hosted server the production profile calls for — is a setting, not a code change.
"""

from __future__ import annotations

from unittest.mock import patch

import langchain.chat_models as chat_models
import pytest

from orderorder.config import get_settings
from orderorder.engine import providers
from orderorder.engine.providers import ProviderSpec, parse_spec
from orderorder.engine.schemas import ScopeAssessment


@pytest.fixture
def captured(monkeypatch):
    """Record what would have been handed to LangChain, without building anything."""
    seen: dict = {}

    def fake_init(model, model_provider=None, **kwargs):
        seen.update({"model": model, "provider": model_provider, **kwargs})

        class Built:
            def with_structured_output(self, schema, method=None):
                seen["method"] = method
                return "bound"

        return Built()

    monkeypatch.setattr(chat_models, "init_chat_model", fake_init)
    get_settings.cache_clear()
    yield seen
    get_settings.cache_clear()


def test_an_openai_compatible_endpoint_is_a_setting(captured, monkeypatch) -> None:
    """A router, a gateway, or an SGLang box: same seam, no code change."""
    monkeypatch.setenv("LLM_BASE_URL", "https://gateway.example/api/v1")
    get_settings.cache_clear()

    providers._build_one(ProviderSpec("openai", "qwen/qwen3-32b"), ScopeAssessment)
    assert captured["provider"] == "openai"
    assert captured["model"] == "qwen/qwen3-32b"
    assert captured["base_url"] == "https://gateway.example/api/v1"


def test_the_endpoint_is_not_forced_on_other_providers(captured, monkeypatch) -> None:
    """Gemini and Groq have their own hosts; pointing them at a gateway would break them."""
    monkeypatch.setenv("LLM_BASE_URL", "https://gateway.example/api/v1")
    get_settings.cache_clear()

    providers._build_one(ProviderSpec("groq", "openai/gpt-oss-120b"), ScopeAssessment)
    assert "base_url" not in captured


def test_without_the_setting_openai_means_openai(captured, monkeypatch) -> None:
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    get_settings.cache_clear()

    providers._build_one(ProviderSpec("openai", "gpt-4o-mini"), ScopeAssessment)
    assert "base_url" not in captured


def test_the_structured_output_method_travels_with_the_provider(captured, monkeypatch) -> None:
    """The engine's answers are schema-constrained; how that is asked for differs by endpoint."""
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    get_settings.cache_clear()

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


def test_no_configured_provider_yields_no_model() -> None:
    """The engine degrades to its model-free checks and says so, rather than failing at the call."""
    with patch.object(providers, "available_specs", return_value=[]):
        assert providers.build_structured(ScopeAssessment) is None
