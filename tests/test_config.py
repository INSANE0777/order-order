"""Settings, and the one thing about them that fails silently.

`.env.example` tells a user to put their provider key in `.env`. Two different readers have to see it:
pydantic-settings, for the fields on `Settings`, and `os.environ`, for the provider keys that
`providers.is_available` and the LangChain client look up. Only the first is automatic.

When the second was missing, a key written exactly as instructed did nothing at all: `doctor` reported
"no key", the engine skipped the model, and every extent-of-support check returned "not assessed" —
identical, from the outside, to having configured nothing.
"""

from __future__ import annotations

import importlib
import os

import orderorder.config as config_module


def _reload_config_in(directory) -> None:
    """Re-import the config module with `directory` as the working directory."""
    previous = os.getcwd()
    os.chdir(directory)
    try:
        importlib.reload(config_module)
    finally:
        os.chdir(previous)


def test_a_key_in_dotenv_reaches_the_environment(tmp_path, monkeypatch) -> None:
    """The provider key is read from os.environ, not from Settings, so it has to arrive there."""
    monkeypatch.delenv("ORDERORDER_PROBE_KEY", raising=False)
    (tmp_path / ".env").write_text("ORDERORDER_PROBE_KEY=from-the-file\n", encoding="utf-8")

    _reload_config_in(tmp_path)
    assert os.environ.get("ORDERORDER_PROBE_KEY") == "from-the-file"


def test_a_real_environment_variable_wins(tmp_path, monkeypatch) -> None:
    """A shell that exports a key means it; so does a container. The file does not override them."""
    monkeypatch.setenv("ORDERORDER_PROBE_KEY", "from-the-shell")
    (tmp_path / ".env").write_text("ORDERORDER_PROBE_KEY=from-the-file\n", encoding="utf-8")

    _reload_config_in(tmp_path)
    assert os.environ["ORDERORDER_PROBE_KEY"] == "from-the-shell"


def test_settings_still_read_their_own_fields(tmp_path, monkeypatch) -> None:
    """A real environment variable outranks the file for Settings too, so clear it first."""
    monkeypatch.delenv("LLM_PRIMARY", raising=False)
    (tmp_path / ".env").write_text("LLM_PRIMARY=openai:some-model\n", encoding="utf-8")

    settings = config_module.Settings(_env_file=str(tmp_path / ".env"))
    assert settings.llm_primary == "openai:some-model"


def test_a_base_url_is_optional_and_empty_by_default(monkeypatch) -> None:
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    settings = config_module.Settings(_env_file=None)
    assert settings.llm_base_url == ""


def test_fallbacks_split_into_a_list() -> None:
    settings = config_module.Settings(_env_file=None, llm_fallbacks="groq:a, cerebras:b ,")
    assert settings.fallback_models == ["groq:a", "cerebras:b"]
