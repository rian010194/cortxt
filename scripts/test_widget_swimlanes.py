#!/usr/bin/env python3
"""Offline checks for the swimlane primitive and session-agents widget (#347).

Run: python scripts/test_widget_swimlanes.py
Prints ok/FAIL lines and exits non-zero on any failure.

Covers:
1. Swimlane primitive registered in widget_contract registry with closed props and bindings.
2. Spec declaration (session-agents-0.1.yaml) loads strictly with read:session-agents capability.
3. session-agents.v1 registered in READ_OPERATIONS and TYPES with closed schema.
4. Safe adapter (read_session_agents_v1) strips undeclared fields and fails closed on malformed.
5. CLI artifact path for --view session-agents (ready artifact with swimlane nodes, error-state on failure).
6. Shared maker.js and index.html contain swimlane rendering + pulse animation CSS markers.
7. Living fixture multi-state sequence (>= 3 states) for demo stepping.
8. Text fallback renderer (render_swimlane_text) formats lanes, items, and active markers.
9. Manifest row in widgets.json.
10. Node syntax checks for maker.js and html inline scripts.
11. Zero a/o/u-with-diacritics across all touched files.
"""
from __future__ import annotations

import io
import json
import re
import subprocess
import sys
import tempfile
from argparse import Namespace
from contextlib import redirect_stdout
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
AP = REPO / "agent-platform"
sys.path.insert(0, str(AP))
sys.path.insert(0, str(REPO / "scripts"))

from cli.unified_cli import _run_widget  # noqa: E402
from widget_contract.adapters.store_reads import ReadAdapterError, read_session_agents_v1  # noqa: E402
from widget_contract.loader import ContractError, load_widget, load_widget_file  # noqa: E402
from widget_contract.registry import ALLOWED_CAPABILITIES, PRIMITIVES, READ_OPERATIONS, TYPES  # noqa: E402
from widget_contract.renderer import render  # noqa: E402
from widget_contract.swimlane_text import render_swimlane_text  # noqa: E402
from widget_contract.validation import ValidationError, validate  # noqa: E402

FAILS: list[str] = []


def check(name: str, condition: bool) -> None:
    print(("ok " if condition else "FAIL ") + name)
    if not condition:
        FAILS.append(name)


def fake_agents_data():
    return {
        "schema_version": 1,
        "agents": [
            {
                "id": "agent-hermes",
                "name": "Hermes",
                "runtime": "hermes",
                "status": "running",
                "current_task": "Execute session plan",
                "tasks": [
                    {"id": "t1", "title": "Load context", "state": "done", "progress": 100},
                    {"id": "t2", "title": "Execute session plan", "state": "running", "progress": 65},
                    {"id": "t3", "title": "Verification", "state": "queued", "progress": 0},
                ],
            },
            {
                "id": "agent-pi",
                "name": "Pi",
                "runtime": "pi",
                "status": "running",
                "current_task": "Analyze codebase invariants",
                "tasks": [
                    {"id": "t4", "title": "Inspect AST", "state": "done", "progress": 100},
                    {"id": "t5", "title": "Analyze codebase invariants", "state": "running", "progress": 40},
                ],
            },
            {
                "id": "agent-codex",
                "name": "Codex",
                "runtime": "codex",
                "status": "done",
                "current_task": None,
                "tasks": [
                    {"id": "t6", "title": "Contract validation", "state": "done", "progress": 100},
                ],
            },
        ],
    }


