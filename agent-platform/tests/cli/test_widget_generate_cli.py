from argparse import Namespace


def _fake_generate_ok(widget_id="pulse", widget_version="0.1", spec_text="contract_version: '0.1'\n"):
    def fake_generate(prompt, *, existing_spec=None, scaffold_dir=None):
        from widget_contract.generation import GenerationOutcome
        return GenerationOutcome(status="ok", spec_text=spec_text,
                                  widget_id=widget_id, widget_version=widget_version,
                                  capabilities=("read:sessions",), document_hash="abc123")
    return fake_generate


def test_widget_generate_writes_spec_on_confirm(monkeypatch, tmp_path):
    from cli.unified_cli import _run_widget_generate
    import widget_contract.generation as gen_mod

    monkeypatch.setattr(gen_mod, "generate_widget_spec", _fake_generate_ok())

    args = Namespace(prompt="build a pulse widget", confirm=True, specs_dir=tmp_path)
    result = _run_widget_generate(args)
    assert result.status == "succeeded"
    written = tmp_path / "pulse-0.1.yaml"
    assert written.exists()
    assert written.read_text(encoding="utf-8") == "contract_version: '0.1'\n"


def test_widget_generate_without_confirm_does_not_write(monkeypatch, tmp_path):
    from cli.unified_cli import _run_widget_generate
    import widget_contract.generation as gen_mod

    monkeypatch.setattr(gen_mod, "generate_widget_spec", _fake_generate_ok())

    args = Namespace(prompt="build a pulse widget", confirm=False, specs_dir=tmp_path)
    result = _run_widget_generate(args)
    assert result.status == "succeeded"
    assert result.evidence[0]["confirmed"] is False
    assert not list(tmp_path.glob("*.yaml"))


def test_widget_generate_missing_operation_reports_scaffold(monkeypatch, tmp_path):
    from cli.unified_cli import _run_widget_generate
    import widget_contract.generation as gen_mod

    scaffold_dir = tmp_path.parent / "scaffolds"

    def fake_generate(prompt, *, existing_spec=None, scaffold_dir=None):
        from widget_contract.generation import GenerationOutcome
        return GenerationOutcome(status="missing_operation",
                                  missing_operations=("widgets.made-up.v1",),
                                  scaffold_paths=(str(scaffold_dir / "scaffold-widgets.made-up.v1.py"),))

    monkeypatch.setattr(gen_mod, "generate_widget_spec", fake_generate)

    args = Namespace(prompt="build a made-up widget", confirm=True, specs_dir=tmp_path)
    result = _run_widget_generate(args)
    assert result.status == "failed"
    assert result.error["category"] == "missing_operation"
    assert "widgets.made-up.v1" in result.error["message"]
    # Scaffold path reported is under the sibling scaffolds/ dir, not specs_dir.
    assert str(tmp_path) not in result.error["message"].split("Scaffold written to: ")[1]
    assert "scaffolds" in result.error["message"]


def test_widget_generate_uses_sibling_scaffolds_dir(monkeypatch, tmp_path):
    """generate must pass a scaffold_dir sibling to specs_dir, not specs_dir itself."""
    from cli.unified_cli import _run_widget_generate
    import widget_contract.generation as gen_mod

    seen = {}

    def fake_generate(prompt, *, existing_spec=None, scaffold_dir=None):
        seen["scaffold_dir"] = scaffold_dir
        from widget_contract.generation import GenerationOutcome
        return GenerationOutcome(status="ok", spec_text="contract_version: '0.1'\n",
                                  widget_id="pulse", widget_version="0.1",
                                  capabilities=(), document_hash="abc123")

    monkeypatch.setattr(gen_mod, "generate_widget_spec", fake_generate)
    specs_dir = tmp_path / "specs"
    args = Namespace(prompt="build a pulse widget", confirm=False, specs_dir=specs_dir)
    _run_widget_generate(args)
    assert seen["scaffold_dir"] == specs_dir.parent / "scaffolds"


