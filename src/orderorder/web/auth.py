"""Who may talk to the engine over HTTP.

The page binds to localhost by default and everything it serves is read-only against the knowledge
base, so on one laptop there is nothing here to protect and a login would be ceremony. The moment it
is bound to anything else that stops being true, and it stops being true in a way that is easy to
miss: `orderorder serve --host 0.0.0.0` is one flag, and the corpus, an upload endpoint and a model
key that costs real money are then reachable by anything that can route to the box.

So the rule is not "add authentication", which nobody does until after the incident. The rule is that
the binding decides:

  * bound to loopback, no token needed and none asked for;
  * bound to anything else, a token is required, and if none is configured the server refuses to
    start rather than coming up open.

Refusing to start is the important half. A warning printed at boot is read once and then lives in a
scrollback nobody reads again, and the failure it warns about is silent — an open server looks
exactly like a closed one until somebody finds it.

The token is compared with `hmac.compare_digest`, not `==`. That matters less here than the habit does.
"""

from __future__ import annotations

import hmac
import ipaddress

from fastapi import HTTPException, Request

# Where the token is read from. One name, so there is one thing to set and one thing to grep for.
TOKEN_ENV = "ORDERORDER_API_TOKEN"
# The header a client sends it in, and the scheme. Bearer, because every HTTP client already knows it.
HEADER = "Authorization"
SCHEME = "Bearer"
# Paths that answer before a token is checked. The health route says whether the corpus is loaded and
# whether a model is configured, which a load balancer needs and which gives nothing away.
OPEN_PATHS = {"/api/health"}


class BindingRefused(RuntimeError):
    """The server was asked to listen off-loopback with no token set."""


def is_loopback(host: str) -> bool:
    """Whether binding to this host exposes the server beyond this machine."""
    if host in {"localhost", ""}:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        # A name that is not an address. It might resolve to loopback and it might not, and guessing
        # in the permissive direction is how a server ends up open.
        return False


def check_binding(host: str, token: str | None) -> None:
    """Refuse to serve off-loopback without a token. Raises `BindingRefused`."""
    if is_loopback(host) or token:
        return
    raise BindingRefused(
        f"refusing to listen on {host} with no {TOKEN_ENV} set. Everything this serves would be "
        f"reachable by anything that can route here: the corpus, the upload endpoint, and a model "
        f"key that costs money to use. Set {TOKEN_ENV} to a secret of your own, or bind 127.0.0.1."
    )


def token_required(request: Request, token: str | None) -> None:
    """Raise 401 unless the request carries the token. A no-op when no token is configured."""
    if not token or request.url.path in OPEN_PATHS:
        return

    supplied = request.headers.get(HEADER, "")
    prefix = f"{SCHEME} "
    if not supplied.startswith(prefix) or not hmac.compare_digest(supplied[len(prefix) :], token):
        # No detail about which half was wrong. A 401 that distinguishes "no token" from "wrong
        # token" is a 401 that helps somebody guess.
        raise HTTPException(401, "a bearer token is required", headers={"WWW-Authenticate": SCHEME})