def main() -> int:
    # 1. Swimlane primitive registered in widget_contract registry with closed props
    check("swimlane primitive is registered in PRIMITIVES", "swimlane" in PRIMITIVES)
    sw_entry = PRIMITIVES.get("swimlane")
    check("swimlane primitive has exact closed props",
          sw_entry is not None and sw_entry.props == frozenset({"label", "columns", "empty", "error"}))
    check("swimlane primitive binds rows to core.array.v1",
          sw_entry is not None and sw_entry.bindings == {"rows": "core.array.v1"})
    check("swimlane primitive has empty and error states",
          sw_entry is not None and sw_entry.empty_state == "empty" and sw_entry.error_state == "error")

    # 2. Spec strictly declares session-agents identity, read, and capability
    spec_path = AP / "widget_contract" / "specs" / "session-agents-0.1.yaml"
    check("session-agents-0.1.yaml spec file exists", spec_path.is_file())
    widget = load_widget_file(spec_path)
    check("spec declares session-agents identity and no actions",
          widget.id == "session-agents" and widget.version == "0.1" and widget.actions == ())
    check("spec declares exactly one read with read:session-agents capability",
          len(widget.reads) == 1 and set(widget.capabilities) == {"read:session-agents"})
    (read_op,) = widget.reads
    check("read is a store session-agents.v1 read with manual refresh",
          (read_op.id, read_op.source, read_op.operation, read_op.output_type, read_op.refresh["mode"]) ==
          ("agents", "store", "session-agents.v1", "session-agents.v1", "manual"))

    # 3. session-agents.v1 registered in READ_OPERATIONS and TYPES
    op_entry = READ_OPERATIONS.get("session-agents.v1")
    check("session-agents.v1 is registered in READ_OPERATIONS",
          op_entry is not None and op_entry.capability == "read:session-agents" and op_entry.source == "store")
    check("session-agents.v1 is registered in TYPES with operational data class",
          "session-agents.v1" in TYPES and TYPES["session-agents.v1"].data_class == "operational")
    check("read:session-agents capability is allow-listed",
          "read:session-agents" in ALLOWED_CAPABILITIES)

    # 4. Safe adapter read_session_agents_v1 strips undeclared fields and rejects malformed
    raw_with_extras = fake_agents_data()
    raw_with_extras["agents"][0]["secret_token"] = "sk-123456"
    raw_with_extras["agents"][0]["command"] = "rm -rf /"
    raw_with_extras["agents"][0]["tasks"][0]["secret_prompt"] = "ignore instructions"
    projection = read_session_agents_v1(raw_with_extras)
    check("safe adapter strips undeclared agent and task fields",
          "secret_token" not in projection["agents"][0]
          and "command" not in projection["agents"][0]
          and "secret_prompt" not in projection["agents"][0]["tasks"][0])
    check("safe adapter accepts callable input",
          read_session_agents_v1(fake_agents_data)["agents"][0]["name"] == "Hermes")

    malformed_cases = [
        {"agents": "not_a_list"},
        {"agents": [{"id": "a1", "name": "A", "runtime": "r", "status": "invalid_status", "current_task": None, "tasks": []}]},
        {"agents": [{"id": "a1", "name": "A", "runtime": "r", "status": "running", "current_task": None, "tasks": "not_a_list"}]},
        {"agents": [{"id": "a1", "name": "A", "runtime": "r", "status": "running", "current_task": None, "tasks": [{"id": "t1", "title": "T", "state": "s", "progress": 150}]}]},
        {"agents": [{"id": "a1", "name": "A", "runtime": "r", "status": "running", "current_task": None, "tasks": [{"id": "t1", "title": "T", "state": "s", "progress": -5}]}]},
        "not_a_dict",
    ]
    for idx, bad in enumerate(malformed_cases):
        failed_closed = False
        try:
            read_session_agents_v1(bad)
        except ReadAdapterError:
            failed_closed = True
        check(f"malformed input case {idx + 1} fails closed", failed_closed)

    # 5. Render tree shape and CLI artifact path with injected fake reader
    tree = render(widget, {"agents": fake_agents_data()}, {"agents": "fresh"})
    check("render tree root primitive is stack", tree["render"]["primitive"] == "stack")
    swimlane_child = next((c for c in tree["render"]["children"] if c["primitive"] == "swimlane"), None)
    check("render tree contains swimlane primitive node with rows",
          swimlane_child is not None and len(swimlane_child["props"]["rows"]) == 3)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        target = tmp_path / "session-agents.json"

        # Valid reader
        with io.StringIO() as buf, redirect_stdout(buf):
            res = _run_widget(
                Namespace(widget_command=None, view="session-agents", repo=None, snapshot=target),
                agents_reader=fake_agents_data,
            )
        check("CLI session-agents view succeeds with injected reader", res.status == "succeeded")
        check("artifact file was written to disk", target.is_file())
        artifact = json.loads(target.read_text(encoding="utf-8"))
        check("artifact has widget identity and no error",
              artifact["widget"] == {"id": "session-agents", "version": "0.1"} and artifact["error"] is None)
        check("artifact render state is ready", artifact["render"]["state"] == "ready")
        art_swimlane = next((c for c in artifact["render"]["children"] if c["primitive"] == "swimlane"), None)
        check("artifact contains ready swimlane node",
              art_swimlane is not None and len(art_swimlane["props"]["rows"]) == 3)

        # Failing reader -> error-state artifact
        def broken_reader():
            raise OSError("session store unavailable")

        target_err = tmp_path / "session-agents-err.json"
        with io.StringIO() as buf, redirect_stdout(buf):
            res_err = _run_widget(
                Namespace(widget_command=None, view="session-agents", repo=None, snapshot=target_err),
                agents_reader=broken_reader,
            )
        check("CLI settles succeeded on reader error", res_err.status == "succeeded")
        art_err = json.loads(target_err.read_text(encoding="utf-8"))
        check("error artifact has kind session_agents_read",
              art_err["error"]["kind"] == "session_agents_read"
              and "session store unavailable" in art_err["error"]["message"])
        check("error artifact renders error-state primitive",
              art_err["render"]["primitive"] == "error-state"
              and art_err["render"]["state"] == "error")

        # Malformed reader output -> error-state artifact
        def malformed_reader():
            return {"agents": "corrupted"}

        target_mal = tmp_path / "session-agents-mal.json"
        with io.StringIO() as buf, redirect_stdout(buf):
            res_mal = _run_widget(
                Namespace(widget_command=None, view="session-agents", repo=None, snapshot=target_mal),
                agents_reader=malformed_reader,
            )
        check("CLI settles succeeded on malformed reader output", res_mal.status == "succeeded")
        art_mal = json.loads(target_mal.read_text(encoding="utf-8"))
        check("malformed artifact has error-state primitive",
              art_mal["error"]["kind"] == "session_agents_read"
              and art_mal["render"]["primitive"] == "error-state")

    # 6. Shared maker.js and index.html contain swimlane rendering + pulse animation CSS
    maker_src = (AP / "widget" / "maker.js").read_text(encoding="utf-8")
    index_html_src = (AP / "widget" / "index.html").read_text(encoding="utf-8")
    maker_html_src = (AP / "widget" / "maker.html").read_text(encoding="utf-8")

    check("maker.js contains swimlane primitive branch", 'primitive === "swimlane"' in maker_src)
    check("index.html contains swimlane primitive branch", 'primitive==="swimlane"' in index_html_src or 'primitive === "swimlane"' in index_html_src)
    check("maker.js contains active marker class assignment", 'active running' in maker_src or 'swimlane-marker active' in maker_src or '.marker.active' in maker_src or 'markerClass += " active' in maker_src)
    check("index.html contains pulse animation keyframes", '@keyframes pulse' in index_html_src)
    check("index.html contains active marker pulse styling", '.marker.active' in index_html_src or '.marker.running' in index_html_src)
    check("maker.html contains pulse animation keyframes", '@keyframes pulse' in maker_html_src)

    # 7. Living fixture multi-state sequence (>= 3 states)
    fixture_path = REPO / "scripts" / "fixtures" / "widget_maker" / "agents_data.json"
    check("scripts/fixtures/widget_maker/agents_data.json exists", fixture_path.is_file())
    fix_data = json.loads(fixture_path.read_text(encoding="utf-8"))
    check("fixture contains sequence array with at least 3 states",
          "sequence" in fix_data and isinstance(fix_data["sequence"], list) and len(fix_data["sequence"]) >= 3)
    for s_idx, state in enumerate(fix_data["sequence"]):
        validated = read_session_agents_v1(state)
        check(f"sequence state {s_idx + 1} validates against session-agents schema",
              len(validated["agents"]) >= 2)

    # 8. Text fallback renderer (render_swimlane_text)
    node_to_render = {
        "primitive": "swimlane",
        "props": {
            "label": "Agents",
            "columns": ["Agent", "Tasks"],
            "rows": [
                {"name": "Hermes", "tasks": [{"title": "spec", "state": "done"}, {"title": "build", "state": "running"}]},
                {"name": "Codex", "tasks": [{"title": "test", "state": "queued"}]},
            ],
        },
    }
    rendered_text = render_swimlane_text(node_to_render)
    check("render_swimlane_text includes label heading", "Agents" in rendered_text)
    check("render_swimlane_text includes columns header", "Agent | Tasks" in rendered_text)
    check("render_swimlane_text includes agent rows with divider", "Hermes |" in rendered_text and "Codex |" in rendered_text)
    check("render_swimlane_text formats active marker with bullet", "\u25cf" in rendered_text)

    # 9. Manifest row in widgets.json
    manifest = json.loads((AP / "widget" / "widgets.json").read_text(encoding="utf-8"))
    agents_row = next((w for w in manifest["widgets"] if w["id"] == "agents"), None)
    check("manifest contains agents row", agents_row is not None)
    check("agents manifest row declares correct spec and artifact",
          agents_row is not None
          and agents_row["title"] == "Agents"
          and agents_row["spec"] == "widget_contract/specs/session-agents-0.1.yaml"
          and agents_row["artifact"] == "session-agents.json"
          and agents_row["hint"] == "cortxt widget --view session-agents")

    # 10. Node syntax checks for maker.js and html inline scripts
    res_ap = subprocess.run(["node", "--check", str(AP / "widget" / "maker.js")], capture_output=True, text=True)
    check("node --check passes on agent-platform/widget/maker.js", res_ap.returncode == 0)

    res_site = subprocess.run(["node", "--check", str(REPO / "site" / "public" / "widgets" / "maker.js")], capture_output=True, text=True)
    check("node --check passes on site/public/widgets/maker.js", res_site.returncode == 0)

    for h_path in [AP / "widget" / "index.html", AP / "widget" / "maker.html", REPO / "site" / "public" / "widgets" / "index.html"]:
        h_text = h_path.read_text(encoding="utf-8")
        scripts = re.findall(r"<script(?:\s+[^>]*)?>(.*?)</script>", h_text, re.DOTALL)
        for idx, s in enumerate(scripts):
            if not s.strip():
                continue
            with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as tf:
                tf.write(s)
                tf_p = tf.name
            r = subprocess.run(["node", "--check", tf_p], capture_output=True, text=True)
            check(f"node --check passes on {h_path.name} inline script {idx+1}", r.returncode == 0)

    # 11. Diacritics check across all touched files
    touched_files = [
        AP / "widget_contract" / "registry.py",
        AP / "widget_contract" / "swimlane_text.py",
        AP / "widget_contract" / "__init__.py",
        AP / "widget_contract" / "adapters" / "store_reads.py",
        AP / "widget_contract" / "specs" / "session-agents-0.1.yaml",
        AP / "cli" / "unified_cli.py",
        AP / "widget" / "maker.js",
        AP / "widget" / "maker.html",
        AP / "widget" / "index.html",
        AP / "widget" / "widgets.json",
        AP / "widget" / "session-agents.json",
        AP / "widget" / "fixtures" / "session-agents.json",
        AP / "widget" / "fixtures" / "agents_data.json",
        AP / "widget" / "fixtures" / "widgets.json",
        REPO / "scripts" / "fixtures" / "widget_maker" / "agents_data.json",
        REPO / "site" / "public" / "widgets" / "maker.js",
        REPO / "site" / "public" / "widgets" / "index.html",
        REPO / "site" / "public" / "widgets" / "specs" / "session-agents-0.1.yaml",
        REPO / "site" / "public" / "widgets" / "fixtures" / "session-agents.json",
        REPO / "site" / "public" / "widgets" / "fixtures" / "agents_data.json",
        REPO / "site" / "public" / "widgets" / "fixtures" / "widgets.json",
        Path(__file__),
    ]
    diacritic_pattern = re.compile(r"[\u00e5\u00e4\u00f6\u00c5\u00c4\u00d6]")
    diacritics_clean = True
    for f in touched_files:
        if f.is_file():
            text = f.read_text(encoding="utf-8")
            if diacritic_pattern.search(text):
                diacritics_clean = False
                print(f"FAIL diacritic character in {f}")

    check("zero a/o/u-with-diacritics across all touched files", diacritics_clean)

    if FAILS:
        print(f"\n{len(FAILS)} FAILED: {', '.join(FAILS)}")
        return 1
    print("\nall checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
