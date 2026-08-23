#!/usr/bin/env python3
"""Deterministic regression tests for scripts/docs_currency.py.

Exercises the ADR parsing, classification, rendering, and check/write
discipline against a fixture ADR directory, so no repository network calls
happen. Run directly: python scripts/test_docs_currency.py (0 = pass)
"""
import importlib.util
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MOD = REPO / "scripts" / "docs_currency.py"
spec = importlib.util.spec_from_file_location("docs_currency", MOD)
d = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = d
spec.loader.exec_module(d)

fail = []

# Scratch area for fixture repos; kept inside the repository so the test can
# write even when the OS temp area is unavailable to the harness.
SCRATCH = REPO / ".tmp" / "docs-currency-test"


def check(name, cond, detail=""):
    print(f"  {'ok' if cond else 'FAIL':4} {name}" + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        fail.append(name)


def fresh_root(label: str) -> Path:
    root = SCRATCH / label
    if root.exists():
        shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True, exist_ok=True)
    return root


ACCEPTED = """# ADR-014: Test Vision (F0)

**Status:** Accepted
**Date:** 2026-08-13
"""

ACCEPTED_AMENDED = """# ADR-020: Test Amendment

**Status:** Accepted (amended 2026-08-19 for a follow-up)
**Date:** 2026-08-16
"""

PROPOSED = """# ADR-029: Test Proposal

**Status:** Proposed (Part 1 implemented)
**Date:** 2026-08-20
"""

SUPERSEDED = """# ADR-011: Old Router

**Status:** Proposed - **SUPERSEDED (2026-08-14, ADR-017)**
**Date:** 2026-07-01
"""

CRLF_ACCEPTED = "# ADR-040: CRLF File\r\n\r\n**Status:** Accepted  \\\r\n**Date:** 2026-08-22  \\\r\n"


def make_fixture_adr_dir(tmp: Path) -> Path:
    adr = tmp / "docs" / "adr"
    adr.mkdir(parents=True)
    (adr / "014-f0.md").write_text(ACCEPTED, encoding="utf-8")
    (adr / "020-amend.md").write_text(ACCEPTED_AMENDED, encoding="utf-8")
    (adr / "029-proposed.md").write_text(PROPOSED, encoding="utf-8")
    (adr / "011-old.md").write_text(SUPERSEDED, encoding="utf-8")
    (adr / "040-crlf.md").write_text(CRLF_ACCEPTED, encoding="utf-8")
    (adr / "README.md").write_text("# ADR Index\n", encoding="utf-8")
    return tmp


def test_parse_and_classify():
    root = fresh_root("parse")
    make_fixture_adr_dir(root)
    records = d.parse_adr_files(root / "docs" / "adr")
    check("parses 5 ADR files (README skipped)", len(records) == 5, str(len(records)))
    check(
        "accepted classification (leading token)",
        d._status_kind("Accepted (amended 2026-08-19 for a follow-up)") == "accepted",
    )
    check(
        "proposed classification with qualifier",
        d._status_kind("Proposed (Part 1 implemented)") == "proposed",
    )
    check(
        "superseded marker wins over leading Proposed",
        d._status_kind("Proposed - **SUPERSEDED (2026-08-14, ADR-017)**") == "superseded",
    )
    by_num = {r.number: r for r in records}
    check("number 011 parsed", by_num.get(11) is not None)
    check("number 040 parsed from CRLF file", by_num.get(40) is not None)
    check("CRLF status trailing backslash stripped", by_num[40].status == "Accepted", repr(by_num[40].status))


def test_render_contains_correct_rows():
    root = fresh_root("render")
    make_fixture_adr_dir(root)
    records = d.parse_adr_files(root / "docs" / "adr")
    page = d.render_adrs_page(records, "2026-08-22")
    check("accepted rows 014, 020, 040 present", "[014]" in page and "[020]" in page and "[040]" in page)
    table_rows = "".join(l for l in page.splitlines() if l.startswith("| ["))
    check("proposed 029 in note, not table", "[ADR-029]" in page and "[ADR-029]" not in table_rows)
    check("superseded 011 in note, not table", "[ADR-011]" in page and "[ADR-011]" not in table_rows)
    check("authority markers present", d.AUTO_BEGIN in page and d.AUTO_END in page)


def test_emit_check_write_discipline():
    root = fresh_root("emit")
    make_fixture_adr_dir(root)
    site = root / "site" / "src" / "content" / "docs" / "docs"
    site.mkdir(parents=True)

    # Check mode with no committed page: must report changed, write nothing.
    changed, unchanged = d.emit_derived_pages(root=root, write=False)
    check("check mode reports change on missing page", len(changed) == 1 and not unchanged, f"{changed} {unchanged}")
    check("check mode writes nothing", not (site / "adrs.md").exists())

    # Write mode: page appears and is stable.
    changed, _ = d.emit_derived_pages(root=root, write=True)
    check("write mode writes page", len(changed) == 1)
    first = (site / "adrs.md").read_text(encoding="utf-8")
    changed2, unchanged2 = d.emit_derived_pages(root=root, write=True)
    check("second write is a no-op", not changed2 and len(unchanged2) == 1, f"{changed2} {unchanged2}")
    check("content identical after no-op write", (site / "adrs.md").read_text(encoding="utf-8") == first)

    # Check mode after write: clean.
    changed3, unchanged3 = d.emit_derived_pages(root=root, write=False)
    check("check mode clean after write", not changed3 and len(unchanged3) == 1, f"{changed3} {unchanged3}")


def test_scan_unsafe_blocks_leak():
    bad = "this contains a secret token=abc and password"
    hits = d.scan_unsafe(bad)
    check("unsafe markers detected", len(hits) >= 2, str(hits))
    check("clean text has no hits", not d.scan_unsafe("clean public documentation"))


test_parse_and_classify()
test_render_contains_correct_rows()
test_emit_check_write_discipline()
test_scan_unsafe_blocks_leak()

# Leave no scratch behind.
if SCRATCH.exists():
    shutil.rmtree(SCRATCH, ignore_errors=True)

if fail:
    print(f"\n{len(fail)} FAILURE(S): {fail}")
    sys.exit(1)
print("\nall docs_currency tests passed")
