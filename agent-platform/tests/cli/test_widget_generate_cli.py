import json
from argparse import Namespace
from pathlib import Path

import pytest


def test_widget_generate_writes_spec_on_confirm(monkeypatch, tmp_path):
    from cli.unified_cli import _run_widget_generate
    import widget_contract.generation as gen_mod

    def fake_generate(prompt, *, existing_spec=None, scaffold_dir=None):
        from widget_contract.generation import GenerationOutcome
        return GenerationOutcome(status="ok", spec_text="contract_version: '0.1'\n",
                                  widget_id="pulse", widget_version="0.1",
                                  capabilities=("read:sessions",), document_hash="abc123")

    monkeypatch.setattr(gen_mod, "generate_widget_spec", fake_generate)

    args = Namespace(prompt="build a pulse widget", confirm=True, specs_dir=tmp_path)
    result = _run_widget_generate(args)
    assert result.status == "succeeded"
    written = tmp_path / "pulse-0.1.yaml"
    assert written.exists()
    assert written.read_text(encoding="utf-8") == "contract_version: '0.1'\n"


def test_widget_generate_without_confirm_does_not_write(monkeypatch, tmp_path):
    from cli.unified_cli import _run_widget_generate
    import widget_contract.generation as gen_mod

    def fake_generate(prompt, *, existing_spec=None, scaffold_dir=None):
        from widget_contract.generation import GenerationOutcome
        return GenerationOutcome(status="ok", spec_text="contract_version: '0.1'\n",
                                  widget_id="pulse", widget_version="0.1",
                                  capabilities=("read:sessions",), document_hash="abc123")

    monkeypatch.setattr(gen_mod, "generate_widget_spec", fake_generate)

    args = Namespace(prompt="build a pulse widget", confirm=False, specs_dir=tmp_path)
    result = _run_widget_generate(args)
    assert result.status == "succeeded"
    assert result.evidence[0]["confirmed"] is False
    assert not list(tmp_path.glob("*.yaml"))


def test_widget_generate_missing_operation_reports_scaffold(monkeypatch, tmp_path):
    from cli.unified_cli import _run_widget_generate
    import widget_contract.generation as gen_mod

    def fake_generate(prompt, *, existing_spec=None, scaffold_dir=None):
        from widget_contract.generation import GenerationOutcome
        return GenerationOutcome(status="missing_operation",
                                  missing_operations=("widgets.made-up.v1",),
                                  scaffold_paths=(str(tmp_path / "scaffold-widgets.made-up.v1.py"),))

    monkeypatch.setattr(gen_mod, "generate_widget_spec", fake_generate)

    args = Namespace(prompt="build a made-up widget", confirm=True, specs_dir=tmp_path)
    result = _run_widget_generate(args)
    assert result.status == "failed"
    assert result.error["category"] == "missing_operation"
    assert "widgets.made-up.v1" in result.error["message"]


def test_widget_remove_deletes_installed_spec(tmp_path):
    from cli.unified_cli import _run_widget_remove

    spec = tmp_path / "pulse-0.1.yaml"
    spec.write_text("contract_version: '0.1'\n", encoding="utf-8")
    args = Namespace(widget_id="pulse", widget_version="0.1", specs_dir=tmp_path)
    result = _run_widget_remove(args)
    assert result.status == "succeeded"
    assert not spec.exists()


def test_widget_remove_reports_not_found(tmp_path):
    from cli.unified_cli import _run_widget_remove

    args = Namespace(widget_id="nope", widget_version="0.1", specs_dir=tmp_path)
    result = _run_widget_remove(args)
    assert result.status == "failed"
    assert result.error["category"] == "input_error"
