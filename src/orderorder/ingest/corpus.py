"""Client for the AWS Open Data judgment corpus.

`indian-supreme-court-judgments` (ap-south-1) is public, so plain anonymous HTTP is enough and no AWS
credentials or boto3 are needed. Layout:

    metadata/parquet/year=YYYY/metadata.parquet   one row per judgment, the data spine
    metadata/json/year=YYYY/<path>.json           per-judgment metadata with raw HTML
    data/tar/year=YYYY/english/english.tar        judgment text and PDFs, with english.index.json
    data/pdf/year=YYYY/english/                   individual PDFs

Licence: CC-BY-4.0. Attribution is required and lives in the README and the app footer.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import httpx
from tenacity import Retrying, retry_if_exception_type, stop_after_attempt, wait_exponential

# What is worth trying again: the connection failed, timed out, or the bucket returned a 5xx. An HTTP
# 404 is the bucket answering that the object is not there, and no amount of retrying changes that.
TRANSIENT_ERRORS = (httpx.TransportError, httpx.RemoteProtocolError)
DOWNLOAD_ATTEMPTS = 4

BUCKET = "indian-supreme-court-judgments"
REGION = "ap-south-1"
BASE_URL = f"https://{BUCKET}.s3.{REGION}.amazonaws.com"
ATTRIBUTION = (
    "Indian Supreme Court Judgments, AWS Open Data (CC-BY-4.0), "
    "https://registry.opendata.aws/indian-supreme-court-judgments/"
)

_KEY_RE = re.compile(r"<Key>([^<]+)</Key>")
_SIZE_RE = re.compile(r"<Size>(\d+)</Size>")
_PREFIX_RE = re.compile(r"<Prefix>([^<]+)</Prefix>")
_TOKEN_RE = re.compile(r"<NextContinuationToken>([^<]+)</NextContinuationToken>")
_TRUNC_RE = re.compile(r"<IsTruncated>(true|false)</IsTruncated>")


@dataclass(frozen=True)
class S3Object:
    key: str
    size: int

    @property
    def url(self) -> str:
        return f"{BASE_URL}/{self.key}"


def list_objects(
    prefix: str, *, delimiter: str | None = None, timeout: float = 60.0
) -> tuple[list[S3Object], list[str]]:
    """List objects and common prefixes under `prefix`, following continuation tokens."""
    objects: list[S3Object] = []
    prefixes: list[str] = []
    token: str | None = None
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        while True:
            params: dict[str, str] = {"list-type": "2", "prefix": prefix, "max-keys": "1000"}
            if delimiter:
                params["delimiter"] = delimiter
            if token:
                params["continuation-token"] = token
            response = client.get(BASE_URL, params=params)
            response.raise_for_status()
            body = response.text
            keys = _KEY_RE.findall(body)
            sizes = [int(s) for s in _SIZE_RE.findall(body)]
            objects.extend(S3Object(k, s) for k, s in zip(keys, sizes, strict=False))
            prefixes.extend(p for p in _PREFIX_RE.findall(body) if p != prefix)
            truncated = _TRUNC_RE.search(body)
            token_match = _TOKEN_RE.search(body)
            if truncated and truncated.group(1) == "true" and token_match:
                token = token_match.group(1)
                continue
            return objects, prefixes


def available_years() -> list[int]:
    """Years for which parquet metadata exists."""
    _, prefixes = list_objects("metadata/parquet/", delimiter="/")
    years = []
    for p in prefixes:
        m = re.search(r"year=(\d{4})/?$", p)
        if m:
            years.append(int(m.group(1)))
    return sorted(years)


def metadata_key(year: int) -> str:
    return f"metadata/parquet/year={year}/metadata.parquet"


def download(key: str, destination: Path, *, timeout: float = 600.0, chunk_size: int = 1 << 20) -> Path:
    """Stream one object to disk. Skips the download if the file already exists with a non-zero size.

    Transient network failures are retried. Fetching nine thousand judgments over a home connection
    produces a steady drizzle of DNS failures and dropped TLS handshakes — they were 184 of the 194
    losses in the first full corpus run — and each one would otherwise be recorded as a judgment whose
    PDF does not exist, which is a different and much more alarming thing.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and destination.stat().st_size > 0:
        return destination
    tmp = destination.with_suffix(destination.suffix + ".part")
    url = f"{BASE_URL}/{key}"

    for attempt in Retrying(
        retry=retry_if_exception_type(TRANSIENT_ERRORS),
        stop=stop_after_attempt(DOWNLOAD_ATTEMPTS),
        wait=wait_exponential(multiplier=0.5, max=8),
        reraise=True,
    ):
        with (
            attempt, httpx.Client(timeout=timeout, follow_redirects=True) as client,
            client.stream("GET", url) as response,
        ):
            # A 404 is an answer, not a failure to reach the bucket, so it is not retried.
            response.raise_for_status()
            with tmp.open("wb") as handle:
                for chunk in response.iter_bytes(chunk_size):
                    handle.write(chunk)
    tmp.replace(destination)
    return destination


def download_metadata(year: int, corpus_dir: Path) -> Path:
    """Fetch one year of parquet metadata into `corpus_dir/metadata/`."""
    destination = corpus_dir / "metadata" / f"year={year}_metadata.parquet"
    return download(metadata_key(year), destination)


def iter_metadata_years(years: Iterator[int] | list[int], corpus_dir: Path) -> Iterator[tuple[int, Path]]:
    for year in years:
        yield year, download_metadata(year, corpus_dir)
