"""Release-state checks for tags, GitHub releases, and live public surfaces."""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

APP_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_VERSION_RE = re.compile(r'^__version__ = "(?P<version>\d+\.\d+\.\d+)"$', re.MULTILINE)
DEFAULT_REPO = "riccardomerenda/driftcut"
DEFAULT_LANDING_URL = "https://driftcut.dev"
DEFAULT_DOCS_URL = "https://docs.driftcut.dev"


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _package_version() -> str:
    text = _read_text(APP_ROOT / "src" / "driftcut" / "__init__.py")
    match = PACKAGE_VERSION_RE.search(text)
    if match is None:
        msg = "Could not find __version__ in src/driftcut/__init__.py"
        raise ValueError(msg)
    return str(match.group("version"))


def _http_get_json(url: str) -> dict[str, Any]:
    request = Request(url, headers={"User-Agent": "driftcut-release-audit"})
    with urlopen(request, timeout=15) as response:  # noqa: S310 - controlled release-audit URL
        payload = response.read().decode("utf-8")
    data = json.loads(payload)
    if not isinstance(data, dict):
        msg = f"Expected a JSON object from {url}"
        raise ValueError(msg)
    return data


def _http_get_text(url: str) -> str:
    request = Request(url, headers={"User-Agent": "driftcut-release-audit"})
    with urlopen(request, timeout=15) as response:  # noqa: S310 - controlled release-audit URL
        payload = response.read().decode("utf-8", errors="replace")
    return str(payload)


def _release_exists(repo: str, tag: str) -> bool:
    url = f"https://api.github.com/repos/{repo}/releases/tags/{tag}"
    try:
        _http_get_json(url)
    except HTTPError as exc:
        if exc.code == 404:
            return False
        raise
    return True


def _tag_exists(repo: str, tag: str) -> bool:
    url = f"https://api.github.com/repos/{repo}/git/ref/tags/{tag}"
    try:
        _http_get_json(url)
    except HTTPError as exc:
        if exc.code == 404:
            return False
        raise
    return True


def _latest_release_tag(repo: str) -> str:
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    data = _http_get_json(url)
    tag_name = data.get("tag_name")
    if not isinstance(tag_name, str):
        msg = f"GitHub latest release for {repo} does not include tag_name"
        raise ValueError(msg)
    return str(tag_name)


def _public_surface_contains_version(url: str, expected_tag: str) -> bool:
    return expected_tag in _http_get_text(url)


def _check_release_state(
    *,
    repo: str,
    expected_tag: str,
    landing_url: str,
    docs_url: str,
) -> list[str]:
    errors: list[str] = []

    try:
        if not _tag_exists(repo, expected_tag):
            errors.append(f"Remote git tag {expected_tag} does not exist for {repo}.")
    except (HTTPError, URLError, ValueError) as exc:
        errors.append(f"Could not verify remote git tag {expected_tag}: {exc}")

    try:
        if not _release_exists(repo, expected_tag):
            errors.append(f"GitHub release {expected_tag} does not exist for {repo}.")
    except (HTTPError, URLError, ValueError) as exc:
        errors.append(f"Could not verify GitHub release {expected_tag}: {exc}")

    try:
        latest_tag = _latest_release_tag(repo)
        if latest_tag != expected_tag:
            errors.append(
                "GitHub latest release is "
                f"{latest_tag}, but local package version is {expected_tag}."
            )
    except (HTTPError, URLError, ValueError) as exc:
        errors.append(f"Could not verify latest GitHub release for {repo}: {exc}")

    for label, url in (("landing page", landing_url), ("docs site", docs_url)):
        try:
            if not _public_surface_contains_version(url, expected_tag):
                errors.append(f"Live {label} at {url} does not mention {expected_tag}.")
        except (HTTPError, URLError) as exc:
            errors.append(f"Could not fetch live {label} at {url}: {exc}")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--expected-version",
        help="Expected version tag such as v0.6.0. Defaults to src/driftcut/__init__.py.",
    )
    parser.add_argument("--repo", default=DEFAULT_REPO, help="GitHub repo slug, owner/name.")
    parser.add_argument("--landing-url", default=DEFAULT_LANDING_URL)
    parser.add_argument("--docs-url", default=DEFAULT_DOCS_URL)
    parser.add_argument("--retries", type=int, default=1, help="Number of audit attempts.")
    parser.add_argument(
        "--delay-seconds",
        type=float,
        default=10.0,
        help="Delay between attempts when retries > 1.",
    )
    args = parser.parse_args()

    expected_tag = args.expected_version or f"v{_package_version()}"
    attempts = max(args.retries, 1)

    last_errors: list[str] = []
    for attempt in range(1, attempts + 1):
        last_errors = _check_release_state(
            repo=args.repo,
            expected_tag=expected_tag,
            landing_url=args.landing_url,
            docs_url=args.docs_url,
        )
        if not last_errors:
            print(f"Release state is consistent for {expected_tag}.")
            return 0
        if attempt < attempts:
            time.sleep(args.delay_seconds)

    print("Release state check failed:", file=sys.stderr)
    for error in last_errors:
        print(f"- {error}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
