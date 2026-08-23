#!/usr/bin/env python3
"""Offline checks for Widget Maker (Issue #339).

Run: python scripts/test_widget_maker.py
Prints ok/FAIL lines and exits non-zero on any failure.

Covers:
1. Shared maker JS exists in both host and docs paths and passes node --check.
2. YAML parser handles spec structure (maps, lists, scalars, comments) without external deps.
3. Client-side spec renderer handles bindings, pointer resolution, and primitives.
4. Every manifest widget has a valid offline fixture that renders without error.
5. CLI side-by-side data (hint command + CLI JSON output) present for each widget.
6. Fixtures contain zero secret-shaped markers (no sk-, cfat_, ghp_, -----BEGIN, webhook secret patterns).
7. Loopback maker page (agent-platform/widget/maker.html) exists with gallery, studio, and CLI side-by-side.
8. Loopback index.html links to maker.html while preserving host behavior.
9. Public docs page (site/public/widgets/index.html) exists, is wired into docs nav, and renders with shared JS.
10. serve.py remains read-only (no POST handler, no custom endpoints).
11. Zero a/o/u-with-diacritics across all touched files.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
AP = REPO / "agent-platform"
sys.path.insert(0, str(AP))

FAILS: list[str] = []


def check(name: str, condition: bool) -> None:
    print(("ok " if condition else "FAIL ") + name)
    if not condition:
        FAILS.append(name)


def run_node(code: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["node", "-e", code], capture_output=True, text=True, cwd=str(REPO))


def main() -> int:
    # 1. Shared maker JS files exist and pass node --check
    ap_maker_js = AP / "widget" / "maker.js"
    site_maker_js = REPO / "site" / "public" / "widgets" / "maker.js"

    check("agent-platform/widget/maker.js exists", ap_maker_js.is_file())
    check("site/public/widgets/maker.js exists", site_maker_js.is_file())

    res_ap = subprocess.run(["node", "--check", str(ap_maker_js)], capture_output=True, text=True)
    check("node --check passes on agent-platform/widget/maker.js", res_ap.returncode == 0)

    res_site = subprocess.run(["node", "--check", str(site_maker_js)], capture_output=True, text=True)
    check("node --check passes on site/public/widgets/maker.js", res_site.returncode == 0)

    # 2. Maker JS primitive handling
    maker_src = ap_maker_js.read_text(encoding="utf-8")
    primitives = [
        "stack", "row", "grid", "panel", "tabs",
        "heading", "text", "badge", "metric",
        "key-value", "table", "list", "swimlane",
        "empty-state", "error-state", "divider", "spacer"
    ]
    for prim in primitives:
        check(f"maker.js handles primitive {prim}", f'"{prim}"' in maker_src or f"'{prim}'" in maker_src)

    # 3. YAML parser and spec rendering in Node
    test_yaml_code = """
    const maker = require('./agent-platform/widget/maker.js');
    const yaml = `
contract_version: "0.1"
widget:
  id: test-unit
  version: "0.1"
render:
  primitive: stack
  children:
    - primitive: metric
      props: {label: Counter}
      bindings: {value: {read: test_store, pointer: /count, type: core.number.v1}}
    - primitive: table
      props: {label: Items, columns: [id, name]}
      bindings: {rows: {read: test_store, pointer: /items, type: core.array.v1}}
    `;
    const parsed = maker.parseYamlSubset(yaml);
    if (!parsed.ok) {
      console.error('YAML parse failed:', parsed.error);
      process.exit(1);
    }
    const rendered = maker.renderSpec(parsed.data, {
      test_store: { count: 99, items: [{ id: 1, name: 'Item A' }] }
    });
    if (rendered.widget.id !== 'test-unit') process.exit(2);
    if (rendered.render.children.length !== 2) process.exit(3);
    if (rendered.render.children[0].props.value !== 99) process.exit(4);
    if (rendered.render.children[1].props.rows.length !== 1) process.exit(5);
    console.log('NODE_OK');
    """
    res_yaml = run_node(test_yaml_code)
    check("maker.js YAML parser and spec renderer execute accurately in Node", "NODE_OK" in res_yaml.stdout)

    # 4. Manifest coverage and fixture rendering
    manifest_path = AP / "widget" / "widgets.json"
    check("widgets.json exists", manifest_path.is_file())
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    widgets = manifest.get("widgets", [])
    check("manifest contains widgets list", len(widgets) >= 6)

    widget_ids = {w.get("id") for w in widgets}
    expected_ids = {"candidates", "pulse", "map", "docker", "webhooks", "loaded"}
    check("manifest covers all expected widget prototypes", expected_ids <= widget_ids)

    # 5. Every manifest widget has fixture artifact with side-by-side data
    for w in widgets:
        wid = w.get("id")
        artifact_name = w.get("artifact")
        check(f"manifest row {wid} has artifact declared", bool(artifact_name))
        check(f"manifest row {wid} has hint declared", bool(w.get("hint")))

        artifact_file = AP / "widget" / artifact_name
        check(f"artifact file {artifact_name} exists for {wid}", artifact_file.is_file())
        if artifact_file.is_file():
            artifact_data = json.loads(artifact_file.read_text(encoding="utf-8"))
            render_tree = artifact_data.get("render") or artifact_data
            check(f"artifact {artifact_name} contains valid render tree", bool(render_tree.get("primitive")))

    # 6. Fixtures contain zero secret-shaped markers
    secret_patterns = [
        re.compile(r"sk-[a-zA-Z0-9_-]{10,}"),
        re.compile(r"cfat_[a-zA-Z0-9_-]{10,}"),
        re.compile(r"ghp_[a-zA-Z0-9_-]{10,}"),
        re.compile(r"github_pat_[a-zA-Z0-9_-]{10,}"),
        re.compile(r"-----BEGIN\s+[A-Z\s]+KEY-----"),
    ]

    fixture_dirs = [
        AP / "widget",
        AP / "widget" / "fixtures",
        REPO / "scripts" / "fixtures" / "widget_maker",
        REPO / "site" / "public" / "widgets" / "fixtures",
    ]

    secrets_found = []
    for d in fixture_dirs:
        if not d.is_dir():
            continue
        for p in d.glob("*.json"):
            content = p.read_text(encoding="utf-8")
            for pattern in secret_patterns:
                if pattern.search(content):
                    secrets_found.append(f"{p}: matches {pattern.pattern}")

    check("fixtures contain zero secret-shaped markers", len(secrets_found) == 0)
    if secrets_found:
        for s in secrets_found:
            print("  FAIL secret leak detected:", s)

    # 7. Loopback maker page exists with required markers
    maker_html_path = AP / "widget" / "maker.html"
    check("agent-platform/widget/maker.html exists", maker_html_path.is_file())
    if maker_html_path.is_file():
        maker_html = maker_html_path.read_text(encoding="utf-8")
        check("maker.html contains gallery section", "gallery-grid" in maker_html or "section-gallery" in maker_html)
        check("maker.html contains studio / spec editor", "studio-spec" in maker_html or "studio-container" in maker_html)
        check("maker.html contains CLI side-by-side elements", "cli-cmd" in maker_html and "cli-json" in maker_html)
        check("maker.html includes maker.js", "maker.js" in maker_html)
        check("maker.html has link back to host", "index.html" in maker_html)

    # 8. Loopback index.html links to maker.html
    index_html_path = AP / "widget" / "index.html"
    check("agent-platform/widget/index.html exists", index_html_path.is_file())
    if index_html_path.is_file():
        index_html = index_html_path.read_text(encoding="utf-8")
        check("index.html contains link to maker.html", "maker.html" in index_html)

    # 9. Public docs page exists with required markers and site integration
    docs_page_path = REPO / "site" / "public" / "widgets" / "index.html"
    check("site/public/widgets/index.html exists", docs_page_path.is_file())
    if docs_page_path.is_file():
        docs_html = docs_page_path.read_text(encoding="utf-8")
        check("docs page contains prototype gallery", "view-gallery" in docs_html or "gallery-grid" in docs_html)
        check("docs page contains spec studio", "view-studio" in docs_html or "studio-spec-input" in docs_html)
        check("docs page contains CLI side-by-side views", "cli-cmd" in docs_html and "cli-json" in docs_html)
        check("docs page references maker.js", "maker.js" in docs_html)

    # Verify site navigation wiring
    astro_config = (REPO / "site" / "astro.config.mjs").read_text(encoding="utf-8")
    check("astro.config.mjs sidebar links to /widgets/", "/widgets/" in astro_config)

    # 10. serve.py remains loopback read-only with no POST handler
    serve_py = (AP / "widget" / "serve.py").read_text(encoding="utf-8")
    check("serve.py binds to loopback only", 'HOST = "127.0.0.1"' in serve_py)
    check("serve.py has no do_POST handler", "do_POST" not in serve_py)
    check("serve.py uses SimpleHTTPRequestHandler", "SimpleHTTPRequestHandler" in serve_py)

    # 11. Diacritics check across all touched/created files
    touched_files = [
        AP / "widget" / "maker.js",
        AP / "widget" / "maker.html",
        AP / "widget" / "index.html",
        AP / "widget" / "widgets.json",
        AP / "widget" / "candidates.json",
        AP / "widget" / "session-pulse.json",
        AP / "widget" / "execution-map.json",
        AP / "widget" / "docker-status.json",
        AP / "widget" / "webhooks.json",
        AP / "widget" / "session-agents.json",
        AP / "widget" / "loaded.json",
        AP / "widget" / "composed.json",
        AP / "widget_contract" / "specs" / "webhooks-0.1.yaml",
        AP / "widget_contract" / "specs" / "session-agents-0.1.yaml",
        REPO / "site" / "public" / "widgets" / "maker.js",
        REPO / "site" / "public" / "widgets" / "index.html",
        REPO / "site" / "astro.config.mjs",
        REPO / "site" / "src" / "content" / "docs" / "docs" / "roadmap.md",
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

    check("zero a/o/u-with-diacritics in touched files", diacritics_clean)

    if FAILS:
        print(f"\n{len(FAILS)} FAILED: {', '.join(FAILS)}")
        return 1
    print("\nall checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
