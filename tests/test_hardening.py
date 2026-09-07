"""What the server refuses, and what it says on the way out.

`tests/test_auth.py` covers who may talk to the engine at all. This covers the rest of the surface: a
body sized to hurt, a file that is not a brief, a client asking faster than one worker can answer, and
the headers that decide what a browser will do with the page if any of the escaping elsewhere is ever
wrong.

The theme is that none of it is about a determined attacker with a target. This is a single-worker
process serving privileged documents on a box an advocate owns, and every limit here exists so that
one careless or automated client cannot take the queue away from the person waiting on a real answer.
"""

from __future__ import annotations

import ast
import re
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from orderorder.web import limits
from orderorder.web.api import MAX_UPLOAD_BYTES, SECURITY_HEADERS, create_app

TOKEN = "a-secret-of-your-own"


@pytest.fixture
def client(corpus):
    with TestClient(create_app(session_factory=corpus)) as c:
        yield c


@pytest.fixture
def guarded(corpus):
    with TestClient(create_app(session_factory=corpus, token=TOKEN)) as c:
        yield c


# --- the headers ------------------------------------------------------------------------------------


def test_every_response_carries_the_security_headers(client) -> None:
    response = client.get("/api/health")
    for header, value in SECURITY_HEADERS.items():
        assert response.headers.get(header) == value, header


def test_a_refusal_carries_them_too(guarded) -> None:
    """A 401 is a response a browser renders, so it needs the same policy as a 200.

    This is the one that gets forgotten: headers added by decorating the success path leave every
    error page bare, and an error page is exactly where a reflected message tends to end up.
    """
    # Not /api/health: that one is deliberately open so a load balancer can reach it.
    response = guarded.get("/api/search", params={"q": "x"}, headers={"Authorization": "Bearer wrong"})
    assert response.status_code == 401
    assert response.headers["Content-Security-Policy"] == SECURITY_HEADERS["Content-Security-Policy"]
    assert response.headers["X-Content-Type-Options"] == "nosniff"


def test_the_policy_forbids_inline_script() -> None:
    """The load-bearing line. Inline script is what an injected citation would become.

    The page's script and style live in their own files precisely so this can be asserted, and a
    change that inlines them again should fail here rather than in a browser somebody else is using.
    """
    policy = SECURITY_HEADERS["Content-Security-Policy"]
    assert "script-src 'self'" in policy
    assert "unsafe-inline" not in policy
    assert "unsafe-eval" not in policy
    assert "object-src 'none'" in policy
    assert "frame-ancestors 'none'" in policy


# --- bodies and files -------------------------------------------------------------------------------


def test_a_body_that_announces_itself_as_enormous_is_refused_unread(client) -> None:
    """Refused on the declared length, before anything is parsed.

    A header is a claim and not a fact, which is why this is only half the defence -- but the half it
    covers is free, and the other half is `_read_at_most`.
    """
    response = client.post(
        "/api/verify",
        content=b"{}",
        headers={"Content-Length": str(limits.MAX_BODY_BYTES + 1), "Content-Type": "application/json"},
    )
    assert response.status_code == 413


def test_a_file_larger_than_the_limit_is_refused(client) -> None:
    oversized = b"%PDF-1.4\n" + b"x" * MAX_UPLOAD_BYTES
    response = client.post("/api/upload", files={"file": ("brief.pdf", oversized, "application/pdf")})
    assert response.status_code == 413


def test_a_file_that_is_not_a_brief_is_refused_by_name(client) -> None:
    response = client.post(
        "/api/upload", files={"file": ("payload.exe", b"MZ\x90\x00", "application/octet-stream")}
    )
    assert response.status_code == 415
    assert ".pdf" in response.json()["detail"]


def test_the_old_doc_format_is_still_told_what_to_do(client) -> None:
    """A format a person will reasonably try gets a sentence, not a status code."""
    response = client.post(
        "/api/upload", files={"file": ("brief.doc", b"\xd0\xcf\x11\xe0", "application/msword")}
    )
    assert response.status_code == 400
    assert "docx" in response.json()["detail"]


# --- how often -------------------------------------------------------------------------------------


