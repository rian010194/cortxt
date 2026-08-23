from pathlib import Path

from cli import orchestrator


def test_skill_discovery_exposes_metadata_but_not_instruction_content(tmp_path):
    skill = tmp_path / "skills" / "reviewer"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("SECRET INSTRUCTION BODY", encoding="utf-8")

    result = orchestrator.discover_skills([("test-runtime", tmp_path / "skills")])

    assert result == [{
        "skill_id": "reviewer", "source": "test-runtime", "installed": True,
        "available": True, "loaded": False, "loaded_by": [], "running": False,
    }]
    assert "SECRET" not in str(result)


def test_profile_parser_exposes_model_and_runtime_state_only():
    output = "  default         qwen/free        stopped      —\n \x1b[32mâ—†builder\x1b[0m         local/model      running      builder"

    result = orchestrator.parse_hermes_profiles(output)

    assert result[0]["profile_id"] == "default"
    assert result[1] == {
        "profile_id": "builder", "runtime_id": "hermes", "model": "local/model",
        "loaded": True, "running": True, "status": "running",
    }


def test_sanitizer_redacts_secret_assignments_before_external_prompt():
    prompt, hits = orchestrator.build_chat_prompt(
        "check token=abc123456789 and continue",
        {"orchestrator": {}, "workstreams": [], "runtimes": [], "skills": []},
    )

    assert "abc123456789" not in prompt
    assert "[REDACTED]" in prompt
    assert hits == 1
    assert "Do not volunteer a status briefing" in prompt


def test_local_greeting_does_not_need_operational_state():
    assert orchestrator.local_conversation_reply("Hello") == (
        "Hello! I’m the Cortxt orchestrator. What would you like to work on?"
    )
    assert orchestrator.local_conversation_reply("What is stale?") is None


def test_transcript_record_contains_hash_but_never_content():
    record = orchestrator.transcript_record(
        transcript_id="t-1", turn_index=1, role="user", content="private words",
        engine="hermes", status="submitted",
    )

    assert "content" not in record
    assert len(record["content_sha256"]) == 64


def test_transcript_record_carries_optional_engine_session_id():
    record = orchestrator.transcript_record(
        transcript_id="t-1", turn_index=1, role="assistant", content="answer",
        engine="codex", status="succeeded", engine_session_id="thread-abc",
    )

    assert record["engine_session_id"] == "thread-abc"


def test_transcript_record_engine_session_id_defaults_to_none():
    record = orchestrator.transcript_record(
        transcript_id="t-1", turn_index=1, role="user", content="hi",
        engine="hermes", status="submitted",
    )

    assert record["engine_session_id"] is None


def test_widget_is_manifest_driven_shell_without_legacy_tabs():
    widget = Path(__file__).parents[2] / "widget" / "index.html"
    html = widget.read_text(encoding="utf-8")

    assert 'class="window' in html
    # Legacy admin-surface tabs and swimlane surface are removed from the widget.
    assert 'data-tab="pipeline"' not in html
    assert 'data-tab="logg"' not in html
    assert 'data-tab="flotta"' not in html
    assert 'id="workstream-select"' not in html
    assert 'id="lanes"' not in html
    # The shell is manifest-driven and generic.
    assert "loadManifest" in html
    assert "renderGenericNode" in html
    assert "widgets.json" in html
