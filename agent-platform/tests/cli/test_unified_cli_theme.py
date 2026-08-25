"""Tests for `cortxt theme list/inspect/preview/use` (issue #375).

Not every individual test passes an explicit --path. Regardless, the
autouse `_isolate_theme_preference_file` fixture below monkeypatches
`widget_contract.theme_resolver.DEFAULT_THEME_PREFERENCE_PATH` (the path
used whenever a test/CLI invocation omits --path) so every test's default
resolution/persistence -- even by omission -- lives under tmp_path rather
than the real per-user ~/.cortxt/theme.json.
"""
from __future__ import annotations

import json

import pytest

from cli.unified_cli import main


@pytest.fixture(autouse=True)
def _isolate_theme_preference_file(tmp_path, monkeypatch):
    """Redirect the no-`--path` default preference file under tmp_path.

    Guarantees no test in this module -- even one that omits --path -- can
    read or write the operator's real ~/.cortxt/theme.json. Also redirects
    theme_resolver's widget/tokens.json sync destination (issue #376 review
    finding 1: `theme use` now calls sync_widget_tokens()) under tmp_path,
    so no test in this module can write to the real repo-tracked
    agent-platform/widget/tokens.json either.
    """
    import widget_contract.theme_resolver as theme_resolver

    monkeypatch.setattr(theme_resolver, "DEFAULT_THEME_PREFERENCE_PATH", tmp_path / "theme.json")
    monkeypatch.setattr(theme_resolver, "DEFAULT_TOKENS_PATH", tmp_path / "widget-tokens.json")


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


def test_theme_preview_auto_enables_truecolor_when_colorterm_advertises_support(monkeypatch, capsys):
    """Regression for the reviewer finding that preview output was byte-identical
    across presets in the non-truecolor path: `ansi_map()` only fills in colors
    NOT already present in DEFAULT_ANSI_MAP, and every preset defines exactly the
    same 14 standard keys, so the 256-color fallback never reflected the actual
    preset. `preview` now auto-enables 24-bit rendering when COLORTERM advertises
    support, so its default output (no --truecolor flag) differs across presets."""
    monkeypatch.setenv("COLORTERM", "truecolor")

    exit_code_a = main(["theme", "preview", "quiet-slate", "--force-ansi"])
    out_a = capsys.readouterr().out
    exit_code_b = main(["theme", "preview", "soft-dusk", "--force-ansi"])
    out_b = capsys.readouterr().out

    assert exit_code_a == 0
    assert exit_code_b == 0
    # Both should be truecolor-rendered (";2;" sequences), and the two
    # presets' actual hex values must diverge, proving preview reflects the
    # requested preset rather than a shared generic ANSI approximation.
    assert ";2;" in out_a
    assert ";2;" in out_b

    def _strip_header(text: str) -> str:
        return "\n".join(text.splitlines()[1:])

    assert _strip_header(out_a) != _strip_header(out_b)


def test_theme_preview_does_not_auto_enable_truecolor_without_colorterm(monkeypatch, capsys):
    monkeypatch.delenv("COLORTERM", raising=False)

    exit_code_a = main(["theme", "preview", "quiet-slate", "--force-ansi"])
    out_a = capsys.readouterr().out
    exit_code_b = main(["theme", "preview", "soft-dusk", "--force-ansi"])
    out_b = capsys.readouterr().out

    assert exit_code_a == 0
    assert exit_code_b == 0
    assert ";2;" not in out_a
    assert ";2;" not in out_b


def test_theme_preview_explicit_truecolor_flag_overrides_colorterm_absence(monkeypatch, capsys):
    monkeypatch.delenv("COLORTERM", raising=False)

    exit_code = main(["theme", "preview", "quiet-slate", "--force-ansi", "--truecolor"])
    out = capsys.readouterr().out

    assert exit_code == 0
    assert ";2;" in out


def test_theme_preview_does_not_persist_anything(tmp_path, capsys):
    """The issue #375 acceptance criteria require `preview` to never change
    the persisted selection -- prove it doesn't create the file, and doesn't
    change an existing persisted value."""
    pref_path = tmp_path / "theme.json"
    pref_path.write_text(json.dumps({"preset": "graphite-ink"}), encoding="utf-8")
    before = pref_path.read_text(encoding="utf-8")

    exit_code = main(["theme", "preview", "soft-dusk", "--path", str(pref_path), "--force-ansi"])
    capsys.readouterr()

    assert exit_code == 0
    assert pref_path.read_text(encoding="utf-8") == before


