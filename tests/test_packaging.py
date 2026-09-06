"""What the shipping artifacts promise each other.

None of this is exercised by running the engine, which is why it breaks quietly. The image's
`ENTRYPOINT` is a console script that lives in `pyproject.toml`; the page the web layer serves is a
data file that only reaches an installed copy if the build carries it; and the container's whole
security story is one Compose line that must not acquire a default.

The wheel one is not hypothetical. `force-include` pointed at `src/orderorder/web/static`, which is
already inside the packaged `src/orderorder`, so hatchling was handed the same archive path twice and
refused to build at all -- `A second file is being added to the wheel archive at the same path`. The
engine ran fine from an editable install the whole time. The first thing to notice was the container
build failing, which is a slow way to find out.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def pyproject() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def test_the_script_the_image_runs_is_the_one_the_project_declares(pyproject) -> None:
    """The Dockerfile's ENTRYPOINT is `orderorder` and nothing checks that at build time."""
    scripts = pyproject["project"]["scripts"]
    assert scripts["orderorder"] == "orderorder.cli:app"

    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert 'ENTRYPOINT ["orderorder"]' in dockerfile


def test_no_forced_include_duplicates_a_packaged_directory(pyproject) -> None:
    """Two ways to put one file in the wheel is not redundancy; it is a build that does not run."""
    wheel = pyproject.get("tool", {}).get("hatch", {}).get("build", {}).get("targets", {}).get("wheel", {})
    packages = [Path(p) for p in wheel.get("packages", [])]
    forced = [Path(source) for source in wheel.get("force-include", {})]

    for source in forced:
        for package in packages:
            assert not source.is_relative_to(package), (
                f"{source} is inside the packaged {package}; hatchling ships it once already and "
                f"force-including it adds a second entry at the same archive path, which fails the build"
            )


def test_the_page_is_inside_the_packaged_directory() -> None:
    """It is data rather than code, so nothing imports it and nothing notices when it is not shipped."""
    assert (ROOT / "src" / "orderorder" / "web" / "static" / "index.html").is_file()


def test_the_image_never_receives_a_key() -> None:
    """A key in a layer is published to whoever can pull the image, and `docker history` keeps it."""
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    copied = re.findall(r"^COPY\s+(.*)$", dockerfile, flags=re.MULTILINE)
    assert not any(".env" in line for line in copied), "the Dockerfile copies a .env into a layer"
    assert not re.search(r"^ARG\s+\w*(KEY|TOKEN|SECRET)", dockerfile, flags=re.MULTILINE | re.IGNORECASE)

    ignored = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    assert ".env" in ignored, "build context includes .env; it only takes one stray COPY . after that"


def test_the_container_token_has_no_default() -> None:
    """Compose fills an unset variable with an empty string, and an empty token is no token."""
    compose = (ROOT / "infra" / "docker-compose.yml").read_text(encoding="utf-8")
    declaration = re.search(r"ORDERORDER_API_TOKEN:\s*\"\$\{ORDERORDER_API_TOKEN([^}]*)\}\"", compose)
    assert declaration, "the serve profile does not pass the token through at all"
    # `:?` is the form that stops the stack; `:-` or `-` would hand it a default and start it open.
    assert declaration.group(1).startswith(":?"), (
        "the token has a default, so a stack brought up with none set would serve the corpus openly"
    )


def test_the_health_route_is_what_the_container_probes() -> None:
    """The health check is the one request made without a token; the exemption lives in auth.py."""
    from orderorder.web.auth import OPEN_PATHS

    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    probed = re.search(r"HEALTHCHECK.*?http://[\d.]+:\d+(/\S*?)['\"]", dockerfile, flags=re.DOTALL)
    assert probed, "no health check in the Dockerfile"
    assert probed.group(1) in OPEN_PATHS
