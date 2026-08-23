#!/usr/bin/env python3
"""Offline check test for Landing proof band and live CLI (TUI) + widget example pairs (Issue #348).

Run: python scripts/test_widget_examples.py
Prints ok/FAIL lines and exits non-zero on any failure.

Covers:
1. examples.json exists with required widgets: candidates, session-agents, usage-cost, pulse, docker, webhooks.
2. Every example entry has cli_command, tui_text (with key labels), artifact path, and tokens.
3. tui_text matches actual TUI renderer (render_tui) output over fixture render trees.
4. Landing page source contains proof band markers (horizontal scroll, CLI+TUI+widget pairs, maker.js reference, live badge).
5. Maker page (maker.html) contains horizontal examples band with scroll-snap.
6. Public docs widget page (index.html) contains horizontal examples band.
7. Multi-state living fixtures (agents_data.json, usage_data.json) exist with >= 3 states.
8. maker.js handles swimlanes, charts, and exports createSequenceStepper and startLivingDemo.
9. node --check passes on maker.js and HTML inline scripts.
10. No secret-shaped markers in fixtures or examples manifest.
11. serve.py remains loopback read-only.
12. Zero a/o/u-with-diacritics across all touched files.
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


def main() -> int:
    from widget_contract.tui import render_tui
    from widget_contract.tokens import load_tokens

    # 1. Examples manifest files exist and are valid JSON
    site_examples_path = REPO / "site" / "public" / "widgets" / "examples.json"
    ap_examples_path = AP / "widget" / "examples.json"
    scripts_examples_path = REPO / "scripts" / "fixtures" / "widget_maker" / "examples.json"

    check("site/public/widgets/examples.json exists", site_examples_path.is_file())
    check("agent-platform/widget/examples.json exists", ap_examples_path.is_file())
    check("scripts/fixtures/widget_maker/examples.json exists", scripts_examples_path.is_file())

    manifest = json.loads(site_examples_path.read_text(encoding="utf-8"))
    examples = manifest.get("examples", [])
    check("examples.json contains examples list", isinstance(examples, list) and len(examples) >= 6)

    example_ids = {ex.get("id") for ex in examples}
    required_ids = {"candidates", "session-agents", "usage-cost", "pulse", "docker", "webhooks"}
    check("examples covers required widgets (candidates, session-agents, usage-cost, pulse, docker, webhooks)",
          required_ids <= example_ids)

    # 2. Every example entry has cli_command, tui_text, artifact, tokens
    tokens = load_tokens()
    for ex in examples:
        eid = ex.get("id", "unknown")
        check(f"example {eid} has title", bool(ex.get("title")))
        check(f"example {eid} has valid cli_command", bool(ex.get("cli_command", "").startswith("cortxt widget")))
        check(f"example {eid} has non-empty tui_text", bool(ex.get("tui_text")))
        check(f"example {eid} has artifact declared", bool(ex.get("artifact")))
        check(f"example {eid} has tokens declared", bool(ex.get("tokens")))

        artifact_file = REPO / "site" / "public" / "widgets" / ex.get("artifact", "")
        check(f"artifact file exists for example {eid}", artifact_file.is_file())
        if artifact_file.is_file():
            art_data = json.loads(artifact_file.read_text(encoding="utf-8"))
            render_tree = art_data.get("render") or art_data
            check(f"artifact for {eid} has valid render tree", bool(render_tree.get("primitive")))

            # Verify tui_text matches render_tui output
            expected_tui = render_tui(art_data, tokens=tokens, force_ansi=False)
            check(f"tui_text for {eid} matches render_tui output", ex.get("tui_text") == expected_tui)

    # 3. Check specific key labels in TUI texts
    tui_by_id = {ex["id"]: ex.get("tui_text", "") for ex in examples}
    check("candidates tui_text contains Candidates heading and frontier group",
          "=== Candidates ===" in tui_by_id.get("candidates", "") and "[frontier]" in tui_by_id.get("candidates", ""))
    check("session-agents tui_text contains swimlane markers and agent sessions",
          "Hermes" in tui_by_id.get("session-agents", "") and "●" in tui_by_id.get("session-agents", ""))
    check("usage-cost tui_text contains tokens by runtime and sparkline/series",
          "Tokens by runtime" in tui_by_id.get("usage-cost", "") and "Usage over time" in tui_by_id.get("usage-cost", ""))
    check("pulse tui_text contains Session Pulse heading and workstreams",
          "=== Session Pulse ===" in tui_by_id.get("pulse", "") and "[Workstreams]" in tui_by_id.get("pulse", ""))
    check("docker tui_text contains Docker Status and Containers table",
          "=== Docker Status ===" in tui_by_id.get("docker", "") and "[Containers]" in tui_by_id.get("docker", ""))
    check("webhooks tui_text contains Webhooks heading and hooks table",
          "=== Webhooks ===" in tui_by_id.get("webhooks", "") and "[Hooks]" in tui_by_id.get("webhooks", ""))

    # 4. Landing page source contains proof band markers
    landing_astro = (REPO / "site" / "src" / "pages" / "index.astro").read_text(encoding="utf-8")
    landing_css = (REPO / "site" / "src" / "styles" / "landing.css").read_text(encoding="utf-8")

    check("index.astro contains proof-band section", "proof-band" in landing_astro)
    check("index.astro contains proof-band-scroll container", "proof-band-scroll" in landing_astro)
    check("index.astro contains proof-pair-card articles", "proof-pair-card" in landing_astro)
    check("index.astro contains proof-cli-pane and proof-widget-pane",
          "proof-cli-pane" in landing_astro and "proof-widget-pane" in landing_astro)
    check("index.astro contains proof-cli-tui and proof-widget-mount",
          "proof-cli-tui" in landing_astro and "proof-widget-mount" in landing_astro)
    check("index.astro references maker.js", "/widgets/maker.js" in landing_astro or "maker.js" in landing_astro)
    check("index.astro contains live-badge marker", "live-badge" in landing_astro)
    check("index.astro contains living demo stepper integration",
          "startLivingDemo" in landing_astro or "createSequenceStepper" in landing_astro)

    check("landing.css contains proof-band styles", ".proof-band" in landing_css)
    check("landing.css contains horizontal scroll styles",
          "overflow-x:auto" in landing_css or "overflow-x: auto" in landing_css)
    check("landing.css contains scroll-snap styles",
          "scroll-snap-type:x mandatory" in landing_css or "scroll-snap-type: x mandatory" in landing_css)
    check("landing.css contains proof-pair-card flex layout", ".proof-pair-card" in landing_css)
    check("landing.css contains live-badge and pulse-dot animation",
          ".live-badge" in landing_css and ".pulse-dot" in landing_css and "@keyframes pulse" in landing_css)

    # 5. Maker page contains horizontal examples band
    maker_html = (AP / "widget" / "maker.html").read_text(encoding="utf-8")
    check("maker.html contains examples-band container", "examples-band" in maker_html)
    check("maker.html contains examples-scroll container", "examples-scroll" in maker_html)
    check("maker.html contains example-chip styling", ".example-chip" in maker_html)
    check("maker.html contains scroll-snap-type on examples-scroll", "scroll-snap-type: x mandatory" in maker_html)
    check("maker.html renders examples band dynamically", "renderExamplesBand" in maker_html)

    # 6. Public docs widget page contains horizontal examples band
    docs_html = (REPO / "site" / "public" / "widgets" / "index.html").read_text(encoding="utf-8")
    check("docs index.html contains examples-band container", "examples-band" in docs_html)
    check("docs index.html contains examples-scroll container", "examples-scroll" in docs_html)
    check("docs index.html contains example-chip styling", ".example-chip" in docs_html)
    check("docs index.html renders examples band", "renderExamplesBand" in docs_html)

    # 7. Multi-state living fixtures exist
    agents_data_file = REPO / "site" / "public" / "widgets" / "fixtures" / "agents_data.json"
    check("agents_data.json exists", agents_data_file.is_file())
    if agents_data_file.is_file():
        agents_data = json.loads(agents_data_file.read_text(encoding="utf-8"))
        states = agents_data.get("states", [])
        check("agents_data.json contains >= 3 states for live stepping", len(states) >= 3)

    usage_data_file = REPO / "site" / "public" / "widgets" / "fixtures" / "usage_data.json"
    check("usage_data.json exists", usage_data_file.is_file())
    if usage_data_file.is_file():
        usage_data = json.loads(usage_data_file.read_text(encoding="utf-8"))
        states = usage_data.get("states", [])
        check("usage_data.json contains >= 3 states for live stepping", len(states) >= 3)

    # 8. maker.js capabilities
    maker_js = (AP / "widget" / "maker.js").read_text(encoding="utf-8")
    check("maker.js exports createSequenceStepper", "createSequenceStepper" in maker_js)
    check("maker.js exports startLivingDemo", "startLivingDemo" in maker_js)
    check("maker.js handles swimlane primitive", '"swimlane"' in maker_js or "'swimlane'" in maker_js)
    check("maker.js handles bar primitive", '"bar"' in maker_js or "'bar'" in maker_js)
    check("maker.js handles line primitive", '"line"' in maker_js or "'line'" in maker_js)
    check("maker.js applies visual tokens", "applyTokens" in maker_js and "DEFAULT_TOKENS" in maker_js)

    # 9. Node syntax checks on JS and inline HTML scripts
    node_site_maker = subprocess.run(["node", "--check", str(REPO / "site" / "public" / "widgets" / "maker.js")],
                                     capture_output=True, text=True)
    check("node --check passes on site/public/widgets/maker.js", node_site_maker.returncode == 0)

    node_ap_maker = subprocess.run(["node", "--check", str(AP / "widget" / "maker.js")],
                                   capture_output=True, text=True)
    check("node --check passes on agent-platform/widget/maker.js", node_ap_maker.returncode == 0)

    def check_inline_scripts(html_text: str, label: str) -> None:
        script_pattern = re.compile(r"<script(?![^>]*src=)[^>]*>(.*?)</script>", re.DOTALL | re.IGNORECASE)
        scripts = script_pattern.findall(html_text)
        for i, code in enumerate(scripts, start=1):
            with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as tf:
                tf.write(code)
                tname = tf.name
            res = subprocess.run(["node", "--check", tname], capture_output=True, text=True)
            Path(tname).unlink(missing_ok=True)
            check(f"node --check passes on {label} inline script #{i}", res.returncode == 0)

    check_inline_scripts(maker_html, "maker.html")
    check_inline_scripts(docs_html, "docs index.html")

    # 10. Fixtures contain zero secret-shaped markers
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
        REPO / "site" / "public" / "widgets",
    ]

    secrets_found: list[str] = []
    for d in fixture_dirs:
        if not d.is_dir():
            continue
        for p in d.glob("*.json"):
            content = p.read_text(encoding="utf-8")
            for pattern in secret_patterns:
                if pattern.search(content):
                    secrets_found.append(f"{p}: matches {pattern.pattern}")

    check("fixtures and manifests contain zero secret-shaped markers", len(secrets_found) == 0)
    if secrets_found:
        for s in secrets_found:
            print("  FAIL secret leak detected:", s)

    # 11. serve.py remains loopback read-only
    serve_py = (AP / "widget" / "serve.py").read_text(encoding="utf-8")
    check("serve.py binds to loopback only", 'HOST = "127.0.0.1"' in serve_py)
    check("serve.py has no do_POST handler", "do_POST" not in serve_py)
    check("serve.py uses SimpleHTTPRequestHandler", "SimpleHTTPRequestHandler" in serve_py)

    # 12. Diacritics check across all touched/created files
    touched_files = [
        REPO / "site" / "src" / "pages" / "index.astro",
        REPO / "site" / "src" / "styles" / "landing.css",
        REPO / "site" / "public" / "widgets" / "examples.json",
        REPO / "site" / "public" / "widgets" / "maker.js",
        REPO / "site" / "public" / "widgets" / "index.html",
        REPO / "site" / "public" / "widgets" / "fixtures" / "session-agents.json",
        REPO / "site" / "public" / "widgets" / "fixtures" / "agents_data.json",
        AP / "widget" / "maker.html",
        AP / "widget" / "maker.js",
        AP / "widget" / "examples.json",
        AP / "widget" / "session-agents.json",
        AP / "widget" / "snapshot.json",
        AP / "widget" / "fixtures" / "session-agents.json",
        AP / "widget" / "fixtures" / "agents_data.json",
        AP / "widget_contract" / "tui.py",
        REPO / "scripts" / "fixtures" / "widget_maker" / "examples.json",
        REPO / "scripts" / "fixtures" / "widget_maker" / "session-agents.json",
        REPO / "scripts" / "fixtures" / "widget_maker" / "agents_data.json",
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
