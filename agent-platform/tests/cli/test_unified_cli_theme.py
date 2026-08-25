"""Tests for `cortxt theme list/inspect/preview/use` (issue #375).

Every test passes an explicit --path so the persisted-preference file lives
under tmp_path rather than the real per-user ~/.cortxt/theme.json.
"""
from __future__ import annotations

import json

from cli.unified_cli import main


def test_theme_list_shows_all_three_presets(capsys):
    exit_code = main(["theme", "list"])
    captured = capsys.readouterr()

    assert exit_code == 0
    for preset_id in ("quiet-slate", "graphite-ink", "soft-dusk"):
        assert preset_id in captured.out


def test_theme_list_marks_the_resolved_active_preset(tmp_path, capsys):
    pref_path = tmp_path / "theme.json"
    pref_path.write_text(json.dumps({"preset": "soft-dusk"}), encoding="utf-8")

    exit_code = main(["theme", "list", "--path", str(pref_path)])
    captured = capsys.readouterr()

    assert exit_code == 0
    # Row format is "{marker}{sep}{preset_id:<14}...": marker is always the
    # first character, so check it directly rather than via a whitespace
    # split (which would swallow a blank marker for unmarked rows). Only
    # look at the preset rows themselves -- stdout also carries the trailing
    # ResultEnvelope JSON dump, which is not shaped like a preset row.
    preset_ids = ("quiet-slate", "graphite-ink", "soft-dusk")
    lines = {
        preset_id: line[0]
        for line in captured.out.splitlines()
        for preset_id in preset_ids
        if line[2:2 + len(preset_id)] == preset_id
    }
    assert lines["soft-dusk"] == "*"
    assert lines["quiet-slate"] == " "
    assert lines["graphite-ink"] == " "


def test_theme_inspect_prints_colors_and_typography_for_named_preset(capsys):
    exit_code = main(["theme", "inspect", "graphite-ink"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "graphite-ink" in captured.out
    assert "Colors:" in captured.out
    # graphite-ink's accent color from widget/presets/visual-tokens.v2.json
    assert "#8aa2ba" in captured.out
    assert "Typography:" in captured.out
    assert "size_base" in captured.out


def test_theme_inspect_unknown_preset_fails(capsys):
    exit_code = main(["theme", "inspect", "not-a-real-preset"])
    assert exit_code == 1


def test_theme_inspect_without_preset_arg_uses_resolved_theme(tmp_path, capsys):
    pref_path = tmp_path / "theme.json"
    pref_path.write_text(json.dumps({"preset": "soft-dusk"}), encoding="utf-8")

    exit_code = main(["theme", "inspect", "--path", str(pref_path)])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "Preset: soft-dusk" in captured.out


def test_theme_preview_renders_status_roles_and_ui_tones(capsys):
    exit_code = main(["theme", "preview", "quiet-slate", "--force-ansi"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "ok" in captured.out
    assert "warn" in captured.out
    assert "bad" in captured.out
    assert "accent" in captured.out
    assert "muted" in captured.out


def test_theme_preview_force_ansi_emits_escape_codes(capsys):
    exit_code = main(["theme", "preview", "quiet-slate", "--force-ansi"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "\x1b[" in captured.out


def test_theme_preview_no_ansi_flag_suppresses_escape_codes(capsys):
    exit_code = main(["theme", "preview", "quiet-slate", "--force-ansi", "--no-ansi"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "\x1b[" not in captured.out


def test_theme_preview_without_tty_and_without_force_flag_has_no_ansi_leak(capsys):
    """Default auto-detection: pytest's captured stdout is not a TTY, so ANSI
    fallback rendering must stay plain -- no truecolor (or any) escape codes
    leaking through, matching #375's ANSI-only-terminal acceptance criterion."""
    exit_code = main(["theme", "preview", "quiet-slate"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "\x1b[" not in captured.out


def test_theme_preview_truecolor_uses_24bit_escape_codes(capsys):
    exit_code = main(["theme", "preview", "quiet-slate", "--force-ansi", "--truecolor"])
    captured = capsys.readouterr()

    assert exit_code == 0
    # 24-bit truecolor sequences carry ";2;" (see tokens._hex_to_truecolor).
    assert ";2;" in captured.out


def test_theme_preview_unknown_preset_fails(capsys):
    exit_code = main(["theme", "preview", "not-a-real-preset"])
    assert exit_code == 1


def test_theme_use_persists_preference(tmp_path, capsys):
    pref_path = tmp_path / "theme.json"

    exit_code = main(["theme", "use", "graphite-ink", "--path", str(pref_path)])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "graphite-ink" in captured.out
    assert json.loads(pref_path.read_text(encoding="utf-8")) == {"preset": "graphite-ink"}


def test_theme_use_unknown_preset_fails_without_writing_file(tmp_path, capsys):
    pref_path = tmp_path / "theme.json"

    exit_code = main(["theme", "use", "not-a-real-preset", "--path", str(pref_path)])

    assert exit_code == 1
    assert not pref_path.exists()


def test_theme_use_then_inspect_reflects_change_end_to_end(tmp_path, capsys):
    """Proves the resolver wiring works end-to-end (not just at the CLI
    layer): `theme use` persists via the issue #374 resolver's
    save_persisted_theme, and a later `theme inspect` (no explicit preset)
    resolves through the same resolver and shows the new preset's tokens."""
    pref_path = tmp_path / "theme.json"

    exit_code_use = main(["theme", "use", "soft-dusk", "--path", str(pref_path)])
    assert exit_code_use == 0
    capsys.readouterr()

    exit_code_inspect = main(["theme", "inspect", "--path", str(pref_path)])
    captured = capsys.readouterr()

    assert exit_code_inspect == 0
    assert "Preset: soft-dusk" in captured.out

    # And the shared resolver itself -- not just the CLI's own bookkeeping --
    # now resolves to soft-dusk, proving this isn't CLI-layer-only state.
    from widget_contract.theme_resolver import resolve_theme

    assert resolve_theme(path=pref_path) == "soft-dusk"


def test_theme_use_overwrites_prior_persisted_preference(tmp_path, capsys):
    pref_path = tmp_path / "theme.json"

    main(["theme", "use", "graphite-ink", "--path", str(pref_path)])
    capsys.readouterr()
    exit_code = main(["theme", "use", "soft-dusk", "--path", str(pref_path)])
    capsys.readouterr()

    assert exit_code == 0
    assert json.loads(pref_path.read_text(encoding="utf-8")) == {"preset": "soft-dusk"}
