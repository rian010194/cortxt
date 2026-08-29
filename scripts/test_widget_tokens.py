#!/usr/bin/env python3
"""Offline check test for shared editable visual tokens (Issue #343).

Run: python scripts/test_widget_tokens.py
Prints ok/FAIL lines and exits non-zero on any failure.

Covers:
1. tokens.json exists and validates against closed VISUAL_TOKENS_SCHEMA in registry.py.
2. Schema rejects malformed tokens (unknown key, wrong type, missing sections).
3. load_tokens() loads and validates tokens, raises typed TokensError on malformed.
4. ansi_map() maps each token color key to ANSI escape codes.
5. maker.js contains applyTokens, defaultTokens, and CSS variable setters.
6. maker.html contains tokens editor markers (textarea, Apply, Reset, error line).
7. index.html contains tokens application markers and loads tokens.
8. node --check passes on maker.js and inline scripts in maker.html and index.html.
9. Zero a/o/u-with-diacritics in all checked files.
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
    from widget_contract.registry import TYPES, VISUAL_TOKENS_SCHEMA
    from widget_contract.tokens import TokensError, ansi_map, load_tokens
    from widget_contract.validation import ValidationError, validate

    # 1. tokens.json exists and validates against closed schema
    tokens_file = AP / "widget" / "tokens.json"
    check("agent-platform/widget/tokens.json exists", tokens_file.is_file())

    data = json.loads(tokens_file.read_text(encoding="utf-8"))
    valid_schema = False
    try:
        validate(data, VISUAL_TOKENS_SCHEMA)
        valid_schema = True
    except ValidationError:
        valid_schema = False
    check("tokens.json validates against VISUAL_TOKENS_SCHEMA", valid_schema)

    check("visual-tokens.v1 is registered in TYPES", "visual-tokens.v1" in TYPES)
    check("visual-tokens.v1 data_class is public-metadata", TYPES["visual-tokens.v1"].data_class == "public-metadata")

    # 2. Schema rejection modes
    # Unknown top-level key
    try:
        validate({**data, "unexpected_extra": 1}, VISUAL_TOKENS_SCHEMA)
        check("schema rejects unknown top-level key", False)
    except ValidationError:
        check("schema rejects unknown top-level key", True)

    # Missing section
    for sec in ("colors", "typography", "spacing", "radius", "density"):
        corrupted = {k: v for k, v in data.items() if k != sec}
        try:
            validate(corrupted, VISUAL_TOKENS_SCHEMA)
            check(f"schema rejects missing {sec} section", False)
        except ValidationError:
            check(f"schema rejects missing {sec} section", True)

    # Unknown key in section
    bad_colors = {**data["colors"], "extra_field": "#000"}
    try:
        validate({**data, "colors": bad_colors}, VISUAL_TOKENS_SCHEMA)
        check("schema rejects unknown key in colors", False)
    except ValidationError:
        check("schema rejects unknown key in colors", True)

    # Wrong type in section
    bad_type = {**data["colors"], "accent": 9999}
    try:
        validate({**data, "colors": bad_type}, VISUAL_TOKENS_SCHEMA)
        check("schema rejects wrong type in colors", False)
    except ValidationError:
        check("schema rejects wrong type in colors", True)

    # 3. load_tokens() accepts valid + raises on malformed
    loaded = load_tokens()
    check("load_tokens() succeeds on default tokens.json", isinstance(loaded, dict) and "colors" in loaded)

    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as tmp:
        tmp.write("{ invalid json")
        tmp_name = tmp.name
    try:
        load_tokens(tmp_name)
        check("load_tokens() raises TokensError on malformed JSON", False)
    except TokensError:
        check("load_tokens() raises TokensError on malformed JSON", True)
    finally:
        Path(tmp_name).unlink(missing_ok=True)

    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as tmp:
        tmp.write(json.dumps({"colors": {}}))
        tmp_name = tmp.name
    try:
        load_tokens(tmp_name)
        check("load_tokens() raises TokensError on invalid schema", False)
    except TokensError:
        check("load_tokens() raises TokensError on invalid schema", True)
    finally:
        Path(tmp_name).unlink(missing_ok=True)

    # 4. ansi_map() returns ANSI codes for all color keys
    amap = ansi_map(loaded)
    color_keys = [
        "background", "surface", "layer", "hover", "stroke", "strong",
        "text", "muted", "dim", "accent", "blue", "ok", "warn", "bad", "reset"
    ]
    for ck in color_keys:
        check(f"ansi_map contains color key {ck}", ck in amap and "\x1b[" in amap[ck])

    # 5. maker.js contains applyTokens, defaultTokens, and CSS variable markers
    maker_js_path = AP / "widget" / "maker.js"
    check("maker.js exists", maker_js_path.is_file())
    maker_src = maker_js_path.read_text(encoding="utf-8")
    check("maker.js exports applyTokens", "applyTokens" in maker_src)
    check("maker.js exports defaultTokens", "defaultTokens" in maker_src)
    check("maker.js sets --token-bg or --token-background", "--token-bg" in maker_src or "--token-background" in maker_src)
    check("maker.js sets --token-accent", "--token-accent" in maker_src)
    check("maker.js sets --token-font-sans", "--token-font-sans" in maker_src)
    check("maker.js sets --token-font-mono", "--token-font-mono" in maker_src)
    check("maker.js sets --token-gap", "--token-gap" in maker_src)
    check("maker.js sets --token-radius", "--token-radius" in maker_src)

    # Test maker.js in Node
    node_test = """
    const maker = require('./agent-platform/widget/maker.js');
    const t = maker.defaultTokens();
    if (!t || !t.colors || t.colors.accent !== '#8fa3c7') process.exit(1);
    const target = { style: { setProperty(k, v) { this[k] = v; } } };
    maker.applyTokens(t, target);
    if (target.style['--token-accent'] !== '#8fa3c7') process.exit(2);
    if (target.style['--token-ok'] !== '#a8d5ba') process.exit(3);
    console.log('NODE_TOKENS_OK');
    """
    res_node = subprocess.run(["node", "-e", node_test], capture_output=True, text=True, cwd=str(REPO))
    check("maker.js token functions execute in Node", "NODE_TOKENS_OK" in res_node.stdout)

    # 6. The integrated Maker module contains the token editor.
    maker_surface = maker_js_path.read_text(encoding="utf-8")
    check("integrated maker contains tokens editor textarea", "data-mk-tokens-input" in maker_surface)
    check("integrated maker contains Apply button", 'data-mk-action="apply-tokens">Apply' in maker_surface)
    check("integrated maker contains Reset button", 'data-mk-action="reset-tokens">Reset' in maker_surface)
    check("integrated maker contains error line", "data-mk-tokens-error" in maker_surface)
    check("integrated maker wires applyTokens", "applyTokens" in maker_surface)

    # 7. The OS shell consumes canonical tokens through the shared maker.js
    # adapter at runtime (ADR-043). index.html loads maker.js before the
    # shell; the shell's loadTokens() fetches tokens.json and applies the
    # canonical tokens via window.WidgetMaker.applyTokens. Inline markup
    # markers are obsolete (retired with the S6 shell changes) and must not
    # be reintroduced.
    index_html_path = AP / "widget" / "index.html"
    check("index.html exists", index_html_path.is_file())
    index_html = index_html_path.read_text(encoding="utf-8")
    check("index.html loads maker.js before the shell", index_html.index('src="maker.js"') < index_html.index('src="work-console.js"'))
    work_console = (AP / "widget" / "work-console.js").read_text(encoding="utf-8")
    check("shell loadTokens() fetches tokens.json", 'fetch("tokens.json"' in work_console)
    check("shell applies tokens via WidgetMaker adapter", "window.WidgetMaker" in work_console and "applyTokens" in work_console)
    check("index.html does not rely on obsolete inline applyTokens markup", "applyTokens" not in index_html)

    # 8. node --check passes on maker.js and inline scripts
    res_mjs = subprocess.run(["node", "--check", str(maker_js_path)], capture_output=True, text=True)
    check("node --check passes on maker.js", res_mjs.returncode == 0)

    for html_path in (index_html_path,):
        html_content = html_path.read_text(encoding="utf-8")
        scripts = re.findall(r"<script(?:\s+[^>]*)?>(.*?)</script>", html_content, re.DOTALL)
        for idx, script_body in enumerate(scripts):
            if not script_body.strip():
                continue
            with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as tmp:
                tmp.write(script_body)
                tmp_name = tmp.name
            try:
                res_check = subprocess.run(["node", "--check", tmp_name], capture_output=True, text=True)
                check(f"node --check passes on {html_path.name} inline script #{idx+1}", res_check.returncode == 0)
            finally:
                Path(tmp_name).unlink(missing_ok=True)

    # 9. Zero a/o/u-with-diacritics in checked files
    checked_files = [
        AP / "widget" / "tokens.json",
        AP / "widget" / "maker.js",
        AP / "widget" / "index.html",
        AP / "widget_contract" / "registry.py",
        AP / "widget_contract" / "tokens.py",
        AP / "tests" / "widget_contract" / "test_tokens.py",
        REPO / "site" / "public" / "widgets" / "tokens.json",
        REPO / "site" / "public" / "widgets" / "maker.js",
        Path(__file__),
    ]
    diacritic_pattern = re.compile(r"[\u00e5\u00e4\u00f6\u00c5\u00c4\u00d6]")
    diacritics_clean = True
    for f in checked_files:
        if f.is_file():
            text = f.read_text(encoding="utf-8")
            if diacritic_pattern.search(text):
                diacritics_clean = False
                print(f"FAIL diacritic character in {f}")

    check("zero a/o/u-with-diacritics in checked files", diacritics_clean)

    if FAILS:
        print(f"\n{len(FAILS)} FAILED: {', '.join(FAILS)}")
        return 1
    print("\nall checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
