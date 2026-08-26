#!/usr/bin/env python3
"""Deterministic regression tests for scripts/session_inbox_contract.py.

Builds fixture inbox trees under a scratch directory inside the repository
(never touches the real workspace `lab/inbox/`), so this test performs no
live inbox mutation and no GitHub calls. Run directly:
python scripts/test_session_inbox_contract.py (0 = pass)
"""
from __future__ import annotations

import importlib.util
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MOD = REPO / "scripts" / "session_inbox_contract.py"
spec = importlib.util.spec_from_file_location("session_inbox_contract", MOD)
sic = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = sic
spec.loader.exec_module(sic)

fail = []

SCRATCH = REPO / ".tmp" / "session-inbox-contract-test"


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


VALID_MESSAGE = """---
from: session-a
to: coordinator
type: delivery
created: 2026-08-26T12:00:00Z
artifact: lab/HANDOFF-fixture.md
affects: docs/adr/
---

Fixture delivery message, no diacritics, no secrets.
"""

MISSING_FIELDS_MESSAGE = """---
from: session-a
type: delivery
created: 2026-08-26T12:00:00Z
artifact: lab/HANDOFF-fixture.md
---

Missing `to` and `affects`.
"""

BAD_TYPE_MESSAGE = """---
from: session-a
to: coordinator
type: gossip
created: 2026-08-26T12:00:00Z
artifact: lab/HANDOFF-fixture.md
affects: docs/adr/
---

Invalid type.
"""

NO_FRONTMATTER_MESSAGE = "Just prose, no YAML frontmatter block at all.\n"

DIACRITICS_MESSAGE = """---
from: session-a
to: coordinator
type: handoff
created: 2026-08-26T12:00:00Z
artifact: lab/HANDOFF-fixture.md
affects: docs/adr/
---

Bör inte skriva svenska här - klart brott mot kontraktet.
"""

URL_ARTIFACT_MESSAGE = """---
from: session-a
to: coordinator
type: delivery
created: 2026-08-26T12:00:00Z
artifact: PR https://github.com/example/repo/pull/1
affects: main
---

Artifact is a URL; must not be treated as a missing path.
"""

MISSING_ARTIFACT_MESSAGE = """---
from: session-a
to: coordinator
type: delivery
created: 2026-08-26T12:00:00Z
artifact: lab/does-not-exist-fixture.md
affects: main
---

Artifact path does not exist on disk.
"""

ANNOTATED_ARTIFACT_MESSAGE = """---
from: session-a
to: coordinator
type: delivery
created: 2026-08-26T12:00:00Z
artifact: lab/HANDOFF-fixture.md (still current baseline)
affects: main
---

Artifact has a trailing free-text annotation that must be stripped.
"""


def build_inbox(root: Path) -> Path:
    """Build a minimal structurally-valid <root>/lab/inbox tree and return
    the lab/inbox path."""
    lab_root = root / "lab" / "inbox"
    (lab_root / "done").mkdir(parents=True, exist_ok=True)
    (lab_root / "coordinator" / "in").mkdir(parents=True, exist_ok=True)
    # The artifact target referenced by several fixture messages above.
    (root / "lab" / "HANDOFF-fixture.md").write_text("fixture handoff\n", encoding="utf-8")
    return lab_root


def codes(findings):
    return {f["code"] for f in findings}