def test_a_client_asking_faster_than_the_worker_can_answer_is_slowed(client) -> None:
    """The one worker is the resource being protected, so the write bucket is the tight one."""
    last = None
    for _ in range(limits.WRITE_REQUESTS + 2):
        last = client.post("/api/verify", json={"text": "no citations here", "use_model": False})
    assert last is not None and last.status_code == 429
    assert int(last.headers["Retry-After"]) >= 1


def test_reading_is_allowed_more_often_than_starting_work(client) -> None:
    """Polling a job is not the same cost as starting one, and the limits say so."""
    assert limits.DEFAULT_REQUESTS > limits.WRITE_REQUESTS
    for _ in range(limits.WRITE_REQUESTS + 2):
        assert client.get("/api/health").status_code == 200


def test_wrong_tokens_are_limited_harder_than_requests(guarded) -> None:
    """Not because the token is guessable -- it is 32 random bytes -- but so the log stays readable."""
    codes = [
        guarded.get("/api/search", params={"q": "x"}, headers={"Authorization": "Bearer wrong"}).status_code
        for _ in range(limits.AUTH_FAILURES + 2)
    ]
    assert 401 in codes
    assert codes[-1] == 429
    assert limits.AUTH_FAILURES < limits.WRITE_REQUESTS


def test_a_wrong_token_is_refused_before_it_is_told_it_is_wrong(guarded) -> None:
    """Once over the limit the answer stops distinguishing a bad token from too many tries."""
    for _ in range(limits.AUTH_FAILURES + 3):
        response = guarded.get(
            "/api/search", params={"q": "x"}, headers={"Authorization": "Bearer wrong"}
        )
    assert response.status_code == 429
    assert "token" not in response.json()["detail"].lower()


# --- the counter itself ------------------------------------------------------------------------------


def test_the_window_resets() -> None:
    # Windows resolves the clock to about 15 ms, so the window and the wait are given a margin well
    # clear of it. A tighter one measures the timer rather than the limiter and fails at random.
    limiter = limits.RateLimiter(requests=2, window=0.2)
    assert limiter.allow("a") is None
    assert limiter.allow("a") is None
    assert limiter.allow("a") is not None
    time.sleep(0.35)
    assert limiter.allow("a") is None


def test_clients_and_buckets_are_counted_apart() -> None:
    limiter = limits.RateLimiter(requests=1, window=60)
    assert limiter.allow("a", "read") is None
    assert limiter.allow("a", "read") is not None
    assert limiter.allow("b", "read") is None, "one client's flood must not refuse another"
    assert limiter.allow("a", "write") is None, "a bucket is a separate budget"


def test_expired_windows_are_pruned() -> None:
    """The dictionary is keyed by client address, so without pruning it is a leak somebody can grow."""
    limiter = limits.RateLimiter(requests=5, window=0.2)
    for n in range(50):
        limiter.allow(f"10.0.0.{n}")
    assert len(limiter) == 50
    time.sleep(0.35)
    assert limiter.prune() == 50
    assert len(limiter) == 0


def test_a_forwarded_for_header_cannot_split_one_client_into_many(client) -> None:
    """Trusting that header is how a limiter stops being one. It is not read, so it changes nothing."""
    codes = []
    for n in range(limits.WRITE_REQUESTS + 2):
        codes.append(
            client.post(
                "/api/verify",
                json={"text": "no citations", "use_model": False},
                headers={"X-Forwarded-For": f"10.0.0.{n}"},
            ).status_code
        )
    assert 429 in codes


# --- the page the policy describes ------------------------------------------------------------------

STATIC_DIR = Path(__file__).resolve().parents[1] / "src" / "orderorder" / "web" / "static"


def _page() -> str:
    """The markup with comments stripped, since a comment cannot execute."""
    return re.sub(r"<!--.*?-->", "", (STATIC_DIR / "index.html").read_text(encoding="utf-8"), flags=re.S)


def test_the_page_has_no_inline_script() -> None:
    """`script-src 'self'` is only a defence while this stays true.

    A page that inlines its script needs `unsafe-inline`, and `unsafe-inline` is what makes an
    injected `<script>` in a citation or a party name executable. Splitting the page into three files
    is what buys the strict policy, so the split is asserted rather than trusted to survive.
    """
    assert not re.search(r"<script(?![^>]*\bsrc=)[^>]*>\s*\S", _page())


