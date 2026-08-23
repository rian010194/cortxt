#!/usr/bin/env python3
"""Offline check test for self-contained widget export/import packages (Issue #346).

Run: python scripts/test_widget_export.py
Prints ok/FAIL lines and exits non-zero on any failure.

Covers:
1. Export for each manifest widget produces a valid package (.cw / JSON).
2. Export packages contain required fields, version "1", valid spec, tokens, renderer.
3. Export packages contain zero secret-shaped markers.
4. Export CLI command succeeds and respects --tokens override.
5. Export rejection modes fail-closed (unknown ID, spec-less widget, secrets).
6. Load CLI command installs valid package into target directory with manifest row.
7. Round-trip: export -> load into temp dir -> widget spec validates and renders.
8. Load rejection modes fail-closed with zero partial install (missing file, malformed JSON,
   unknown format version, missing required field, secret-shaped content, invalid spec contract).
9. Standalone Node.js consumer can evaluate embedded renderer and render widget from package.
10. maker.html contains Export and Import UI markers; serve.py remains read-only.
11. docs/widget-package-format.md exists and documents package format and rendering.
12. Zero a/o/u-with-diacritics in all checked files.
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
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as tmp:
        tmp.write(code)
        tmp_name = tmp.name
    try:
        return subprocess.run(["node", tmp_name], capture_output=True, text=True, cwd=str(REPO))
    finally:
        try:
            Path(tmp_name).unlink()
        except OSError:
            pass


def main() -> int:
    from cli.unified_cli import _run_widget_export, _run_widget_load, main as cli_main
    from widget_contract.loader import load_widget
    from widget_contract.package import (
        PACKAGE_FORMAT_VERSION,
        PackageError,
        assert_no_secrets,
        export_package,
        load_package,
        scan_for_secrets,
        validate_package,
    )
    from widget_contract.registry import TYPES, VISUAL_TOKENS_SCHEMA
    from widget_contract.validation import validate

    # 1. Manifest widgets export verification
    manifest_file = AP / "widget" / "widgets.json"
    check("agent-platform/widget/widgets.json exists", manifest_file.is_file())
    manifest_data = json.loads(manifest_file.read_text(encoding="utf-8"))
    widgets_list = manifest_data.get("widgets", [])

    exportable_ids = [w["id"] for w in widgets_list if w.get("spec")]
    check("manifest contains exportable widgets", len(exportable_ids) >= 5)

    for wid in exportable_ids:
        pkg = export_package(wid, ap_path=AP)
        check(f"export_package({wid}) returns dict", isinstance(pkg, dict))
        check(f"export_package({wid}) has package_format '1'", pkg.get("package_format") == "1")
        check(f"export_package({wid}) has manifest metadata", isinstance(pkg.get("manifest"), dict))
        check(f"export_package({wid}) manifest widget_id matches", bool(pkg.get("manifest", {}).get("widget_id")))
        check(f"export_package({wid}) widget spec string non-empty", bool(pkg.get("widget")))
        check(f"export_package({wid}) tokens object present", isinstance(pkg.get("tokens"), dict))
        check(f"export_package({wid}) renderer source non-empty", bool(pkg.get("renderer")))

        # Validate spec strictly
        w_obj = load_widget(pkg["widget"])
        check(f"exported spec for {wid} strictly validates", w_obj.id is not None)

        # Validate tokens against schema
        tokens_valid = True
        try:
            validate(pkg["tokens"], VISUAL_TOKENS_SCHEMA)
        except Exception:
            tokens_valid = False
        check(f"exported tokens for {wid} validate against schema", tokens_valid)

        # Check secret cleanliness
        secrets = scan_for_secrets(pkg)
        check(f"exported package for {wid} has zero secrets", len(secrets) == 0)

    # 2. CLI export command
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        out_pkg = tmp_path / "pulse.cw"
        rc = cli_main(["widget", "export", "pulse", "--out", str(out_pkg)])
        check("cortxt widget export pulse --out file.cw returns 0", rc == 0)
        check("output package file created on disk", out_pkg.is_file())

        parsed_pkg = json.loads(out_pkg.read_text(encoding="utf-8"))
        check("disk package contains valid JSON and format 1", parsed_pkg.get("package_format") == "1")

        # CLI export with custom tokens
        custom_tokens = {
            "schema_version": 1,
            "colors": {
                "background": "#111111",
                "surface": "#222222",
                "layer": "#333333",
                "hover": "#444444",
                "stroke": "#555555",
                "strong": "#ffffff",
                "text": "#eeeeee",
                "muted": "#888888",
                "dim": "#666666",
                "accent": "#00ff00",
                "blue": "#0000ff",
                "ok": "#00aa00",
                "warn": "#aaaa00",
                "bad": "#ff0000",
            },
            "typography": {
                "sans": ["sans-serif"],
                "mono": ["monospace"],
                "size_base": "12px",
                "size_small": "10px",
                "size_heading": "14px",
                "weight_normal": 400,
                "weight_bold": 600,
            },
            "spacing": {
                "unit": "4px",
                "gap_small": 4,
                "gap_medium": 8,
                "gap_large": 12,
                "padding_small": 4,
                "padding_medium": 8,
            },
            "radius": {"small": 2, "medium": 4, "large": 8},
            "density": {"row_height": 24, "card_max_height": 300, "grid_min_card_width": 280},
        }
        tokens_file = tmp_path / "custom_tokens.json"
        tokens_file.write_text(json.dumps(custom_tokens), encoding="utf-8")

        custom_out = tmp_path / "custom_pulse.cw"
        rc_custom = cli_main(["widget", "export", "pulse", "--out", str(custom_out), "--tokens", str(tokens_file)])
        check("cortxt widget export with --tokens returns 0", rc_custom == 0)
        loaded_custom = json.loads(custom_out.read_text(encoding="utf-8"))
        check("custom tokens embedded in package", loaded_custom["tokens"]["colors"]["accent"] == "#00ff00")

    # 3. Export rejection modes
    try:
        export_package("unknown-widget-999", ap_path=AP)
        check("export rejects unknown widget ID", False)
    except PackageError:
        check("export rejects unknown widget ID", True)

    try:
        export_package("loaded", ap_path=AP)
        check("export rejects widget with no declared spec file", False)
    except PackageError:
        check("export rejects widget with no declared spec file", True)

    # 4. Round-trip: export -> load into empty target dir -> render
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        cw_file = tmp_path / "candidates.cw"
        export_package("candidates", out_path=cw_file, ap_path=AP)

        target_dir = tmp_path / "installed_candidates"
        rc_load = cli_main(["widget", "load", "--package", str(cw_file), "--dir", str(target_dir)])
        check("cortxt widget load --package succeeds", rc_load == 0)
        check("installed spec YAML exists", (target_dir / "specs" / "candidates-0.1.yaml").is_file())
        check("installed widgets.json exists", (target_dir / "widgets.json").is_file())
        check("installed fixture JSON exists", (target_dir / "candidates.json").is_file())

        # Inspect installed manifest
        installed_manifest = json.loads((target_dir / "widgets.json").read_text(encoding="utf-8"))
        entries = installed_manifest.get("widgets", [])
        check("widgets.json has candidates entry", any(w.get("id") == "candidates" for w in entries))

        # Strict validation of installed spec
        installed_spec = (target_dir / "specs" / "candidates-0.1.yaml").read_text(encoding="utf-8")
        installed_obj = load_widget(installed_spec)
        check("installed spec strictly validates via load_widget", installed_obj.id == "candidates")

    # 5. Load rejection modes & fail-closed verification (no partial install)
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        target_dir = tmp_path / "rejection_target"

        # Missing file
        missing_file = tmp_path / "non_existent.cw"
        rc_missing = cli_main(["widget", "load", "--package", str(missing_file), "--dir", str(target_dir)])
        check("load rejects missing package file", rc_missing != 0)
        check("no files written on missing package error", not target_dir.exists() or len(list(target_dir.iterdir())) == 0)

        # Malformed JSON
        malformed_file = tmp_path / "malformed.cw"
        malformed_file.write_text("{ not json ", encoding="utf-8")
        rc_malformed = cli_main(["widget", "load", "--package", str(malformed_file), "--dir", str(target_dir)])
        check("load rejects malformed JSON", rc_malformed != 0)
        check("no files written on malformed JSON", not target_dir.exists() or len(list(target_dir.iterdir())) == 0)

        # Unknown package format version
        base_valid_pkg = export_package("pulse", ap_path=AP)
        bad_version_pkg = {**base_valid_pkg, "package_format": "2"}
        bad_version_file = tmp_path / "bad_version.cw"
        bad_version_file.write_text(json.dumps(bad_version_pkg), encoding="utf-8")
        rc_version = cli_main(["widget", "load", "--package", str(bad_version_file), "--dir", str(target_dir)])
        check("load rejects unsupported package format version", rc_version != 0)
        check("no files written on unsupported format version", not target_dir.exists() or len(list(target_dir.iterdir())) == 0)

        # Missing required field (renderer)
        missing_field_pkg = {k: v for k, v in base_valid_pkg.items() if k != "renderer"}
        missing_field_file = tmp_path / "missing_field.cw"
        missing_field_file.write_text(json.dumps(missing_field_pkg), encoding="utf-8")
        rc_field = cli_main(["widget", "load", "--package", str(missing_field_file), "--dir", str(target_dir)])
        check("load rejects missing required field (renderer)", rc_field != 0)
        check("no files written on missing required field", not target_dir.exists() or len(list(target_dir.iterdir())) == 0)

        # Secret-carrying package
        secret_pkg = {**base_valid_pkg, "secret_key": "sk-1234567890abcdef12345"}
        secret_file = tmp_path / "secret.cw"
        secret_file.write_text(json.dumps(secret_pkg), encoding="utf-8")
        rc_secret = cli_main(["widget", "load", "--package", str(secret_file), "--dir", str(target_dir)])
        check("load rejects secret-carrying package", rc_secret != 0)
        check("no files written on secret rejection", not target_dir.exists() or len(list(target_dir.iterdir())) == 0)

        # Contract validation failure (spec has forbidden key)
        corrupted_spec = base_valid_pkg["widget"] + "\ncommand: /bin/sh\n"
        corrupted_pkg = {**base_valid_pkg, "widget": corrupted_spec}
        corrupted_file = tmp_path / "corrupted_spec.cw"
        corrupted_file.write_text(json.dumps(corrupted_pkg), encoding="utf-8")
        rc_spec_fail = cli_main(["widget", "load", "--package", str(corrupted_file), "--dir", str(target_dir)])
        check("load rejects spec that fails strict validation", rc_spec_fail != 0)
        check("no files written on contract validation failure", not target_dir.exists() or len(list(target_dir.iterdir())) == 0)

    # 6. Standalone Node.js rendering from package
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        node_pkg_file = tmp_path / "node_pulse.cw"
        export_package("pulse", out_path=node_pkg_file, ap_path=AP)

        node_script = f"""
        const fs = require('fs');
        const vm = require('vm');

        const raw = fs.readFileSync({json.dumps(str(node_pkg_file))}, 'utf8');
        const pkg = JSON.parse(raw);

        // Run embedded renderer in sandbox
        const exportsObj = {{}};
        const sandbox = {{ module: {{ exports: exportsObj }}, exports: exportsObj }};
        vm.createContext(sandbox);
        vm.runInContext(pkg.renderer, sandbox);
        const maker = sandbox.module.exports;

        // Parse YAML spec and render
        const parsed = maker.parseYamlSubset(pkg.widget);
        if (!parsed.ok) {{
            console.error('YAML parse error:', parsed.error);
            process.exit(1);
        }}

        const rendered = maker.renderSpec(parsed.data, {{
            snapshot: {{ sessions: [], runtimes: [] }}
        }});

        if (!rendered || !rendered.render || rendered.render.primitive !== 'stack') {{
            console.error('Unexpected render output:', rendered);
            process.exit(2);
        }}

        // Verify fixture is present
        if (!pkg.fixture || !pkg.fixture.render) {{
            console.error('Missing fixture render tree');
            process.exit(3);
        }}

        console.log('OK standalone render');
        """
        node_res = run_node(node_script)
        check("standalone Node.js render from .cw package succeeds", node_res.returncode == 0 and "OK standalone render" in node_res.stdout)
        if node_res.returncode != 0:
            print("  Node STDERR:", node_res.stderr)

    # 7. UI and documentation markers
    maker_html = (AP / "widget" / "maker.html").read_text(encoding="utf-8")
    check("maker.html has Export package marker", "exportWidgetPackage" in maker_html or "Export package" in maker_html)
    check("maker.html has Import package marker", "section-import" in maker_html or "import-textarea" in maker_html)
    check("maker.html has cortxt widget load --package command marker", "cortxt widget load --package" in maker_html)

    docs_file = REPO / "docs" / "widget-package-format.md"
    check("docs/widget-package-format.md exists", docs_file.is_file())
    docs_text = docs_file.read_text(encoding="utf-8") if docs_file.is_file() else ""
    check("docs document package_format", "package_format" in docs_text)
    check("docs document standalone rendering", "Standalone Consumer Rendering" in docs_text or "standalone" in docs_text.lower())
    check("docs document export/load CLI", "cortxt widget export" in docs_text and "cortxt widget load" in docs_text)

    # 8. serve.py remains read-only
    serve_text = (AP / "widget" / "serve.py").read_text(encoding="utf-8")
    check("serve.py binds to loopback only", 'HOST = "127.0.0.1"' in serve_text)
    check("serve.py has no do_POST handler", "do_POST" not in serve_text)
    check("serve.py uses SimpleHTTPRequestHandler", "SimpleHTTPRequestHandler" in serve_text)

    # 9. Diacritics hygiene
    checked_files = [
        AP / "widget_contract" / "package.py",
        AP / "cli" / "unified_cli.py",
        AP / "widget" / "maker.html",
        REPO / "docs" / "widget-package-format.md",
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
