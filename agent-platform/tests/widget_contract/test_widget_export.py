"""Pytest unit and integration tests for widget export/import (.cw packages)."""

from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path

import pytest

from cli.unified_cli import _run_widget_export, _run_widget_load
from widget_contract.loader import ContractError, load_widget
from widget_contract.package import (
    PACKAGE_FORMAT_VERSION,
    PackageError,
    assert_no_secrets,
    export_package,
    load_package,
    scan_for_secrets,
    validate_package,
)
from widget_contract.registry import VISUAL_TOKENS_SCHEMA
from widget_contract.validation import validate


def test_export_package_success_candidates():
    pkg = export_package("candidates")
    assert pkg["package_format"] == "1"
    assert pkg["manifest"]["widget_id"] == "candidates"
    assert pkg["manifest"]["package_format_version"] == "1"
    assert "tokens" in pkg and "renderer" in pkg and "widget" in pkg
    assert "fixture" in pkg

    # Validate widget model
    widget = load_widget(pkg["widget"])
    assert widget.id == "candidates"

    # Validate tokens
    validate(pkg["tokens"], VISUAL_TOKENS_SCHEMA)

    # Validate zero secrets
    assert scan_for_secrets(pkg) == []


def test_export_package_all_manifest_widgets():
    for wid in ("candidates", "pulse", "map", "docker", "webhooks"):
        pkg = export_package(wid)
        assert pkg["package_format"] == "1"
        assert pkg["manifest"]["package_format_version"] == "1"
        assert bool(pkg["renderer"])
        assert bool(pkg["widget"])
        assert scan_for_secrets(pkg) == []


def test_export_package_rejection_unknown_id():
    with pytest.raises(PackageError, match="not found"):
        export_package("non-existent-widget-id")


def test_export_package_rejection_no_spec():
    with pytest.raises(PackageError, match="no declared spec"):
        export_package("loaded")


def test_export_package_writes_to_out_path(tmp_path):
    out_file = tmp_path / "pulse.cw"
    pkg = export_package("pulse", out_path=out_file)
    assert out_file.is_file()
    disk_data = json.loads(out_file.read_text(encoding="utf-8"))
    assert disk_data["package_format"] == "1"
    assert disk_data["manifest"]["widget_id"] == "session-pulse"


def test_validate_package_fails_on_unsupported_version():
    pkg = export_package("pulse")
    pkg["package_format"] = "2"
    with pytest.raises(PackageError, match="Unsupported package format version"):
        validate_package(pkg)


def test_validate_package_fails_on_missing_required_field():
    pkg = export_package("pulse")
    del pkg["renderer"]
    with pytest.raises(PackageError, match="missing required field"):
        validate_package(pkg)


def test_validate_package_fails_on_secret_marker():
    pkg = export_package("pulse")
    pkg["extra_secret"] = "sk-1234567890abcdef12345"
    with pytest.raises(PackageError, match="Secret-shaped content detected"):
        validate_package(pkg)


def test_load_package_installs_into_directory(tmp_path):
    pkg = export_package("candidates")
    installed = load_package(pkg, target_dir=tmp_path)

    assert installed["widget_id"] == "candidates"
    assert (tmp_path / "specs" / "candidates-0.1.yaml").is_file()
    assert (tmp_path / "widgets.json").is_file()
    assert (tmp_path / "candidates.json").is_file()

    # Manifest content check
    manifest = json.loads((tmp_path / "widgets.json").read_text(encoding="utf-8"))
    assert any(w["id"] == "candidates" for w in manifest["widgets"])


def test_load_package_fails_closed_without_writing_files(tmp_path):
    target = tmp_path / "empty_target"
    bad_pkg = {"package_format": "1", "widget": "invalid yaml ::::", "tokens": {}, "renderer": "x"}

    with pytest.raises(PackageError):
        load_package(bad_pkg, target_dir=target)

    # Fail-closed invariant: zero files written
    assert not target.exists() or len(list(target.iterdir())) == 0


def test_cli_widget_export_and_load_flow(tmp_path):
    out_file = tmp_path / "map.cw"
    target_install = tmp_path / "installed_map"

    # Export
    res_exp = _run_widget_export(Namespace(widget_command="export", widget_id="map", out=out_file, tokens=None))
    assert res_exp.status == "succeeded"
    assert out_file.is_file()

    # Load
    res_load = _run_widget_load(Namespace(widget_command="load", package=out_file, dir=target_install, spec=None))
    assert res_load.status == "succeeded"
    assert (target_install / "specs" / "execution-map-0.1.yaml").is_file()
    assert (target_install / "widgets.json").is_file()


def test_cli_widget_load_rejection_reports_stable_error(tmp_path):
    bad_file = tmp_path / "corrupt.cw"
    bad_file.write_text("invalid json content", encoding="utf-8")

    res = _run_widget_load(Namespace(widget_command="load", package=bad_file, dir=tmp_path / "out", spec=None))
    assert res.status == "failed"
    assert res.error["category"] == "package_load"