def test_the_page_has_no_inline_style() -> None:
    """Same argument, one notch quieter: `style-src` governs `style=` attributes as well as blocks."""
    page = _page()
    assert "<style" not in page
    assert not re.search(r"\sstyle\s*=", page)


def test_nothing_generated_carries_an_inline_style_either() -> None:
    """The templates in app.js build markup too, and the policy does not care who wrote it."""
    assert not re.search(r"\sstyle\s*=", (STATIC_DIR / "app.js").read_text(encoding="utf-8"))


def test_no_inline_event_handlers() -> None:
    """An `onclick=` attribute is inline script by another name, and CSP treats it as one."""
    assert not re.search(r"\son(click|load|error|submit|change|input|mouse\w+)\s*=", _page(), re.I)


def test_the_script_does_not_evaluate_strings() -> None:
    script = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    assert not re.search(r"\beval\s*\(|new\s+Function\s*\(", script)


def test_escaping_covers_the_single_quote() -> None:
    """`escape` is the last line before the DOM, so it has to cover the quote a future attribute uses.

    The version before this covered `& < > "` and not `'`, which was safe only because every attribute
    it fed happened to be double-quoted -- a property of the current templates rather than of the
    escaping, and the sort of thing that stops being true in a hurry.
    """
    script = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    assert "&#39;" in script


def test_every_class_the_page_uses_is_styled() -> None:
    """A class that lost its rule is invisible in a way no test would otherwise notice."""
    css = (STATIC_DIR / "app.css").read_text(encoding="utf-8")
    script = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    used: set[str] = set()
    for source, pattern in ((_page(), r'class="([^"]*)"'), (script, r'class="([^"$]*)"')):
        for match in re.finditer(pattern, source):
            used |= {c for c in match.group(1).split() if c}
    defined = set(re.findall(r"\.([a-zA-Z][\w-]*)", css))
    assert not (used - defined), f"styled nowhere: {sorted(used - defined)}"


def test_the_stylesheet_and_script_are_served(client) -> None:
    for path, kind in (("/app.css", "text/css"), ("/app.js", "text/javascript")):
        response = client.get(path)
        assert response.status_code == 200, path
        assert kind in response.headers["content-type"]
        assert response.headers["Content-Security-Policy"]


# --- the queries ------------------------------------------------------------------------------------

SRC = Path(__file__).resolve().parents[1] / "src"

# Names that may be built into a SQL string, because they are module constants written here rather
# than anything a caller supplies. Adding to this list is a decision; growing it by accident is what
# this test exists to stop.
SQL_SAFE_INTERPOLATIONS = {"FTS_TABLE", "belongs"}


def test_no_caller_value_is_ever_formatted_into_sql() -> None:
    """Parameterisation, checked by reading the code rather than by trusting the habit.

    SQLAlchemy does the binding everywhere it is used as an ORM, and the handful of raw statements
    bind their parameters too. What a grep cannot see is the difference between interpolating a table
    name -- a constant in this module -- and interpolating a search term. So this walks the syntax
    tree, finds every SQL string built with an f-string, and asserts that what goes into the braces is
    on a list of things that are ours.
    """
    offenders: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and getattr(node.func, "id", "") in {"sql_text", "text"}):
                continue
            for argument in node.args:
                if not isinstance(argument, ast.JoinedStr):
                    continue
                for piece in argument.values:
                    if not isinstance(piece, ast.FormattedValue):
                        continue
                    name = ast.unparse(piece.value)
                    if name not in SQL_SAFE_INTERPOLATIONS:
                        offenders.append(f"{path.name}:{node.lineno} interpolates {name!r}")
    assert not offenders, "SQL built from something that is not a constant:\n  " + "\n  ".join(offenders)


