"""Who may talk to the engine over HTTP.

The threat is not someone attacking the page. It is `orderorder serve --host 0.0.0.0` typed once, to
show a colleague, on a machine holding nine thousand judgments, an upload endpoint and a model key
that costs money per call. That flag is easy to type and the result is invisible: an open server looks
exactly like a closed one until somebody finds it.

So the binding decides. Loopback asks for nothing; anything else demands a token, and a server told to
listen wide with no token configured refuses to start rather than coming up open. Refusing to start is
the half that matters -- a warning at boot is read once and then lives in a scrollback nobody reads.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from orderorder.web.api import create_app
from orderorder.web.auth import BindingRefused, check_binding, is_loopback

TOKEN = "a-secret-of-your-own"


@pytest.fixture
def guarded(corpus):
    with TestClient(create_app(session_factory=corpus, token=TOKEN)) as client:
        yield client


# --- which bindings are safe ------------------------------------------------------------------------


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1", "127.0.0.5", ""])
def test_loopback_is_recognised(host: str) -> None:
    assert is_loopback(host)


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.10", "10.0.0.1", "::"])
def test_anything_else_is_not(host: str) -> None:
    assert not is_loopback(host)


def test_a_name_that_might_resolve_anywhere_is_not_loopback() -> None:
    """Guessing in the permissive direction is how a server ends up open."""
    assert not is_loopback("my-laptop.local")


# --- refusing to come up open -----------------------------------------------------------------------


def test_binding_wide_with_no_token_refuses_to_start() -> None:
    with pytest.raises(BindingRefused, match="refusing to listen"):
        check_binding("0.0.0.0", None)


def test_the_refusal_says_what_would_have_been_exposed() -> None:
    """A message that only says "no" gets worked around; one that says why gets a token set."""
    with pytest.raises(BindingRefused) as refused:
        check_binding("0.0.0.0", None)
    message = str(refused.value)
    assert "corpus" in message
    assert "ORDERORDER_API_TOKEN" in message


def test_binding_wide_with_a_token_is_allowed() -> None:
    check_binding("0.0.0.0", TOKEN)


def test_loopback_never_needs_a_token() -> None:
    check_binding("127.0.0.1", None)


# --- the token, once one is set ---------------------------------------------------------------------


def test_without_a_token_the_engine_does_not_answer(guarded) -> None:
    assert guarded.get("/api/search", params={"q": "misrepresentation"}).status_code == 401


def test_the_wrong_token_does_not_answer(guarded) -> None:
    response = guarded.get(
        "/api/search", params={"q": "misrepresentation"}, headers={"Authorization": "Bearer wrong"}
    )
    assert response.status_code == 401


def test_the_right_token_answers(guarded) -> None:
    response = guarded.get(
        "/api/search",
        params={"q": "misrepresentation"},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert response.status_code == 200


def test_the_challenge_names_the_scheme(guarded) -> None:
    assert guarded.get("/api/search", params={"q": "x"}).headers["WWW-Authenticate"] == "Bearer"


def test_the_refusal_does_not_say_which_half_was_wrong(guarded) -> None:
    """A 401 that distinguishes "no token" from "wrong token" helps somebody guess."""
    missing = guarded.get("/api/search", params={"q": "x"}).json()["detail"]
    wrong = guarded.get(
        "/api/search", params={"q": "x"}, headers={"Authorization": "Bearer wrong"}
    ).json()["detail"]
    assert missing == wrong


def test_health_answers_without_a_token(guarded) -> None:
    """A load balancer needs it, and it gives nothing away."""
    assert guarded.get("/api/health").status_code == 200


def test_the_upload_endpoint_is_covered(guarded) -> None:
    """The one that takes a file, and the reason a route-by-route token would have been a mistake."""
    response = guarded.post(
        "/api/upload", files={"file": ("brief.txt", b"some text here", "text/plain")}
    )
    assert response.status_code == 401


def test_the_page_itself_is_covered(guarded) -> None:
    assert guarded.get("/").status_code == 401


# --- and the default, which is what almost everyone runs --------------------------------------------


def test_with_no_token_configured_nothing_is_asked_for(client) -> None:
    """One laptop, bound to loopback, read-only: a login there would be ceremony."""
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/search", params={"q": "misrepresentation"}).status_code == 200
