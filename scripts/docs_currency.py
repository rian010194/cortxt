#!/usr/bin/env python3
"""docs_currency.py -- keep the published Starlight docs mirroring repository authority.

Regenerates the derived site pages under `site/src/content/docs/docs/` from
their authoritative repository sources, or verifies (--check) that the
committed pages already match what would be regenerated.

Why this exists
---------------
The docs site (Astro + Starlight) publishes pages that are *derived* from
repository authority: the Accepted-only ADR index is generated from
`docs/adr/`, the Atlas status page from `scripts/atlas_sync.py`. Hand-editing
those pages lets them drift (e.g. an Accepted ADR missing from the site index,
or a stale "as of" date). This script is the deterministic regeneration path;
the CI job fails a PR when a derived page would change, so a contributor
cannot merge site docs that no longer match the repository authority.

Scope
-----
Currently regenerates one derived page:

- `site/src/content/docs/docs/adrs.md` <- `docs/adr/*.md` (Accepted only)

The Atlas status page is owned by `scripts/atlas_sync.py --emit-site` and is
out of scope here. New derived pages should be added here with the same
discipline: read-only authority, no secrets, deterministic output, and a
`--check` that fails on drift.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ADRS_SITE_PATH = Path("site/src/content/docs/docs/adrs.md")
ADR_DIR = Path("docs/adr")

HEADING_RE = re.compile(r"^#\s+ADR-(\d+):\s+(.+?)\s*$", re.MULTILINE)
STATUS_RE = re.compile(r"^\*\*Status:\*\*\s*(.+?)\s*$", re.MULTILINE)
DATE_RE = re.compile(r"^\*\*Date:\*\*\s*(.+?)\s*$", re.MULTILINE)

# Known-bad markers that must never appear in a generated page (mirrors
# atlas_sync.py's scan_unsafe discipline).
KNOWN_BAD_MARKERS = [
    "BEGIN PRIVATE",
    "do not publish",
    "secret",
    "token=",
    "api_key",
    "password",
    "private key",
    "BEGIN RSA",
    "BEGIN OPENSSH",
    "BEGIN PRIVATE KEY",
]

# Authority marker: every page this script owns carries a comment so the
# boundary between generated and hand-written content is explicit.
AUTO_BEGIN = "<!-- docs-currency:auto:begin -->"
AUTO_END = "<!-- docs-currency:auto:end -->"


# ---------------------------------------------------------------------------
# Repository authority parsing
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AdrRecord:
    number: int
    title: str
    status: str
    date: str | None
    filename: str


def parse_adr_files(adr_dir: Path) -> list[AdrRecord]:
    """Parse the ADR files in `adr_dir` into records.

    Authority is the per-file `# ADR-NNN: Title` heading plus the
    `**Status:**` and `**Date:**` lines, exactly as the repository index
    (`docs/adr/README.md`) is derived from them. Files that do not follow
    the ADR template are skipped; a number collision is an error.
    """
    records: dict[int, AdrRecord] = {}
    if not adr_dir.is_dir():
        return []
    for path in sorted(adr_dir.glob("*.md")):
        if path.name == "README.md":
            continue
        # Normalize line endings: ADR files are committed with CRLF, and the
        # regexes below anchor on `$` which does not match before a bare `\r`.
        text = path.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")
        heading = HEADING_RE.search(text)
        if not heading:
            continue
        number = int(heading.group(1))
        title = heading.group(2).strip()
        # Some ADR files end the header line with a markdown soft-break (`\`)
        # so the next `**Field:**` line starts on its own visual line; strip it.
        title = title.rstrip("\\").strip()
        status_match = STATUS_RE.search(text)
        date_match = DATE_RE.search(text)
        status = status_match.group(1).strip() if status_match else "Unknown"
        date = date_match.group(1).strip() if date_match else None
        status = status.rstrip("\\").strip()
        if date:
            date = date.rstrip("\\").strip()
        record = AdrRecord(
            number=number,
            title=title,
            status=status,
            date=date,
            filename=path.name,
        )
        if number in records:
            raise ValueError(f"duplicate ADR number {number}: {records[number].filename} and {path.name}")
        records[number] = record
    return [records[n] for n in sorted(records)]


# ---------------------------------------------------------------------------
# Derived page rendering
# ---------------------------------------------------------------------------


def _repo_adr_url(filename: str) -> str:
    return f"https://github.com/rian010194/cortxt/blob/main/docs/adr/{filename}"


def _status_kind(status: str) -> str:
    """Classify a status string into accepted | proposed | superseded | other.

    Statuses carry optional qualifiers (e.g. "Accepted (amended 2026-08-19)",
    "Proposed (Part 1 implemented)", "Proposed - **SUPERSEDED (ADR-017)**")
    so classification looks for an explicit superseded marker first, then the
    leading token, matching the repository index's decision-state rule.
    """
    lowered = status.strip().lower()
    if "superseded" in lowered:
        return "superseded"
    token = lowered.split("(", 1)[0].strip().rstrip("\\").strip()
    if token == "accepted":
        return "accepted"
    if token in ("proposed", "draft"):
        return "proposed"
    return "other"


def render_adrs_page(records: list[AdrRecord], as_of: str) -> str:
    """Render the Accepted-only ADR index page for the docs site.

    Only records marked **Accepted** appear in the table. Proposed and
    Superseded records are listed in a note so readers can see what is
    pending or historical without presenting them as authority.
    """
    accepted = [r for r in records if _status_kind(r.status) == "accepted"]
    proposed = [r for r in records if _status_kind(r.status) == "proposed"]
    superseded = [r for r in records if _status_kind(r.status) == "superseded"]

    lines = [
        "---",
        "title: Accepted architecture decisions",
        "description: The Accepted-only ADR index mirrored from the repository authority.",
        "---",
        "",
        AUTO_BEGIN,
        "",
        "This page is generated from the repository ADR files by "
        "`scripts/docs_currency.py`; do not hand-edit the generated block. "
        f"As of {as_of}. [Open the authoritative ADR index]("
        "https://github.com/rian010194/cortxt/blob/main/docs/adr/README.md).",
        "",
        "| ADR | Decision |",
        "| --- | --- |",
    ]
    for r in accepted:
        lines.append(f"| [{r.number:03d}]({_repo_adr_url(r.filename)}) | {r.title} |")

    notes = []
    if proposed:
        names = ", ".join(
            f"[ADR-{r.number:03d}]({_repo_adr_url(r.filename)}) ({r.status})" for r in proposed
        )
        notes.append(
            f"**Proposed** records ({names}) are reviewable designs, not "
            "Accepted decisions; they are intentionally absent from the "
            "Accepted table above."
        )
    if superseded:
        names = ", ".join(
            f"[ADR-{r.number:03d}]({_repo_adr_url(r.filename)})" for r in superseded
        )
        notes.append(
            f"**Superseded** records ({names}) are historical references kept "
            "for traceability only."
        )
    if notes:
        lines.append("")
        lines.append(":::note")
        lines.append(" ".join(notes))
        lines.append(":::")

    lines.append("")
    lines.append(AUTO_END)
    lines.append("")
    return "\n".join(lines)


def render_all(records: list[AdrRecord], as_of: str) -> dict[Path, str]:
    """Return {relative_path: content} for every derived page this script owns."""
    return {
        ADRS_SITE_PATH: render_adrs_page(records, as_of),
    }


# ---------------------------------------------------------------------------
# Safe-content scan (mirrors atlas_sync.py)
# ---------------------------------------------------------------------------


def scan_unsafe(text: str) -> list:
    return [marker for marker in KNOWN_BAD_MARKERS if marker.lower() in text.lower()]


# ---------------------------------------------------------------------------
# Emit / check
# ---------------------------------------------------------------------------


def _as_of_date(records: list[AdrRecord]) -> str:
    """Derive the freshness date from the ADR authority itself so output is
    deterministic for a given repository state (the CI gate must not
    depend on wall-clock time). Uses the latest **Date:** across records."""
    dates = [r.date for r in records if r.date]
    return max(dates, key=lambda d: d) if dates else "unknown"


def emit_derived_pages(*, root: Path, write: bool) -> tuple[list[str], list[str]]:
    """Regenerate derived pages. Returns (changed, unchanged) relative paths.

    With `write=False` (check mode) nothing is written; any page whose
    committed content differs from the regenerated content is reported as
    changed so the caller can fail the gate.
    """
    adr_dir = root / ADR_DIR
    records = parse_adr_files(adr_dir)
    pages = render_all(records, _as_of_date(records))

    changed: list[str] = []
    unchanged: list[str] = []
    for rel, content in pages.items():
        for marker in scan_unsafe(content):
            raise ValueError(f"unsafe content marker {marker!r} would be written to {rel}")

        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        existing = path.read_text(encoding="utf-8") if path.exists() else None
        if existing == content:
            unchanged.append(str(rel))
            continue
        changed.append(str(rel))
        if write:
            path.write_text(content, encoding="utf-8")
    return changed, unchanged


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path("."),
        help="Repository root (the directory containing docs/ and site/).",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify committed derived pages match regeneration; exit 1 if any would change. Writes nothing.",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Regenerate derived pages in place (idempotent; only writes on change).",
    )
    args = parser.parse_args(argv)

    if args.check and args.write:
        parser.error("--check and --write are mutually exclusive")

    changed, unchanged = emit_derived_pages(root=args.root, write=args.write and not args.check)

    for rel in unchanged:
        print(f"docs-currency: unchanged -> {rel}")
    for rel in changed:
        print(f"docs-currency: {'written' if args.write else 'WOULD CHANGE'} -> {rel}")

    if args.check and changed:
        print(
            "docs-currency: FAIL -- derived site page(s) drifted from repository "
            "authority. Run `python scripts/docs_currency.py --write` and commit "
            "the regenerated page(s).",
            file=sys.stderr,
        )
        return 1
    if not args.check and not args.write:
        print("docs-currency: check mode (no writes); use --check to gate, --write to regenerate.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