def test_theme_preview_does_not_create_preference_file_when_absent(tmp_path, capsys):
    pref_path = tmp_path / "theme.json"

    exit_code = main(["theme", "preview", "soft-dusk", "--path", str(pref_path), "--force-ansi"])
    capsys.readouterr()

    assert exit_code == 0
    assert not pref_path.exists()


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


def test_theme_use_syncs_widget_host_tokens(tmp_path, capsys):
    """Issue #376 review finding 1: `theme use` must also call
    sync_widget_tokens() so widget/tokens.json (what the widget host, Widget
    Maker, and site's generated copy actually serve) reflects the newly
    selected preset -- not just the CLI/TUI's own resolver-backed rendering.
    Before this fix, sync_widget_tokens() had zero callers anywhere."""
    import widget_contract.theme_resolver as theme_resolver
    from widget_contract.tokens import load_preset_tokens

    pref_path = tmp_path / "theme.json"
    widget_tokens_path = theme_resolver.DEFAULT_TOKENS_PATH  # patched to tmp_path by the autouse fixture

    assert not widget_tokens_path.exists()

    exit_code = main(["theme", "use", "graphite-ink", "--path", str(pref_path)])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "synced" in captured.out.lower()
    assert widget_tokens_path.is_file()
    written = json.loads(widget_tokens_path.read_text(encoding="utf-8"))
    assert written == load_preset_tokens("graphite-ink")


def test_theme_use_resolve_theme_output_matches_widget_tokens_file(tmp_path, capsys):
    """After `theme use`, widget_contract.theme_resolver.resolve_theme()'s
    output and what's actually on disk in widget/tokens.json must agree --
    the whole point of finding 1's fix is that CLI/TUI (which resolves
    through resolve_theme()) and the widget host (which reads
    widget/tokens.json) render the same palette."""
    import widget_contract.theme_resolver as theme_resolver
    from widget_contract.tokens import load_preset_tokens

    pref_path = tmp_path / "theme.json"

    main(["theme", "use", "soft-dusk", "--path", str(pref_path)])
    capsys.readouterr()

    resolved_preset = theme_resolver.resolve_theme(path=pref_path)
    assert resolved_preset == "soft-dusk"

    on_disk = json.loads(theme_resolver.DEFAULT_TOKENS_PATH.read_text(encoding="utf-8"))
    assert on_disk == load_preset_tokens(resolved_preset)


def test_theme_use_does_not_clobber_hand_edited_widget_tokens(tmp_path, capsys):
    """The clobber guard (theme_resolver.sync_widget_tokens's marker
    mechanism) must survive being driven through the actual CLI command, not
    just the resolver function in isolation: a Widget Maker hand edit made
    since the last sync must not be silently destroyed by `theme use`."""
    import widget_contract.theme_resolver as theme_resolver

    pref_path = tmp_path / "theme.json"

    # First `theme use` establishes a baseline sync + marker.
    main(["theme", "use", "graphite-ink", "--path", str(pref_path)])
    capsys.readouterr()

    # Simulate a hand edit in the Widget Maker's Tokens tab after that sync.
    widget_tokens_path = theme_resolver.DEFAULT_TOKENS_PATH
    hand_edited = json.loads(widget_tokens_path.read_text(encoding="utf-8"))
    hand_edited["colors"]["accent"] = "#123456"
    widget_tokens_path.write_text(json.dumps(hand_edited, indent=2) + "\n", encoding="utf-8")

    exit_code = main(["theme", "use", "soft-dusk", "--path", str(pref_path)])
    captured = capsys.readouterr()

    # The theme preference itself still switches -- only the widget host
    # tokens.json sync is skipped.
    assert exit_code == 0
    assert theme_resolver.resolve_theme(path=pref_path) == "soft-dusk"
    assert "not synced" in captured.out.lower()

    still_on_disk = json.loads(widget_tokens_path.read_text(encoding="utf-8"))
    assert still_on_disk["colors"]["accent"] == "#123456"


def test_theme_preset_display_dict_is_in_sync_with_the_presets_collection():
    """`_THEME_PRESET_DISPLAY`'s module comment claims it's kept in sync with
    widget/presets/visual-tokens.v2.json, but nothing enforced that. Make the
    claim actually true: a preset added without a matching display entry (or
    vice versa) now fails this test loudly instead of degrading silently to
    name=id / 'No description available.' in `theme list`/`theme inspect`."""
    from cli.unified_cli import _THEME_PRESET_DISPLAY
    from widget_contract.tokens import load_presets

    preset_ids = set(load_presets()["presets"])
    assert preset_ids == set(_THEME_PRESET_DISPLAY)
