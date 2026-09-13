#!/usr/bin/env python
"""Producer gate: a contract change without a version bump must be red.

VLT-D-007 step 2, decision point 3 (issue #604): the core's PR-CI runs a
schema diff against the latest ``contracts/vX.Y.Z`` tag and blocks a contract
change that ships without a package-version bump, and a MAJOR bump that does
not extend ``SUPPORTED_CONTRACT_VERSIONS`` (the buf pattern, in miniature).
The policy lives in ``contracts/cortxt_contracts/version.py`` and is re-read
here per run -- never duplicated.

Checked, in order:

1. **No tag yet** -- this PR is the first distribution; nothing to diff, so
   the gate passes (the repo/package congruence tests own the agreement).
2. **Version unchanged since the latest tag** -- the packaged schemas must be
   byte-identical to the tagged ones. Any change without a bump is red.
3. **Version bumped** -- a MAJOR bump must extend ``SUPPORTED_CONTRACT_VERSIONS``
   (dual acceptance is declared, never implicit), and the window must stay
   exactly N/N-1, newest first.

The tag list comes from ``git tag --list 'contracts/v*'`` in this repository,
or from ``--tags`` (CI passes the tags it resolved; tests inject). Tag blobs
are read with ``git show <tag>:<path>``; a tag that lacks a schema file counts
as "absent" and any on-disk file then counts as a change (fail-closed).

Read-only: this script never tags, never writes, never network-calls.
"""

from __future__ import annotations

import argparse
import ast
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

#: The packaged schemas the version gate diffs against the latest tag. The
#: repo-root exports (``contracts/*.schema.json``) are owned by the congruence
#: test, not here.
PACKAGED_SCHEMAS: tuple[str, ...] = (
    "dispatch-request.v1.schema.json",
    "dispatch-request.v2.schema.json",
    "dispatch-request.schema.json",
    "result-envelope.schema.json",
)

VERSION_RELPATH = "cortxt_contracts/version.py"
TAG_PREFIX = "contracts/v"
TAG_GLOB = "contracts/v*"


def _run_git(*args: str) -> str:
    """Run a read-only git command; empty stdout on any failure (fail-closed)."""
    completed = subprocess.run(  # noqa: S603 - fixed argv, no shell
        ["git", *args],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(REPO_ROOT),
    )
    return completed.stdout if completed.returncode == 0 else ""


def read_version_module(contracts_dir: Path) -> dict:
    """Return the version declarations (fail-closed, no import).

    The policy module is parsed with ``ast`` rather than imported so the gate
    never executes repository code. Returns ``{"_error": ...}`` when the
    module is missing or the declarations are unreadable.
    """
    path = contracts_dir / VERSION_RELPATH
    if not path.is_file():
        return {"_error": f"{VERSION_RELPATH} not found under {contracts_dir}"}
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError as exc:
        return {"_error": f"{path}: syntax error: {exc}"}

    values: dict = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if not isinstance(target, ast.Name):
                continue
            if target.id == "CONTRACT_PACKAGE_VERSION" and isinstance(
                node.value, ast.Constant
            ):
                values["package_version"] = str(node.value.value)
            elif target.id == "SUPPORTED_CONTRACT_VERSIONS" and isinstance(
                node.value, ast.Tuple
            ):
                entries = [
                    element.value
                    for element in node.value.elts
                    if isinstance(element, ast.Constant)
                    and isinstance(element.value, str)
                ]
                if len(entries) == len(node.value.elts):
                    values["supported"] = tuple(entries)
    if "package_version" not in values:
        values["_error"] = f"{path}: CONTRACT_PACKAGE_VERSION not found"
    return values


def latest_tag_version(tags: list[str]) -> str | None:
    """Return the newest ``contracts/vX.Y.Z`` version (semver order), or None."""
    versions: list[tuple[int, int, int]] = []
    for tag in tags:
        if not tag.startswith(TAG_PREFIX):
            continue
        parts = tag[len(TAG_PREFIX) :].split(".")
        if len(parts) != 3 or not all(part.isdigit() for part in parts):
            continue
        versions.append((int(parts[0]), int(parts[1]), int(parts[2])))
    if not versions:
        return None
    major, minor, patch = max(versions)
    return f"{major}.{minor}.{patch}"


