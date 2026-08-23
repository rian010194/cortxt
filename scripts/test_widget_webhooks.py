#!/usr/bin/env python3
"""Offline checks for the Webhooks standalone widget view (#338).

Run: python scripts/test_widget_webhooks.py
Prints ok/FAIL lines and exits non-zero on any failure.

Covers:
1. Registry entries for webhooks.status.v1 and pages.deploys.v1 with closed schemas.
2. Spec declaration (webhooks-0.1.yaml) with two reads and exact capabilities.
3. Safe adapters (read_webhooks_status_v1, read_pages_deploys_v1, redact_hook) and fail-closed validation.
4. Render tree structure (metric, hooks table, latest key-value, deployments table).
5. CLI artifact path for --view webhooks (valid + failing gh reader, redaction invariant).
6. CLI artifact path for --view pages-deploys (valid + failing pages reader, token redaction invariant).
7. Manifest row in widgets.json.
8. Node syntax check for index.html.
9. Diacritics check across all touched files.
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

import cli.unified_cli as unified_cli  # noqa: E402
from cli.unified_cli import _run_widget  # noqa: E402
from widget_contract.adapters.store_reads import (  # noqa: E402
    ReadAdapterError,
    read_pages_deploys_v1,
    read_webhooks_status_v1,
    redact_hook,
)
from widget_contract.loader import load_widget_file  # noqa: E402
from widget_contract.registry import (  # noqa: E402
    ALLOWED_CAPABILITIES,
    READ_OPERATIONS,
    TYPES,
)
from widget_contract.renderer import render  # noqa: E402
from widget_contract.validation import ValidationError, validate  # noqa: E402

FAILS: list[str] = []


def check(name: str, condition: bool) -> None:
    print(("ok " if condition else "FAIL ") + name)
    if not condition:
        FAILS.append(name)


def fake_raw_hooks(secret_marker: str = "ghp_supersecretvalue999") -> list[dict]:
    return [
        {
            "id": 101,
            "url": "https://api.github.com/repos/rian010194/cortxt/hooks/101",
            "name": "web",
            "active": True,
            "events": ["push", "pull_request"],
            "config": {
                "url": "https://api.cloudflare.com/pages/deploy-hook/123",
                "content_type": "json",
                "secret": secret_marker,
            },
        },
        {
            "id": 102,
            "url": "https://api.github.com/repos/rian010194/cortxt/hooks/102",
            "name": "web",
            "active": False,
            "events": ["issues"],
            "config": {
                "url": "https://notify.example.com/events",
                "content_type": "json",
                "secret": secret_marker,
            },
        },
    ]


def fake_pages_data() -> dict:
    return {
        "schema_version": 1,
        "project": "cortxt",
        "account": "c7c04f119f81234dc3d851bf6ff2adfe",
        "latest": {
            "id": "dep-456",
            "environment": "production",
            "created_on": "2026-08-23T18:00:00Z",
            "stage": "deploy",
            "status": "success",
        },
        "deployments": [
            {
                "id": "dep-456",
                "environment": "production",
                "created_on": "2026-08-23T18:00:00Z",
                "stage": "deploy",
            },
            {
                "id": "dep-455",
                "environment": "preview",
                "created_on": "2026-08-23T17:00:00Z",
                "stage": "deploy",
            },
        ],
    }


def main() -> int:
    # 1. Registry: schemas and read operations registered with correct metadata
    check("webhooks.status.v1 registered in TYPES", "webhooks.status.v1" in TYPES)
    check("webhooks.status.v1 is public-metadata", TYPES["webhooks.status.v1"].data_class == "public-metadata")
    check("pages.deploys.v1 registered in TYPES", "pages.deploys.v1" in TYPES)
    check("pages.deploys.v1 is operational", TYPES["pages.deploys.v1"].data_class == "operational")

    op_wh = READ_OPERATIONS.get("webhooks.status.v1")
    check("webhooks.status.v1 in READ_OPERATIONS", op_wh is not None)
    if op_wh:
        check("webhooks operation is store source", op_wh.source == "store")
        check("webhooks operation capability is read:webhooks", op_wh.capability == "read:webhooks")

    op_pg = READ_OPERATIONS.get("pages.deploys.v1")
    check("pages.deploys.v1 in READ_OPERATIONS", op_pg is not None)
    if op_pg:
        check("pages operation is store source", op_pg.source == "store")
        check("pages operation capability is read:pages", op_pg.capability == "read:pages")

    check("ALLOWED_CAPABILITIES contains read:webhooks", "read:webhooks" in ALLOWED_CAPABILITIES)
    check("ALLOWED_CAPABILITIES contains read:pages", "read:pages" in ALLOWED_CAPABILITIES)

    # 2. Spec: webhooks-0.1.yaml validation
    spec_path = AP / "widget_contract" / "specs" / "webhooks-0.1.yaml"
    widget = load_widget_file(spec_path)
    check("spec loads with id webhooks and version 0.1", widget.id == "webhooks" and widget.version == "0.1")
    check("spec declares zero actions", widget.actions == ())
    check("spec declares exactly two reads", len(widget.reads) == 2)
    read_map = {r.id: r for r in widget.reads}
    check("reads contain webhooks read", "webhooks" in read_map and read_map["webhooks"].operation == "webhooks.status.v1")
    check("reads contain pages read", "pages" in read_map and read_map["pages"].operation == "pages.deploys.v1")
    check("spec capabilities match exactly", set(widget.capabilities) == {"read:webhooks", "read:pages"})

    # 3. Adapters: redaction helper and safe projections
    secret_marker = "cfat_supersecret_token_never_leak_12345"
    raw_hooks = fake_raw_hooks(secret_marker=secret_marker)
    redacted = redact_hook(raw_hooks[0])
    check("redact_hook keeps id", redacted["id"] == 101)
    check("redact_hook projects endpoint url", redacted["url"] == "https://api.cloudflare.com/pages/deploy-hook/123")
    check("redact_hook keeps events", redacted["events"] == ["push", "pull_request"])
    check("redact_hook keeps active boolean", redacted["active"] is True)
    check("redact_hook excludes secret", "secret" not in redacted and "config" not in redacted)
    check("redact_hook secret string absent from dict keys and values", secret_marker not in str(redacted))

    wh_proj = read_webhooks_status_v1({
        "repo": "rian010194/cortxt",
        "total": 2,
        "active": 1,
        "hooks": raw_hooks,
    })
    check("read_webhooks_status_v1 valid schema_version", wh_proj["schema_version"] == 1)
    check("read_webhooks_status_v1 total and active counts", wh_proj["total"] == 2 and wh_proj["active"] == 1)
    check("read_webhooks_status_v1 hooks list length", len(wh_proj["hooks"]) == 2)
    check("read_webhooks_status_v1 excludes secret", secret_marker not in str(wh_proj))

    # Test malformed webhooks inputs fail closed
    malformed_wh = False
    try:
        read_webhooks_status_v1({"repo": 123, "hooks": []})
    except ReadAdapterError:
        malformed_wh = True
    check("read_webhooks_status_v1 rejects non-string repo", malformed_wh)

    malformed_wh_hooks = False
    try:
        read_webhooks_status_v1({"repo": "owner/repo", "hooks": "not-a-list"})
    except ReadAdapterError:
        malformed_wh_hooks = True
    check("read_webhooks_status_v1 rejects non-list hooks", malformed_wh_hooks)

    # Pages adapter test
    pages_raw = fake_pages_data()
    pg_proj = read_pages_deploys_v1(pages_raw)
    check("read_pages_deploys_v1 valid schema_version", pg_proj["schema_version"] == 1)
    check("read_pages_deploys_v1 latest id", pg_proj["latest"]["id"] == "dep-456")
    check("read_pages_deploys_v1 deployments length", len(pg_proj["deployments"]) == 2)

    # Test malformed pages inputs fail closed
    malformed_pg = False
    try:
        read_pages_deploys_v1({"project": "cortxt", "account": "c7c04f119f81234dc3d851bf6ff2adfe", "latest": "bad", "deployments": []})
    except ReadAdapterError:
        malformed_pg = True
    check("read_pages_deploys_v1 rejects non-dict latest", malformed_pg)

    # 4. Render tree verification
    tree = render(widget, {"webhooks": wh_proj, "pages": pg_proj}, {"webhooks": "fresh", "pages": "fresh"})
    check("render tree primitive is stack", tree["render"]["primitive"] == "stack")
    children = tree["render"]["children"]
    check("render tree has 4 children", len(children) == 4)
    check("child 0 is metric Active webhooks", children[0]["primitive"] == "metric" and children[0]["props"]["value"] == 1)
    check("child 1 is table Hooks", children[1]["primitive"] == "table" and len(children[1]["props"]["rows"]) == 2)
    check("child 2 is key-value Latest deployment", children[2]["primitive"] == "key-value" and children[2]["props"]["value"]["id"] == "dep-456")
    check("child 3 is table Deployments", children[3]["primitive"] == "table" and len(children[3]["props"]["rows"]) == 2)

    # 5. CLI --view webhooks with fake gh reader + secret redaction invariant
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        target_wh = tmp_path / "webhooks.json"
        saved_gh_reader = unified_cli._gh_webhooks_reader
        saved_pages_reader = unified_cli._pages_deploys_reader

        secret_token = "cfat_test_redaction_secret_xyz987"
        try:
            unified_cli._gh_webhooks_reader = lambda repo: fake_raw_hooks(secret_marker=secret_token)
            unified_cli._pages_deploys_reader = lambda *args, **kwargs: fake_pages_data()

            buf = io.StringIO()
            with redirect_stdout(buf):
                res = _run_widget(Namespace(widget_command=None, view="webhooks", repo="rian010194/cortxt",
                                            snapshot=target_wh, snapshot_input=None, plan_input=None))
            out_text = buf.getvalue()

            check("CLI --view webhooks succeeds", res.status == "succeeded")
            check("webhooks.json artifact exists", target_wh.is_file())
            artifact = json.loads(target_wh.read_text(encoding="utf-8"))
            check("webhooks.json state is ready", artifact["render"]["state"] == "ready")
            check("webhooks.json error is None", artifact.get("error") is None)
            check("webhooks.json has repo", artifact.get("repo") == "rian010194/cortxt")
            check("webhooks.json contains hook rows", len(artifact["render"]["children"][1]["props"]["rows"]) == 2)
            check("secret token ABSENT from webhooks.json", secret_token not in target_wh.read_text(encoding="utf-8"))
            check("secret token ABSENT from stdout", secret_token not in out_text)

            # Fail-closed test on gh error
            target_err = tmp_path / "webhooks-err.json"
            unified_cli._gh_webhooks_reader = lambda repo: (_ for _ in ()).throw(RuntimeError("API rate limit exceeded"))
            buf = io.StringIO()
            with redirect_stdout(buf):
                res_err = _run_widget(Namespace(widget_command=None, view="webhooks", repo="rian010194/cortxt",
                                                snapshot=target_err, snapshot_input=None, plan_input=None))
            check("CLI --view webhooks on failing gh reader returns succeeded envelope with error artifact", res_err.status == "succeeded")
            err_artifact = json.loads(target_err.read_text(encoding="utf-8"))
            check("failing gh reader produces error kind webhooks_read", err_artifact.get("error", {}).get("kind") == "webhooks_read")
            check("failing gh reader render state is error", err_artifact["render"]["state"] == "error")

            # Missing --repo test
            res_no_repo = _run_widget(Namespace(widget_command=None, view="webhooks", repo=None,
                                                snapshot=target_wh, snapshot_input=None, plan_input=None))
            check("missing --repo fails with input_error", res_no_repo.status == "failed" and res_no_repo.error.get("category") == "input_error")

        finally:
            unified_cli._gh_webhooks_reader = saved_gh_reader
            unified_cli._pages_deploys_reader = saved_pages_reader

    # 6. CLI --view pages-deploys with fake pages reader + token redaction invariant
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        target_pg = tmp_path / "pages-deploys.json"
        saved_pages_reader = unified_cli._pages_deploys_reader

        fake_cf_token = "cfat_pages_secret_token_1234567890abcdef"
        try:
            unified_cli._pages_deploys_reader = lambda *args, **kwargs: fake_pages_data()

            buf = io.StringIO()
            with redirect_stdout(buf):
                res = _run_widget(Namespace(widget_command=None, view="pages-deploys", repo=None,
                                            snapshot=target_pg, snapshot_input=None, plan_input=None))
            out_text = buf.getvalue()

            check("CLI --view pages-deploys succeeds", res.status == "succeeded")
            check("pages-deploys.json artifact exists", target_pg.is_file())
            artifact = json.loads(target_pg.read_text(encoding="utf-8"))
            check("pages-deploys.json state is ready", artifact["render"]["state"] == "ready")
            check("pages-deploys.json error is None", artifact.get("error") is None)
            check("pages-deploys.json latest id is dep-456", artifact["render"]["children"][2]["props"]["value"]["id"] == "dep-456")
            check("pages-deploys.json deployments count is 2", len(artifact["render"]["children"][3]["props"]["rows"]) == 2)
            check("fake token ABSENT from pages-deploys.json", fake_cf_token not in target_pg.read_text(encoding="utf-8"))
            check("fake token ABSENT from stdout", fake_cf_token not in out_text)

            # Fail-closed test on pages error
            target_err = tmp_path / "pages-err.json"
            unified_cli._pages_deploys_reader = lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError(f"API failure with {fake_cf_token}"))
            buf = io.StringIO()
            with redirect_stdout(buf):
                res_err = _run_widget(Namespace(widget_command=None, view="pages-deploys", repo=None,
                                                snapshot=target_err, snapshot_input=None, plan_input=None))
            check("CLI --view pages-deploys on failing reader returns succeeded envelope with error artifact", res_err.status == "succeeded")
            err_artifact = json.loads(target_err.read_text(encoding="utf-8"))
            check("failing pages reader produces error kind pages_read", err_artifact.get("error", {}).get("kind") == "pages_read")
            check("failing pages reader render state is error", err_artifact["render"]["state"] == "error")

        finally:
            unified_cli._pages_deploys_reader = saved_pages_reader

    # 7. Manifest check
    manifest_path = AP / "widget" / "widgets.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    wh_entry = next((w for w in manifest.get("widgets", []) if w.get("id") == "webhooks"), None)
    check("widgets.json contains webhooks row", wh_entry is not None)
    if wh_entry:
        check("webhooks manifest title is Webhooks", wh_entry.get("title") == "Webhooks")
        check("webhooks manifest spec path", wh_entry.get("spec") == "widget_contract/specs/webhooks-0.1.yaml")
        check("webhooks manifest artifact", wh_entry.get("artifact") == "webhooks.json")
        check("webhooks manifest hint", "cortxt widget --view webhooks" in wh_entry.get("hint", ""))

    # 8. Node syntax check on index.html script block
    index_html = (AP / "widget" / "index.html").read_text(encoding="utf-8")
    script_match = re.search(r"<script>(.*?)</script>", index_html, re.DOTALL)
    check("index.html contains script block", script_match is not None)
    if script_match:
        with tempfile.NamedTemporaryFile(suffix=".js", delete=False, mode="w", encoding="utf-8") as js_file:
            js_file.write(script_match.group(1))
            js_temp_path = Path(js_file.name)
        try:
            node_res = subprocess.run(["node", "--check", str(js_temp_path)], capture_output=True, text=True)
            check("node --check on index.html script passes", node_res.returncode == 0)
        finally:
            if js_temp_path.is_file():
                js_temp_path.unlink()

    # 9. Diacritics check across all touched files
    touched_files = [
        AP / "widget_contract" / "registry.py",
        AP / "widget_contract" / "adapters" / "store_reads.py",
        AP / "widget_contract" / "specs" / "webhooks-0.1.yaml",
        AP / "widget" / "widgets.json",
        AP / "cli" / "unified_cli.py",
        Path(__file__),
    ]
    diacritic_pattern = re.compile(r"[\u00e5\u00e4\u00f6\u00c5\u00c4\u00d6]")
    clean = True
    for file_path in touched_files:
        if file_path.is_file():
            text = file_path.read_text(encoding="utf-8")
            if diacritic_pattern.search(text):
                clean = False
                print(f"FAIL diacritics found in {file_path}")
    check("zero a/o/u-with-diacritics in all touched files", clean)

    if FAILS:
        print(f"\n{len(FAILS)} FAILED: {', '.join(FAILS)}")
        return 1
    print("\nall checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
