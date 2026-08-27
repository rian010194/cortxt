#!/usr/bin/env python3
"""Bounded semantic-correctness checks for public documentation.

`scripts/docs_currency.py` verifies the generated ADR index is mechanically
in sync. It does not check that public pages describe the *current* accepted
product surface (ADR-042: durable authority, replaceable execution) rather
than an obsolete CLI-primary framing. This script adds narrow, targeted
checks for the specific obsolete claims this repository has already made in
public docs, scoped to current public pages and README-like surfaces. It
intentionally does not touch `docs/adr/*.md` -- historical ADR wording (e.g.
ADR-015's "CLI-primary") is a register entry and must not be flagged.

Run directly: python scripts/docs_semantic_currency.py (0 = pass)
"""
import re
import sys
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# Explicit public/current-facing pages -- must exist; a missing one is a
# FAIL, not a silent skip, since a moved/renamed page would otherwise drop
# out of the gate unnoticed.
EXPLICIT_PUBLIC_PAGES = [
    REPO / "README.md",
    REPO / "CLAUDE.md",
    REPO / "docs" / "agents" / "current-operating-model.md",
    REPO / "docs" / "agents" / "work-launcher.md",
]

# Every docs page under the Starlight docs root -- covers new pages added
# without a matching update to this script.
DOCS_GLOB_ROOT = REPO / "site" / "src" / "content" / "docs" / "docs"

# The old docs.cortxt.io host is not reliably routed to the current docs
# build (verified 2026-08-27: its root path serves the landing page, not
# the Starlight site) -- see site/README.md. Public docs must not link it.
LEGACY_DOCS_DOMAIN = "docs.cortxt.io"

fail: list[str] = []


# Marker used by Atlas-synced pages (scripts/atlas_sync.py). Their content is
# mirrored from GitHub issue titles/bodies, not authored here -- editing them
# by hand is overwritten on the next sync, so semantic-currency issues in
# them must be fixed at the GitHub issue, not this repo. Excluded from these
# checks for that reason, not because their content doesn't matter.
AUTO_GENERATED_MARKER = "derived automatically from the"


def current_public_pages() -> list[Path]:
    pages = list(EXPLICIT_PUBLIC_PAGES)
    if DOCS_GLOB_ROOT.exists():
        pages.extend(sorted(DOCS_GLOB_ROOT.glob("**/*.md")))
        pages.extend(sorted(DOCS_GLOB_ROOT.glob("**/*.mdx")))
    # de-dupe while preserving order
    seen: set[Path] = set()
    unique = []
    for p in pages:
        if p in seen:
            continue
        seen.add(p)
        if p.exists() and AUTO_GENERATED_MARKER in read(p):
            continue
        unique.append(p)
    return unique


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'ok' if cond else 'FAIL':4} {name}" + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        fail.append(name)


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_explicit_pages_exist():
    for path in EXPLICIT_PUBLIC_PAGES:
        check(f"explicit public page exists: {path.relative_to(REPO)}", path.exists())


def test_no_cli_primary_claim_on_current_pages():
    pattern = re.compile(
        r"CLI\s+is\s+the\s+primary\s+product\s+surface|CLI[\s-]+primary\b",
        re.IGNORECASE,
    )
    for path in current_public_pages():
        if not path.exists():
            continue
        text = read(path)
        # Collapse whitespace (including line-wrap newlines) so a hard-wrapped
        # sentence can't dodge the pattern.
        flat = re.sub(r"\s+", " ", text)
        hits = list(pattern.finditer(flat))
        check(
            f"no unqualified CLI-primary claim: {path.relative_to(REPO)}",
            not hits,
            f"matched: {[h.group(0) for h in hits]!r}" if hits else "",
        )


def test_no_legacy_docs_domain_links():
    for path in current_public_pages():
        if not path.exists():
            continue
        text = read(path)
        check(
            f"no {LEGACY_DOCS_DOMAIN} link: {path.relative_to(REPO)}",
            LEGACY_DOCS_DOMAIN not in text,
        )


def test_quick_start_python_version_matches_package_metadata():
    pyproject = REPO / "agent-platform" / "pyproject.toml"
    quick_start = REPO / "site" / "src" / "content" / "docs" / "docs" / "quick-start.md"
    if not (pyproject.exists() and quick_start.exists()):
        check("quick-start Python version check (files present)", False, "missing pyproject.toml or quick-start.md")
        return
    meta = tomllib.loads(read(pyproject))
    requires_python = meta.get("project", {}).get("requires-python", "")
    m = re.search(r">=\s*(\d+)\.(\d+)", requires_python)
    check("pyproject declares a >= python version", m is not None, requires_python)
    if not m:
        return
    min_major, min_minor = m.group(1), m.group(2)
    text = read(quick_start)
    stated = re.search(r"Python (\d+)\.(\d+) or later", text)
    check("quick-start states a Python floor", stated is not None)
    if stated:
        check(
            "quick-start Python floor matches pyproject requires-python",
            (stated.group(1), stated.group(2)) == (min_major, min_minor),
            f"quick-start says {stated.group(0)!r}, pyproject says {requires_python!r}",
        )


def test_adr_042_in_generated_index():
    index = REPO / "docs" / "adr" / "README.md"
    if not index.exists():
        check("ADR-042 appears in the generated ADR index", False, f"missing: {index.relative_to(REPO)}")
        return
    text = read(index)
    check("ADR-042 appears in the generated ADR index", "ADR-042" in text)


def test_accepted_direction_not_labeled_shipped():
    pattern = re.compile(
        r"(Work Console|Cortxt OS|Studio)\s+(is|are)\s+(now\s+|fully\s+)?"
        r"(complete|completed|shipped|fully shipped|generally available|available today)",
        re.IGNORECASE,
    )
    for path in current_public_pages():
        if not path.exists():
            continue
        text = read(path)
        flat = re.sub(r"\s+", " ", text)
        hits = list(pattern.finditer(flat))
        check(
            f"no 'shipped/complete' overclaim in {path.relative_to(REPO)}",
            not hits,
            f"matched: {[h.group(0) for h in hits]!r}" if hits else "",
        )


def test_widgets_not_top_level_product_claim():
    widgets_page = REPO / "site" / "src" / "content" / "docs" / "docs" / "widgets.mdx"
    if not widgets_page.exists():
        check("widgets page present", False)
        return
    text = read(widgets_page)
    check(
        "widgets page does not call widgets the top-level product",
        "widgets is the product" not in text.lower() and "widgets are the product" not in text.lower(),
    )


def main() -> int:
    test_explicit_pages_exist()
    test_no_cli_primary_claim_on_current_pages()
    test_no_legacy_docs_domain_links()
    test_quick_start_python_version_matches_package_metadata()
    test_adr_042_in_generated_index()
    test_accepted_direction_not_labeled_shipped()
    test_widgets_not_top_level_product_claim()

    if fail:
        print(f"\n{len(fail)} FAILURE(S): {fail}")
        return 1
    print("\nall docs semantic-currency checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