def test_every_element_the_script_reaches_for_exists_in_the_page() -> None:
    """The page and the script are separate files now, so they can drift apart silently.

    A missing id does not raise anything a user sees: `$("board").innerHTML = ...` throws once, in a
    console nobody has open, and the surface simply does nothing. This is the check that the split
    into three files did not lose an element, and that the next edit to the markup does not either.
    """
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    script = (STATIC_DIR / "app.js").read_text(encoding="utf-8")

    present = set(re.findall(r'\bid="([^"]+)"', html))
    # Ids the script builds into the markup it generates, which the page cannot be expected to hold.
    generated = set(re.findall(r"id=[\'\"]+([a-z-]+)[\'\"]", script))
    # `$("view-" + name)` is composed at runtime, so the literal never appears.
    composed = {f"view-{name}" for name in ("check", "find", "draft")}

    wanted = set(re.findall(r'\$\("([^"]+)"\)', script))
    missing = sorted(wanted - present - generated - composed)
    assert not missing, f"the script reaches for elements the page does not have: {missing}"


# --- the palette ------------------------------------------------------------------------------------

# Foreground, background, what renders that way, and the WCAG minimum. 4.5 for text; 3.0 for large
# text and for the edge that identifies a control (1.4.11). Decorative hairlines carry no duty and are
# deliberately absent -- a divider between two table rows is not information.
CONTRAST_PAIRS = [
    ("ink", "bg", "body text on the cream page", 4.5),
    ("ink", "surface", "body text on a card", 4.5),
    ("ink-2", "bg", "navigation, secondary prose", 4.5),
    ("ink-2", "surface", "a finding's detail", 4.5),
    ("muted", "bg", "hints on the page", 4.5),
    ("muted", "surface", "hints and captions on a card", 4.5),
    ("faint", "surface", "paragraph labels", 4.5),
    ("faint", "bg", "placeholder text", 4.5),
    ("accent", "bg", "links, the folder tab label", 4.5),
    ("accent", "surface", "the index heading, links on a card", 4.5),
    ("accent-ink", "accent", "cream on the cobalt block, the button label", 4.5),
    ("bg", "ink", "the label on the thumb of the surface control", 4.5),
    ("coral", "surface", "the numeral, as large text", 3.0),
    ("coral-deep", "surface", "the brand red where it must be read", 4.5),
    ("good", "surface", "verified-quote text, grade A/B mark", 4.5),
    ("warn", "surface", "grade C mark, quoted-voice tag", 4.5),
    ("bad", "surface", "a finding's heading, finding chip", 4.5),
    ("bad", "bg", "a finding chip against the cream", 4.5),
    ("unchecked", "surface", "the not-checked mark", 4.5),
    ("edge", "bg", "control boundaries on the page", 3.0),
    ("edge", "surface", "control boundaries on a card", 3.0),
]


def _palettes() -> dict[str, dict[str, str]]:
    css = (STATIC_DIR / "app.css").read_text(encoding="utf-8")

    def grab(block: str) -> dict[str, str]:
        return dict(re.findall(r"--([\w-]+):\s*(#[0-9a-fA-F]{6});", block))

    light = grab(re.search(r":root \{(.*?)\n\}", css, re.S).group(1))
    dark = grab(re.search(r"prefers-color-scheme: dark\).*?:root \{(.*?)\n\s*\}", css, re.S).group(1))
    return {"light": light, "dark": {**light, **dark}}


def _contrast(one: str, two: str) -> float:
    def luminance(colour: str) -> float:
        channels = (int(colour[i : i + 2], 16) / 255 for i in (1, 3, 5))
        linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

    first, second = luminance(one), luminance(two)
    return (max(first, second) + 0.05) / (min(first, second) + 0.05)


def test_every_rendered_pair_meets_wcag_in_both_themes() -> None:
    """Contrast, measured rather than judged by eye.

    A palette chosen for its mood is a palette nobody has checked. This one was: `--faint` measured
    3.36 against a card and carried the card labels and every empty state, and the quiet button's
    border measured 1.83 while being the only thing that said it was a button. Both were invisible
    until something computed them, and both are the sort of thing that degrades again silently.
    """
    failures = []
    for theme, palette in _palettes().items():
        for foreground, background, what, minimum in CONTRAST_PAIRS:
            assert foreground in palette and background in palette, f"{theme}: {foreground}/{background}"
            ratio = _contrast(palette[foreground], palette[background])
            if ratio < minimum:
                failures.append(f"{theme}: {what} ({foreground} on {background}) {ratio:.2f} < {minimum}")
    assert not failures, "contrast below WCAG:\n  " + "\n  ".join(failures)
