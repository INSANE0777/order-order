"""What a routed gateway actually delivered during a run.

`orderorder doctor --probe` says whether one call works. It says nothing about what happens over the
eight hundred calls an evaluation makes, and with a router in front of the model that is the thing
worth knowing: a route that resolves to a rotating pool of free endpoints can answer the probe and
then rate-limit four calls in five.

This reads OmniRoute's own call logs for a window and reports what was requested, what served it, and
how often that failed. It is a diagnostic rather than part of the engine -- the engine already
records a check it could not run as "not assessed" -- but a run whose numbers came two thirds from a
fallback is a run whose numbers are about the fallback, and the report should say so.

    uv run python scripts/gateway-failure-rate.py --since 2026-09-06T00:36:07Z
    uv run python scripts/gateway-failure-rate.py --marker path/to/file   # since that file's mtime
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import glob
import json
import os
from pathlib import Path

DEFAULT_LOGS = Path(os.environ.get("ORDERORDER_DATA_DIR", "data")) / "omniroute" / "call_logs"


def read(directory: Path, since: float) -> list[dict]:
    out = []
    for path in glob.glob(str(directory / "*" / "*.json")):
        if os.path.getmtime(path) < since:
            continue
        try:
            with open(path, encoding="utf-8") as handle:
                out.append(json.load(handle))
        except Exception:  # noqa: BLE001 - a half-written log is not worth stopping for
            continue
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--logs", type=Path, default=DEFAULT_LOGS)
    parser.add_argument("--since", help="ISO timestamp, e.g. 2026-09-06T00:36:07Z")
    parser.add_argument("--marker", type=Path, help="A file whose mtime is the start of the window")
    parser.add_argument("--key", default=None, help="Only calls made with this API key name")
    args = parser.parse_args()

    if args.marker:
        since = os.path.getmtime(args.marker)
    elif args.since:
        since = dt.datetime.fromisoformat(args.since.replace("Z", "+00:00")).timestamp()
    else:
        since = 0.0

    calls = read(args.logs, since)
    if args.key:
        calls = [c for c in calls if (c.get("summary") or {}).get("apiKeyName") == args.key]
    if not calls:
        print("no calls in this window")
        return

    served = collections.Counter()
    failed = collections.Counter()
    reasons = collections.Counter()
    prompt_tokens = []
    for call in calls:
        summary = call.get("summary") or {}
        model = str(summary.get("model"))
        status = summary.get("status")
        served[model] += 1
        if call.get("error") or (isinstance(status, int) and status >= 400):
            failed[model] += 1
            reasons[f"{status}"] += 1
        tokens = (summary.get("tokens") or {}).get("in") or 0
        if tokens:
            prompt_tokens.append(tokens)

    total = len(calls)
    bad = sum(failed.values())
    print(f"{total} calls, {bad} failed ({bad / total:.0%})\n")
    print(f"  {'served by':<38}{'calls':>7}{'failed':>8}{'rate':>7}")
    for model, count in served.most_common(12):
        print(f"  {model:<38}{count:>7}{failed[model]:>8}{failed[model] / count:>7.0%}")
    print("\n  status codes on failures:", dict(reasons.most_common(8)))
    if prompt_tokens:
        prompt_tokens.sort()
        median = prompt_tokens[len(prompt_tokens) // 2]
        real = sum(1 for t in prompt_tokens if t > 800)
        print(f"\n  prompt tokens: median {median:,}, {real} calls over 800 (the engine's own prompts)")


if __name__ == "__main__":
    main()
