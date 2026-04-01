"""Release-alignment checks for app surfaces, with optional local docs-repo validation."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
VERSION_TAG_RE = re.compile(r"\bv(?P<version>\d+\.\d+\.\d+)\b")
CHANGELOG_HEADER_RE = re.compile(r"^## \[(?P<version>\d+\.\d+\.\d+)\]", re.MULTILINE)
PACKAGE_VERSION_RE = re.compile(r'^__version__ = "(?P<version>\d+\.\d+\.\d+)"$', re.MULTILINE)


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _package_version() -> str:
    text = _read_text(APP_ROOT / "src" / "driftcut" / "__init__.py")
    match = PACKAGE_VERSION_RE.search(text)
    if match is None:
        msg = "Could not find __version__ in src/driftcut/__init__.py"
        raise ValueError(msg)
    return match.group("version")


def _top_changelog_version() -> str:
    text = _read_text(APP_ROOT / "CHANGELOG.md")
    match = CHANGELOG_HEADER_RE.search(text)
    if match is None:
        msg = "Could not find top changelog entry in CHANGELOG.md"
        raise ValueError(msg)
    return match.group("version")


def _version_tags(text: str) -> set[str]:
    return {f"v{match.group('version')}" for match in VERSION_TAG_RE.finditer(text)}


def _check_single_version_surface(
    errors: list[str],
    *,
    path: Path,
    expected_tag: str,
) -> None:
    found = _version_tags(_read_text(path))
    if not found:
        errors.append(f"{path} does not mention {expected_tag}.")
        return
    extra = sorted(found - {expected_tag})
    if extra:
        errors.append(
            f"{path} contains mismatched version tag(s): {', '.join(extra)} "
            f"(expected only {expected_tag})."
        )


def _check_app_surfaces() -> list[str]:
    errors: list[str] = []
    version = _package_version()
    expected_tag = f"v{version}"

    changelog_version = _top_changelog_version()
    if changelog_version != version:
        errors.append(
            "Top CHANGELOG entry does not match src/driftcut/__init__.py: "
            f"{changelog_version} != {version}."
        )

    _check_single_version_surface(
        errors,
        path=APP_ROOT / "README.md",
        expected_tag=expected_tag,
    )
    _check_single_version_surface(
        errors,
        path=APP_ROOT / "site" / "index.html",
        expected_tag=expected_tag,
    )

    return errors


def _find_local_docs_repo() -> Path | None:
    candidate = APP_ROOT.parent / "driftcut-docs"
    if candidate.exists():
        return candidate
    return None


def _check_local_docs_repo(errors: list[str], *, expected_tag: str) -> None:
    docs_repo = _find_local_docs_repo()
    if docs_repo is None:
        return

    docs_script = docs_repo / "scripts" / "check_docs_alignment.py"
    if not docs_script.exists():
        errors.append(f"Local docs repo exists at {docs_repo}, but {docs_script.name} is missing.")
        return

    completed = subprocess.run(
        [sys.executable, str(docs_script), "--expected-version", expected_tag],
        cwd=docs_repo,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode == 0:
        return

    output = completed.stdout.strip()
    error_output = completed.stderr.strip()
    details = "\n".join(part for part in [output, error_output] if part)
    if not details:
        details = "Unknown docs alignment failure."
    errors.append(
        "Local driftcut-docs repo is out of sync with the app release surfaces:\n" + details
    )


def main() -> int:
    errors = _check_app_surfaces()
    expected_tag = f"v{_package_version()}"
    _check_local_docs_repo(errors, expected_tag=expected_tag)

    if errors:
        print("Release alignment check failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    print(f"Release alignment is consistent for {expected_tag}.")
    if _find_local_docs_repo() is None:
        print("Local driftcut-docs repo not found; skipped cross-repo alignment check.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