def test_widget_generate_rejects_existing_spec(monkeypatch, tmp_path):
    from cli.unified_cli import _run_widget_generate
    import widget_contract.generation as gen_mod

    monkeypatch.setattr(gen_mod, "generate_widget_spec", _fake_generate_ok())
    existing = tmp_path / "pulse-0.1.yaml"
    existing.write_text("already here\n", encoding="utf-8")

    args = Namespace(prompt="build a pulse widget", confirm=True, specs_dir=tmp_path)
    result = _run_widget_generate(args)
    assert result.status == "failed"
    assert result.error["category"] == "input_error"
    assert existing.read_text(encoding="utf-8") == "already here\n"


def test_widget_generate_rejects_unsafe_version(monkeypatch, tmp_path):
    from cli.unified_cli import _run_widget_generate
    import widget_contract.generation as gen_mod

    monkeypatch.setattr(gen_mod, "generate_widget_spec", _fake_generate_ok(widget_version="../evil"))

    args = Namespace(prompt="build a pulse widget", confirm=True, specs_dir=tmp_path)
    result = _run_widget_generate(args)
    assert result.status == "failed"
    assert result.error["category"] == "generation_error"
    assert not list(tmp_path.glob("*.yaml"))


def test_widget_generate_invalid_outcome_maps_to_generation_error(monkeypatch, tmp_path):
    from cli.unified_cli import _run_widget_generate
    import widget_contract.generation as gen_mod

    def fake_generate(prompt, *, existing_spec=None, scaffold_dir=None):
        from widget_contract.generation import GenerationOutcome
        return GenerationOutcome(status="invalid", error_message="not a valid spec")

    monkeypatch.setattr(gen_mod, "generate_widget_spec", fake_generate)

    args = Namespace(prompt="build something broken", confirm=True, specs_dir=tmp_path)
    result = _run_widget_generate(args)
    assert result.status == "failed"
    assert result.error["category"] == "generation_error"
    assert result.error["message"] == "not a valid spec"


def test_widget_edit_writes_spec_on_confirm(monkeypatch, tmp_path):
    from cli.unified_cli import _run_widget_edit
    import widget_contract.generation as gen_mod

    existing = tmp_path / "pulse-0.1.yaml"
    existing.write_text("contract_version: '0.1'\nold: true\n", encoding="utf-8")

    def fake_generate(prompt, *, existing_spec=None, scaffold_dir=None):
        assert existing_spec == "contract_version: '0.1'\nold: true\n"
        from widget_contract.generation import GenerationOutcome
        return GenerationOutcome(status="ok", spec_text="contract_version: '0.1'\nold: false\n",
                                  widget_id="pulse", widget_version="0.1",
                                  capabilities=("read:sessions",), document_hash="def456")

    monkeypatch.setattr(gen_mod, "generate_widget_spec", fake_generate)

    args = Namespace(widget_id="pulse", widget_version="0.1", prompt="flip old to false",
                      confirm=True, specs_dir=tmp_path)
    result = _run_widget_edit(args)
    assert result.status == "succeeded"
    assert existing.read_text(encoding="utf-8") == "contract_version: '0.1'\nold: false\n"


def test_widget_edit_without_confirm_does_not_write(monkeypatch, tmp_path):
    from cli.unified_cli import _run_widget_edit
    import widget_contract.generation as gen_mod

    existing = tmp_path / "pulse-0.1.yaml"
    existing.write_text("contract_version: '0.1'\nold: true\n", encoding="utf-8")

    monkeypatch.setattr(gen_mod, "generate_widget_spec", _fake_generate_ok(
        spec_text="contract_version: '0.1'\nold: false\n"))

    args = Namespace(widget_id="pulse", widget_version="0.1", prompt="flip old to false",
                      confirm=False, specs_dir=tmp_path)
    result = _run_widget_edit(args)
    assert result.status == "succeeded"
    assert result.evidence[0]["confirmed"] is False
    assert existing.read_text(encoding="utf-8") == "contract_version: '0.1'\nold: true\n"


