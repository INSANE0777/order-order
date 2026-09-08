"""That an outage leaves a trace an operator can find.

Every degraded check in this engine already tells the advocate: `review_reason` on the verdict says
the model could not be reached, and the verdict is *not assessed* rather than a guess. That is the
correctness property and it is tested in `test_outage.py`. This file tests the operability one, which
is different and was missing: whoever is running the box has to be able to tell "the corpus has
nothing to say about this" from "the model has been down since Tuesday", and reading every verdict is
not a way to do that.

The rule that constrains all of it: **a prompt is never logged.** It carries the brief, an uploaded
brief is privileged, and the one guarantee this deployment makes about it is that it is not stored.
"""

from __future__ import annotations

import logging

import pytest

from orderorder import logs
from orderorder.engine.providers import _Reported


class _Wedged:
    """A model that fails the way a rate-limited provider fails: every call, immediately."""

    def invoke(self, prompt, *args, **kwargs):
        raise RuntimeError("429 Too Many Requests")


class _Answering:
    def invoke(self, prompt, *args, **kwargs):
        return {"support": "full"}


def test_a_failed_model_call_is_reported_once_and_re_raised(caplog) -> None:
    """Re-raised, because every caller already turns this into 'not assessed' and must keep doing so."""
    model = _Reported(_Wedged(), "google_genai:gemini-2.5-flash → groq:openai/gpt-oss-120b")
    with caplog.at_level(logging.WARNING, logger=logs.LOGGER_NAME), pytest.raises(RuntimeError):
        model.invoke("some prompt")

    assert len(caplog.records) == 1, "one call, one line; a retry storm should not become a log storm"
    said = caplog.text
    assert "model call failed" in said
    assert "429" in said, "the operator needs the reason, not just that something went wrong"
    assert "gemini-2.5-flash" in said and "gpt-oss-120b" in said, "name the whole chain that failed"


def test_a_working_model_says_nothing(caplog) -> None:
    """The wrapper is on the failure path only; a healthy engine does not narrate itself."""
    model = _Reported(_Answering(), "openai:gpt-oss-20b")
    with caplog.at_level(logging.WARNING, logger=logs.LOGGER_NAME):
        assert model.invoke("some prompt") == {"support": "full"}
    assert caplog.records == []


def test_the_prompt_is_never_logged(caplog) -> None:
    """A prompt carries the brief. The brief is privileged and is not stored; a log would store it."""
    secret = "the appellant admits the payment was made to conceal the transaction"
    model = _Reported(_Wedged(), "openai:gpt-oss-20b")
    with caplog.at_level(logging.DEBUG, logger=logs.LOGGER_NAME), pytest.raises(RuntimeError):
        model.invoke(f"Read this and answer: {secret}")
    assert secret not in caplog.text
    assert "appellant" not in caplog.text


def test_a_long_provider_error_is_cut_before_it_reaches_the_log() -> None:
    """Some clients echo the request back in the error string. The cap is cheaper than trusting them."""
    long = RuntimeError("x" * 5_000)
    written = logs.reason(long)
    assert len(written) <= logs.MAX_REASON_CHARS
    assert written.startswith("RuntimeError: ")


def test_a_reason_is_one_line() -> None:
    """A multi-line traceback in the message would break one event into many lines of log."""
    assert "\n" not in logs.reason(ValueError("first line\nsecond line"))


def test_configuring_twice_does_not_double_every_line() -> None:
    """`configure` is called by `serve` and by the app factory, so it has to be idempotent."""
    logs.configure()
    logger = logging.getLogger(logs.LOGGER_NAME)
    before = len(logger.handlers)
    logs.configure()
    logs.configure()
    assert len(logger.handlers) == before
    assert logger.propagate is False, "propagating would print every line a second time under uvicorn"
