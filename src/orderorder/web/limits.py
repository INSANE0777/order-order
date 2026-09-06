"""How often one client may ask, and how much it may send.

Three separate concerns end up here because they share a reason: everything this server does is
expensive in a way an ordinary web application's routes are not. Checking a brief parses citations,
runs full-text search over four hundred thousand paragraphs and may call a metered language model. A
single-worker process (see `docs/DEPLOYMENT.md` §2.3) serves them one at a time. So the cost of an
unauthenticated flood is not a large bill, it is that the advocate waiting on a real answer does not
get one.

**Why counting in this process is the right size.** A shared counter in Redis is the correct answer
for a horizontally scaled service, and this is deliberately not one: jobs live in a dictionary in this
process, and the deployment note says to run exactly one worker for that reason. A limiter that needs
infrastructure the rest of the design refuses would be answering a question nobody here is asking. If
that changes, this is the piece to replace, and it is small on purpose.

**Fixed windows, not a token bucket.** A window that resets lets a client burst at the boundary, which
is the standard objection, and it does not matter for what this is defending: the aim is that nobody
holds the queue for minutes, not that request timing is smooth. Fixed windows are also legible -- a
person reading `60 requests a minute` knows what happened -- and legibility is worth more here than
smoothing.

**Failed authentication is counted separately and far harder.** A wrong token is not a request that
happens to be expensive; it is somebody looking for the door. The token is 32 random bytes and cannot
be guessed inside the heat death of the universe, so this is not really about guessing. It is about
the log: a machine that may make five wrong guesses a minute produces an audit trail somebody can
read, and one that may make ten thousand produces noise.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

# What a person driving the page actually does: a burst of clicks, a job, some polling. Well clear of
# that, and well under what would keep the one worker busy.
DEFAULT_REQUESTS = 120
DEFAULT_WINDOW = 60.0
# Starting a job is the expensive one, and no human starts twenty verifications a minute.
WRITE_REQUESTS = 20
# A wrong token. Low, and deliberately so.
AUTH_FAILURES = 5
AUTH_WINDOW = 60.0

# Requests whose method changes something or starts work, as opposed to reading a result.
WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


@dataclass
class _Window:
    started: float
    count: int = 0


@dataclass
class RateLimiter:
    """Fixed-window request counting, per client and per bucket.

    `allow` returns the seconds to wait when a client is over its limit, and `None` when it is not, so
    the caller can put a `Retry-After` on the refusal rather than a bare 429.
    """

    requests: int = DEFAULT_REQUESTS
    window: float = DEFAULT_WINDOW
    _windows: dict[tuple[str, str], _Window] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def allow(self, client: str, bucket: str = "read", *, limit: int | None = None) -> float | None:
        """`None` if the request may proceed, else how many seconds until it may."""
        ceiling = self.requests if limit is None else limit
        now = time.monotonic()
        key = (client, bucket)
        with self._lock:
            current = self._windows.get(key)
            if current is None or now - current.started >= self.window:
                self._windows[key] = _Window(started=now, count=1)
                return None
            current.count += 1
            if current.count > ceiling:
                return max(0.0, self.window - (now - current.started))
            return None

    def forget(self, client: str, bucket: str = "read") -> None:
        """Drop a client's window. Used when a request turns out to have been authorised after all."""
        with self._lock:
            self._windows.pop((client, bucket), None)

    def prune(self, *, now: float | None = None) -> int:
        """Drop windows that have expired. Returns how many went.

        Without this the dictionary is a slow memory leak keyed by client address, which is a thing an
        attacker can grow on purpose. Called on a schedule rather than per request so that the common
        path stays two dictionary operations.
        """
        moment = time.monotonic() if now is None else now
        with self._lock:
            dead = [k for k, w in self._windows.items() if moment - w.started >= self.window]
            for key in dead:
                del self._windows[key]
            return len(dead)

    def __len__(self) -> int:
        with self._lock:
            return len(self._windows)


def client_of(request) -> str:
    """Who to count this request against.

    `request.client.host` and nothing else. A proxy's `X-Forwarded-For` is a header, which is to say
    it is whatever the client wrote in it, and trusting it lets one machine appear as a thousand and
    empty every limit here. Behind a reverse proxy that means the limit applies to the proxy, which is
    the honest failure: it is visible, rather than a limit that silently is not one. A deployment that
    wants per-client limits behind a proxy should set them in the proxy, which is the only place that
    knows which hop to believe.
    """
    client = getattr(request, "client", None)
    return getattr(client, "host", None) or "unknown"


# Bodies. The size checks in the routes run after the body has been parsed into memory, which is too
# late for a body whose only purpose is to be large. This is the number the middleware refuses at.
MAX_BODY_BYTES = 30_000_000