def test_widget_edit_reports_not_found(tmp_path):
    from cli.unified_cli import _run_widget_edit

    args = Namespace(widget_id="nope", widget_version="0.1", prompt="anything",
                      confirm=True, specs_dir=tmp_path)
    result = _run_widget_edit(args)
    assert result.status == "failed"
    assert result.error["category"] == "input_error"


def test_widget_edit_rejects_unsafe_version(monkeypatch, tmp_path):
    from cli.unified_cli import _run_widget_edit
    import widget_contract.generation as gen_mod

    existing = tmp_path / "pulse-0.1.yaml"
    existing.write_text("contract_version: '0.1'\n", encoding="utf-8")

    monkeypatch.setattr(gen_mod, "generate_widget_spec", _fake_generate_ok(widget_version="../evil"))

    args = Namespace(widget_id="pulse", widget_version="0.1", prompt="anything",
                      confirm=True, specs_dir=tmp_path)
    result = _run_widget_edit(args)
    assert result.status == "failed"
    assert result.error["category"] == "generation_error"
    assert existing.read_text(encoding="utf-8") == "contract_version: '0.1'\n"


def test_widget_remove_deletes_installed_spec_when_confirmed(tmp_path):
    from cli.unified_cli import _run_widget_remove

    spec = tmp_path / "pulse-0.1.yaml"
    spec.write_text("contract_version: '0.1'\n", encoding="utf-8")
    args = Namespace(widget_id="pulse", widget_version="0.1", specs_dir=tmp_path, confirm=True)
    result = _run_widget_remove(args)
    assert result.status == "succeeded"
    assert not spec.exists()


def test_widget_remove_without_confirm_does_not_delete(tmp_path):
    from cli.unified_cli import _run_widget_remove

    spec = tmp_path / "pulse-0.1.yaml"
    spec.write_text("contract_version: '0.1'\n", encoding="utf-8")
    args = Namespace(widget_id="pulse", widget_version="0.1", specs_dir=tmp_path, confirm=False)
    result = _run_widget_remove(args)
    assert result.status == "succeeded"
    assert spec.exists()
    assert result.evidence[0]["confirmed"] is False
    assert str(spec) in result.evidence[0]["would_remove"]


def test_widget_remove_reports_not_found(tmp_path):
    from cli.unified_cli import _run_widget_remove

    args = Namespace(widget_id="nope", widget_version="0.1", specs_dir=tmp_path, confirm=True)
    result = _run_widget_remove(args)
    assert result.status == "failed"
    assert result.error["category"] == "input_error"


def test_widget_reset_deletes_all_specs_when_confirmed(tmp_path):
    from cli.unified_cli import _run_widget_reset

    (tmp_path / "pulse-0.1.yaml").write_text("a\n", encoding="utf-8")
    (tmp_path / "docker-status-0.1.yaml").write_text("b\n", encoding="utf-8")
    args = Namespace(specs_dir=tmp_path, confirm=True)
    result = _run_widget_reset(args)
    assert result.status == "succeeded"
    assert not list(tmp_path.glob("*.yaml"))
    assert result.evidence[0]["removed_count"] == 2


def test_widget_reset_without_confirm_does_not_delete(tmp_path):
    from cli.unified_cli import _run_widget_reset

    (tmp_path / "pulse-0.1.yaml").write_text("a\n", encoding="utf-8")
    (tmp_path / "docker-status-0.1.yaml").write_text("b\n", encoding="utf-8")
    args = Namespace(specs_dir=tmp_path, confirm=False)
    result = _run_widget_reset(args)
    assert result.status == "succeeded"
    assert len(list(tmp_path.glob("*.yaml"))) == 2
    assert result.evidence[0]["confirmed"] is False
    assert len(result.evidence[0]["would_remove"]) == 2


def test_widget_reset_without_confirm_on_missing_dir_is_a_noop(tmp_path):
    from cli.unified_cli import _run_widget_reset

    args = Namespace(specs_dir=tmp_path / "does-not-exist", confirm=False)
    result = _run_widget_reset(args)
    assert result.status == "succeeded"
    assert result.evidence[0]["would_remove"] == []