def evaluate(
    contracts_dir: Path,
    tags: list[str],
    *,
    tag_blob: "callable | None" = None,
    packaged_bytes: "dict[str, bytes | None] | None" = None,
) -> list[str]:
    """Return the gate findings; an empty list means green.

    Args:
        contracts_dir: The repository's ``contracts/`` directory.
        tags: The ``contracts/vX.Y.Z`` tags that exist (injected).
        tag_blob: Optional ``callable(relpath) -> bytes | None`` resolving a
            path inside the latest tag. Defaults to ``git show``. Tests inject
            to stay offline and to work outside a git checkout.
        packaged_bytes: Optional override for the on-disk packaged schema
            bytes, keyed by filename (``None`` = file absent). Tests only.
    """
    findings: list[str] = []

    latest = latest_tag_version(tags)
    if latest is None:
        # No tag yet: this PR is the first distribution. The congruence tests
        # own the repo/package agreement; there is nothing to diff against.
        return findings

    version_info = read_version_module(contracts_dir)
    if "_error" in version_info:
        return [f"version module unreadable: {version_info['_error']}"]

    package_version = str(version_info["package_version"])
    supported = tuple(version_info.get("supported") or ())

    if package_version == latest:
        # Same version as the tag: the packaged schemas must be identical.
        reader = tag_blob or (
            lambda relpath: _git_blob(f"{TAG_PREFIX}{latest}", relpath)
        )
        for name in PACKAGED_SCHEMAS:
            relpath = f"contracts/cortxt_contracts/schemas/{name}"
            on_disk = contracts_dir / "cortxt_contracts" / "schemas" / name
            current = on_disk.read_bytes() if on_disk.is_file() else None
            if packaged_bytes is not None and name in packaged_bytes:
                current = packaged_bytes[name]
            tagged = reader(relpath)
            if current != tagged:
                findings.append(
                    f"packaged schema {name} changed but the package version "
                    f"was not bumped ({package_version} == tagged {latest}); "
                    "a contract change requires a version bump"
                )
        return findings

    # The package version moved. A MAJOR bump must declare dual acceptance.
    latest_major = int(latest.split(".")[0])
    current_major = int(package_version.split(".")[0])
    if current_major > latest_major and package_version not in supported:
        findings.append(
            "breaking contract change: MAJOR bump "
            f"{latest} -> {package_version} without extending "
            "SUPPORTED_CONTRACT_VERSIONS (declare dual acceptance, "
            "VLT-D-007 §3)"
        )

    # N/N-1 window policy: exactly two entries, newest first.
    if supported:
        if len(supported) != 2:
            findings.append(
                "SUPPORTED_CONTRACT_VERSIONS must be exactly N/N-1 "
                f"(two entries, newest first), got {list(supported)}"
            )
        elif supported[0] != package_version:
            findings.append(
                "SUPPORTED_CONTRACT_VERSIONS[0] must equal "
                f"CONTRACT_PACKAGE_VERSION ({package_version}), "
                f"got {supported[0]}"
            )
    return findings


def _git_blob(tag: str, relpath: str) -> bytes | None:
    """Return a file's content at ``tag``, or ``None`` when absent/failed."""
    completed = subprocess.run(  # noqa: S603 - fixed argv, no shell
        ["git", "show", f"{tag}:{relpath}"],
        capture_output=True,
        cwd=str(REPO_ROOT),
        check=False,
    )
    if completed.returncode != 0:
        return None
    return completed.stdout


def list_tags() -> list[str]:
    """The ``contracts/vX.Y.Z`` tags in this repository."""
    return [
        line.strip()
        for line in _run_git("tag", "--list", TAG_GLOB).splitlines()
        if line.strip()
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--contracts-dir",
        default=str(REPO_ROOT / "contracts"),
        help="path to the contracts directory (default: <repo>/contracts)",
    )
    parser.add_argument(
        "--tags",
        default=None,
        help=(
            "comma-separated contracts/vX.Y.Z tags; default reads "
            "'git tag --list contracts/v*' in this repository"
        ),
    )
    args = parser.parse_args(argv)

    tags = (
        [tag.strip() for tag in args.tags.split(",") if tag.strip()]
        if args.tags is not None
        else list_tags()
    )

    findings = evaluate(Path(args.contracts_dir), tags)
    if findings:
        for finding in findings:
            print(f"GATE-RED: {finding}")
        return 1
    print("GATE-GREEN: contract version policy satisfied")
    return 0


if __name__ == "__main__":
    sys.exit(main())