def main() -> int:
    # -- extract_artifact_target ------------------------------------------------
    kind, target = sic.extract_artifact_target("PR https://github.com/example/repo/pull/1")
    check("extract_artifact_target: url prefix classified as url", kind == "url", f"got {kind!r}")
    check("extract_artifact_target: url target extracted", target == "https://github.com/example/repo/pull/1", target)

    kind, target = sic.extract_artifact_target("lab/HANDOFF-fixture.md (still current baseline)")
    check("extract_artifact_target: annotation stripped", (kind, target) == ("path", "lab/HANDOFF-fixture.md"), (kind, target))

    kind, target = sic.extract_artifact_target(r"C:\Users\rikar\Cortxt\projects\ai-workspace-control-plane")
    check(
        "extract_artifact_target: absolute Windows path kept whole",
        (kind, target) == ("path", r"C:\Users\rikar\Cortxt\projects\ai-workspace-control-plane"),
        (kind, target),
    )

    # -- _looks_like_inbox / discover_lab_root / resolve_lab_root ---------------
    root = fresh_root("valid-root")
    lab_root = build_inbox(root)
    workspace_root = lab_root.parent.parent

    check("_looks_like_inbox: true for done/-shaped root", sic._looks_like_inbox(lab_root))

    not_inbox = fresh_root("not-an-inbox")
    (not_inbox / "some-file.txt").write_text("x", encoding="utf-8")
    check("_looks_like_inbox: false for unrelated directory", not sic._looks_like_inbox(not_inbox))

    resolved, err = sic.resolve_lab_root(lab_root, workspace_root)
    check("resolve_lab_root: explicit valid root resolves with no error", resolved == lab_root and err is None, (resolved, err))

    resolved, err = sic.resolve_lab_root(not_inbox, workspace_root)
    check(
        "resolve_lab_root: explicit structurally-wrong root -> wrong_root",
        resolved is None and err == "wrong_root",
        (resolved, err),
    )

    nonexistent = root / "does" / "not" / "exist"
    resolved, err = sic.resolve_lab_root(nonexistent, workspace_root)
    check(
        "resolve_lab_root: explicit nonexistent root -> wrong_root",
        resolved is None and err == "wrong_root",
        (resolved, err),
    )

    empty_workspace = fresh_root("empty-workspace-for-discovery")
    resolved, err = sic.resolve_lab_root(None, empty_workspace, stop_at=SCRATCH)
    check(
        "resolve_lab_root: auto-discovery absence -> missing",
        resolved is None and err == "missing",
        (resolved, err),
    )

    nested_start = lab_root.parent.parent / "deeply" / "nested" / "start"
    nested_start.mkdir(parents=True, exist_ok=True)
    resolved, err = sic.resolve_lab_root(None, nested_start, stop_at=SCRATCH)
    check(
        "resolve_lab_root: auto-discovery walks up parents to find lab/inbox",
        resolved == lab_root and err is None,
        (resolved, err),
    )

    # -- validate_message: field/type/frontmatter checks -------------------------
    def write_and_validate(name: str, content: str, target_lab_root: Path, target_workspace_root: Path):
        mailbox = target_lab_root / "coordinator" / "in"
        mailbox.mkdir(parents=True, exist_ok=True)
        path = mailbox / name
        path.write_text(content, encoding="utf-8")
        return sic.validate_message(path, target_lab_root, target_workspace_root)

    findings = write_and_validate("valid.md", VALID_MESSAGE, lab_root, workspace_root)
    check("validate_message: fully valid message has zero findings", findings == [], findings)

    findings = write_and_validate("missing-fields.md", MISSING_FIELDS_MESSAGE, lab_root, workspace_root)
    fcodes = codes(findings)
    check(
        "validate_message: missing required fields reported individually",
        "missing_field:to" in fcodes and "missing_field:affects" in fcodes,
        fcodes,
    )
    check(
        "validate_message: missing-field findings are errors",
        all(f["severity"] == "error" for f in findings if f["code"].startswith("missing_field:")),
        findings,
    )

    findings = write_and_validate("bad-type.md", BAD_TYPE_MESSAGE, lab_root, workspace_root)
    check("validate_message: invalid type reported", "invalid_type" in codes(findings), codes(findings))

    findings = write_and_validate("no-frontmatter.md", NO_FRONTMATTER_MESSAGE, lab_root, workspace_root)
    check(
        "validate_message: missing frontmatter block reported and short-circuits",
        codes(findings) == {"frontmatter_invalid"},
        codes(findings),
    )

    findings = write_and_validate("diacritics.md", DIACRITICS_MESSAGE, lab_root, workspace_root)
    diac = [f for f in findings if f["code"] == "diacritics_found"]
    check("validate_message: diacritics detected", len(diac) == 1, findings)
    check("validate_message: diacritics finding is a warning", diac and diac[0]["severity"] == "warning", diac)

    findings = write_and_validate("url-artifact.md", URL_ARTIFACT_MESSAGE, lab_root, workspace_root)
    check(
        "validate_message: URL artifact never flagged as missing",
        "artifact_missing" not in codes(findings),
        codes(findings),
    )

    findings = write_and_validate("missing-artifact.md", MISSING_ARTIFACT_MESSAGE, lab_root, workspace_root)
    check("validate_message: nonexistent artifact path flagged", "artifact_missing" in codes(findings), codes(findings))
    am = next(f for f in findings if f["code"] == "artifact_missing")
    check("validate_message: artifact_missing finding is a warning", am["severity"] == "warning", am)

    findings = write_and_validate("annotated-artifact.md", ANNOTATED_ARTIFACT_MESSAGE, lab_root, workspace_root)
    check(
        "validate_message: annotated artifact path resolves after stripping annotation",
        "artifact_missing" not in codes(findings),
        codes(findings),
    )

    # -- absolute-path artifact handled without reading the artifact's contents --
    abs_root = fresh_root("abs-artifact-target")
    abs_artifact = abs_root / "definitely-exists.md"
    abs_artifact.write_text("content that must never be opened by the checker\n", encoding="utf-8")
    abs_lab_root = build_inbox(fresh_root("abs-artifact-inbox"))
    abs_message = f"""---
from: session-a
to: coordinator
type: delivery
created: 2026-08-26T12:00:00Z
artifact: {abs_artifact}
affects: main
---

Absolute-path artifact.
"""
    findings = write_and_validate("abs-artifact.md", abs_message, abs_lab_root, abs_lab_root.parent.parent)
    check(
        "validate_message: absolute artifact path resolved as-is (existing)",
        "artifact_missing" not in codes(findings),
        codes(findings),
    )

    # -- run_validation / main: end-to-end, exit codes ----------------------------
    e2e_root = fresh_root("end-to-end")
    e2e_lab_root = build_inbox(e2e_root)
    (e2e_lab_root / "coordinator" / "in" / "ok.md").write_text(VALID_MESSAGE, encoding="utf-8")
    (e2e_lab_root / "coordinator" / "in" / "broken.md").write_text(BAD_TYPE_MESSAGE, encoding="utf-8")
    report = sic.run_validation(e2e_lab_root, e2e_lab_root.parent.parent)
    check("run_validation: checks both message files", report["messages_checked"] == 2, report)
    check("run_validation: surfaces the invalid_type error", "invalid_type" in codes(report["findings"]), report)

    rc = sic.main(["--lab-root", str(e2e_lab_root), "--json"])
    check("main: exit code 1 when an error finding is present", rc == 1, rc)

    clean_root = fresh_root("clean-end-to-end")
    clean_lab_root = build_inbox(clean_root)
    (clean_lab_root / "coordinator" / "in" / "ok.md").write_text(VALID_MESSAGE, encoding="utf-8")
    rc = sic.main(["--lab-root", str(clean_lab_root), "--json"])
    check("main: exit code 0 when only clean messages present", rc == 0, rc)

    rc = sic.main(["--lab-root", str(not_inbox)])
    check("main: exit code 2 for wrong_root", rc == 2, rc)

    empty_start = fresh_root("empty-start-for-main")
    rc = sic.main(["--start", str(empty_start), "--stop-at", str(SCRATCH)])
    check("main: exit code 2 for missing (auto-discovery absence)", rc == 2, rc)

    # README.md files are documentation, not messages, and must be skipped.
    readme_root = fresh_root("readme-skip")
    readme_lab_root = build_inbox(readme_root)
    (readme_lab_root / "README.md").write_text("# not a message\n", encoding="utf-8")
    files = sic.iter_message_files(readme_lab_root)
    check("iter_message_files: README.md excluded", all(p.name.lower() != "readme.md" for p in files), files)

    shutil.rmtree(SCRATCH, ignore_errors=True)

    print()
    if fail:
        print(f"FAIL: {len(fail)} failure(s): {fail}")
        return 1
    print("OK: all session-inbox-contract checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
