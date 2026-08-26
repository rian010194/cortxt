#!/usr/bin/env python3
"""session_inbox_contract.py -- validate the lab/inbox/ session-coordination contract.

Read-only checker for the workspace-local session inbox described in
AGENTS.md ("Session injection (workspace-local coordination)") and
lab/DESIGN-session-injection.md. `lab/inbox/` lives outside this repository
(workspace-local, never tracked), so this tool never writes to it and never
moves, deletes, or renames a message file -- it only reads and reports.

What it checks, for every `*.md` message file under `<lab-root>/**` (except
files named `README.md`, which are documentation, not messages):

- YAML frontmatter is present and parses.
- The required fields are present and non-empty: `from`, `to`, `type`,
  `created`, `artifact`, `affects`.
- `type` is one of `delivery`, `request`, `handoff`.
- The message contains zero a/o/u-with-diacritics (aa/ao/ou umlauts:
  a-with-diaeresis/ring, o-with-diaeresis -- the contract requires English).
- `artifact` resolves to an existing path, when it names one. A URL artifact
  (PR links, docs links) is recognized and skipped -- this tool never makes
  a network call and never opens/reads an artifact's contents, only checks
  filesystem existence via `Path.exists()`.

Root resolution has two distinct failure modes, deliberately not conflated:

- `--lab-root` given explicitly, but it does not exist or does not
  structurally look like an inbox root (no `done/` directory and no
  mailbox subdirectory containing `in/` or `out/`) -> `wrong_root`. The
  operator pointed at something; that something is not this contract's
  shape.
- `--lab-root` omitted and auto-discovery (walking up from `--start`,
  default the repository root, looking for `<parent>/lab/inbox`) finds
  nothing anywhere up to the filesystem root -> `missing`. There is simply
  no inbox to check.

Severity: active messages (anything outside `done/`) are checked strictly: a
frontmatter problem, missing/empty required field, or invalid `type` is an
`error` and fails the run (exit 1). Messages already archived under `done/`
are legacy evidence: the same findings remain visible but are downgraded to
warnings. A stale `artifact` path or a diacritics hit is always a warning.
This policy never rewrites historical messages.

Usage:
    python scripts/session_inbox_contract.py [--lab-root PATH]
        [--workspace-root PATH] [--start PATH] [--stop-at PATH] [--json]

Exit codes: 0 = clean (only warnings, if any), 1 = one or more errors,
2 = root/boundary resolution failed (`missing`, `wrong_root`,
`invalid_stop_at`, or `wrong_workspace_root`).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml

REQUIRED_FIELDS = ("from", "to", "type", "created", "artifact", "affects")
MESSAGE_TYPES = frozenset({"delivery", "request", "handoff"})
DIACRITICS_RE = re.compile(r"[åäöÅÄÖ]")
URL_RE = re.compile(r"https?://\S+")
FRONTMATTER_RE = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n?", re.DOTALL)


def _looks_like_inbox(path: Path) -> bool:
    """Structural check: does `path` look like a lab/inbox root?

    True if it is a directory containing a `done/` subdirectory, or at
    least one immediate subdirectory that itself has an `in/` or `out/`
    mailbox directory. Deliberately does not require any specific mailbox
    name -- mailboxes are created per session.
    """
    if not path.is_dir():
        return False
    if (path / "done").is_dir():
        return True
    try:
        children = list(path.iterdir())
    except OSError:
        return False
    for child in children:
        if not child.is_dir():
            continue
        if (child / "in").is_dir() or (child / "out").is_dir():
            return True
    return False


def discover_lab_root(start: Path, stop_at: Path | None = None) -> Path | None:
    """Walk `start` and its parents looking for a `lab/inbox` that passes
    the structural check. Returns None if none is found up to the
    filesystem root, or up to and including `stop_at` when given.

    `stop_at` is a bounded-discovery seam for deterministic tests: without
    it, discovery walking up from a scratch directory inside this
    repository would keep climbing past the repository root and find the
    real workspace-local `lab/inbox` (workspace-local, never tracked), which
    would make "auto-discovery finds nothing" tests non-deterministic and
    would risk a test ever touching the live inbox. Production callers
    (the CLI default) leave it unset and walk to the filesystem root, which
    is required because `lab/inbox` genuinely lives above the repository
    root in the real workspace layout.
    """
    current = start.resolve()
    stop = stop_at.resolve() if stop_at is not None else None
    if stop is not None and stop != current and stop not in current.parents:
        raise ValueError(f"stop_at must be start or one of its ancestors: {stop}")
    seen = set()
    while current not in seen:
        seen.add(current)
        candidate = current / "lab" / "inbox"
        if candidate.exists() and _looks_like_inbox(candidate):
            return candidate
        if stop is not None and current == stop:
            break
        if current.parent == current:
            break
        current = current.parent
    return None


def resolve_lab_root(
    explicit: Path | None, start: Path, stop_at: Path | None = None
) -> tuple[Path | None, str | None]:
    """Resolve the lab-root to check.

    Returns (root, error_code). error_code is one of:
    - None: `root` is a valid, structurally-checked inbox root.
    - "wrong_root": `explicit` was given but does not resolve to a
      structurally valid inbox (missing, not a directory, or wrong shape).
    - "missing": no `--lab-root` was given and auto-discovery found nothing
      (up to `stop_at`, when given).
    - "invalid_stop_at": `stop_at` is not `start` or one of its ancestors.
    """
    if explicit is not None:
        if not _looks_like_inbox(explicit):
            return None, "wrong_root"
        return explicit, None

    try:
        found = discover_lab_root(start, stop_at)
    except ValueError:
        return None, "invalid_stop_at"
    if found is None:
        return None, "missing"
    return found, None


def parse_frontmatter(text: str) -> tuple[dict[str, Any] | None, str | None]:
    """Parse the leading YAML frontmatter block. Returns (fields, error)."""
    match = FRONTMATTER_RE.match(text)
    if not match:
        return None, "no YAML frontmatter block found (expected a leading `---` block)"
    try:
        loaded = yaml.safe_load(match.group(1))
    except yaml.YAMLError as exc:
        return None, f"YAML frontmatter did not parse: {exc}"
    if not isinstance(loaded, dict):
        return None, "YAML frontmatter did not parse to a mapping"
    return loaded, None


def extract_artifact_target(raw: str) -> tuple[str, str]:
    """Classify an `artifact` field value as ("url", target) or
    ("path", target); a URL takes priority over path-shaped parsing (e.g.
    "PR https://github.com/..." is a URL, not a path named "PR")."""
    raw = raw.strip()
    url_match = URL_RE.search(raw)
    if url_match:
        return "url", url_match.group(0)
    # Strip a trailing free-text annotation like "(still current baseline)".
    token = raw.split(" (", 1)[0].strip()
    return "path", token


def check_artifact(raw: str, workspace_root: Path) -> dict[str, Any] | None:
    """Check an `artifact` field's existence. Never opens/reads the
    artifact itself -- filesystem existence only. Returns a finding dict
    or None if there is nothing to report (URL artifact, or path exists)."""
    kind, target = extract_artifact_target(raw)
    if kind == "url" or not target:
        return None
    candidate = Path(target)
    resolved = candidate if candidate.is_absolute() else (workspace_root / candidate)
    if resolved.exists():
        return None
    return {
        "code": "artifact_missing",
        "severity": "warning",
        "detail": f"artifact not found: {target!r} (resolved: {resolved})",
    }


def validate_message(path: Path, lab_root: Path, workspace_root: Path) -> list[dict[str, Any]]:
    """Validate one message file. Returns a list of finding dicts, each
    with keys: file, code, severity, detail."""
    findings: list[dict[str, Any]] = []
    relative_path = path.relative_to(lab_root)
    rel = str(relative_path)
    is_legacy = bool(relative_path.parts) and relative_path.parts[0].lower() == "done"

    def add(code: str, severity: str, detail: str) -> None:
        if is_legacy and severity == "error":
            severity = "warning"
        findings.append({"file": rel, "code": code, "severity": severity, "detail": detail})

    text = path.read_text(encoding="utf-8", errors="replace")

    fields, err = parse_frontmatter(text)
    if err:
        add("frontmatter_invalid", "error", err)
        return findings

    assert fields is not None
    for field in REQUIRED_FIELDS:
        value = fields.get(field)
        if value is None or not str(value).strip():
            add(f"missing_field:{field}", "error", f"required field {field!r} is missing or empty")

    msg_type = fields.get("type")
    if msg_type is not None and str(msg_type).strip() and msg_type not in MESSAGE_TYPES:
        add("invalid_type", "error", f"type={msg_type!r} not in {sorted(MESSAGE_TYPES)}")

    diacritics = DIACRITICS_RE.findall(text)
    if diacritics:
        add("diacritics_found", "warning", f"{len(diacritics)} a/o/u-with-diacritics occurrence(s)")

    artifact = fields.get("artifact")
    if artifact is not None and str(artifact).strip():
        finding = check_artifact(str(artifact), workspace_root)
        if finding:
            add(finding["code"], finding["severity"], finding["detail"])

    return findings


def iter_message_files(lab_root: Path) -> list[Path]:
    return sorted(p for p in lab_root.rglob("*.md") if p.name.lower() != "readme.md")


def run_validation(lab_root: Path, workspace_root: Path) -> dict[str, Any]:
    messages = iter_message_files(lab_root)
    findings: list[dict[str, Any]] = []
    for path in messages:
        findings.extend(validate_message(path, lab_root, workspace_root))
    return {
        "lab_root": str(lab_root),
        "workspace_root": str(workspace_root),
        "messages_checked": len(messages),
        "findings": findings,
    }


def workspace_relationship_valid(lab_root: Path, workspace_root: Path) -> bool:
    """Return whether lab_root is exactly <workspace_root>/lab/inbox."""
    return lab_root.resolve() == (workspace_root.resolve() / "lab" / "inbox").resolve()


def _print_report(report: dict[str, Any]) -> None:
    print(f"session-inbox-contract: lab-root -> {report['lab_root']}")
    print(f"session-inbox-contract: workspace-root -> {report['workspace_root']}")
    print(f"session-inbox-contract: {report['messages_checked']} message(s) checked")
    for finding in report["findings"]:
        print(f"  {finding['severity']:7} {finding['code']:20} {finding['file']}: {finding['detail']}")
    if not report["findings"]:
        print("session-inbox-contract: OK, no findings")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--lab-root",
        type=Path,
        default=None,
        help="Explicit lab/inbox root to validate. Omit to auto-discover by walking up from --start.",
    )
    parser.add_argument(
        "--workspace-root",
        type=Path,
        default=None,
        help="Workspace root used to resolve workspace-relative artifact paths. "
        "Defaults to lab-root's grandparent (the <workspace>/lab/inbox layout).",
    )
    parser.add_argument(
        "--start",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Starting directory for auto-discovery when --lab-root is omitted.",
    )
    parser.add_argument(
        "--stop-at",
        type=Path,
        default=None,
        help="Bound auto-discovery to not walk above this ancestor directory. "
        "Omit for normal use -- lab/inbox genuinely lives above the repository "
        "root in the real workspace layout. Intended for deterministic tests.",
    )
    parser.add_argument("--json", action="store_true", help="Emit the report as JSON instead of text.")
    args = parser.parse_args(argv)

    lab_root, error_code = resolve_lab_root(args.lab_root, args.start, args.stop_at)
    if error_code is not None:
        if args.json:
            print(json.dumps({"error": error_code}))
        elif error_code == "wrong_root":
            print(
                f"session-inbox-contract: FAIL -- --lab-root {args.lab_root} does not "
                "structurally resolve to a lab/inbox root (wrong_root)",
                file=sys.stderr,
            )
        elif error_code == "invalid_stop_at":
            print(
                "session-inbox-contract: FAIL -- --stop-at must be --start or "
                "one of its ancestors (invalid_stop_at)",
                file=sys.stderr,
            )
        else:
            print(
                f"session-inbox-contract: FAIL -- no lab/inbox found via auto-discovery "
                f"starting from {args.start} (missing)",
                file=sys.stderr,
            )
        return 2

    assert lab_root is not None
    workspace_root = (args.workspace_root or lab_root.parent.parent).resolve()
    lab_root = lab_root.resolve()
    if not workspace_relationship_valid(lab_root, workspace_root):
        if args.json:
            print(json.dumps({"error": "wrong_workspace_root"}))
        else:
            print(
                f"session-inbox-contract: FAIL -- lab-root {lab_root} is not exactly "
                f"{workspace_root / 'lab' / 'inbox'} (wrong_workspace_root)",
                file=sys.stderr,
            )
        return 2
    report = run_validation(lab_root, workspace_root)

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        _print_report(report)

    if any(f["severity"] == "error" for f in report["findings"]):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
