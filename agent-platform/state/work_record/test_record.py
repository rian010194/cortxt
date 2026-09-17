"""Work-record domain model tests (ADR-050).

The pins that matter are the ADR's rules, not the field list: a record is
valid with NO issue and NO repository (rule 1), ``settled`` is a valid state
in its own right (rule 3), and the schema is closed in both directions --
unknown fields are rejected and required fields cannot be dropped.
"""

from __future__ import annotations

import json

import pytest

from state.work_record.record import (
    RECORD_KIND,
    SCHEMA_PATH,
    STATE_OPEN,
    STATE_SETTLED,
    WorkRecordError,
    build_work_record,
    load_schema,
    validate_work_record,
)

ARRAY_FIELDS = (
    "observations",
    "proposals",
    "open_questions",
    "goals",
    "limits",
    "acceptance_criteria",
    "possibly_affected_repositories",
)


def minimal() -> dict:
    return build_work_record(work_id="w-1", title="Decide the store shape")


def test_schema_file_is_the_single_closed_definition():
    schema = load_schema()
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["additionalProperties"] is False
    assert json.loads(SCHEMA_PATH.read_text(encoding="utf-8")) == schema


def test_record_without_issue_or_repository_is_valid():
    """ADR-050 rule 1: a work record exists before a repository and an issue."""
    record = minimal()
    assert record["possibly_affected_repositories"] == []
    assert "issue_ref" not in record
    assert "repository" not in record
    validate_work_record(record)


def test_settled_is_a_valid_state():
    """ADR-050 rule 3: a work record may itself be the finished result."""
    record = build_work_record(work_id="w-1", title="Analysis", state=STATE_SETTLED)
    assert record["state"] == STATE_SETTLED
    validate_work_record(record)


def test_default_state_is_open():
    assert minimal()["state"] == STATE_OPEN


def test_content_is_carried_verbatim():
    record = build_work_record(
        work_id="w-2",
        title="Dialogue to result",
        observations=["the store already exists"],
        proposals=["mirror the packaging ops API"],
        open_questions=["where does the renderer live?"],
        goals=["a readable artefact"],
        limits=["domain and operations only"],
        acceptance_criteria=["history shows the supersession"],
        possibly_affected_repositories=["rian010194/cortxt", "some/other-path"],
    )
    assert record["observations"] == ["the store already exists"]
    assert record["possibly_affected_repositories"] == [
        "rian010194/cortxt", "some/other-path"]


def test_possibly_affected_repositories_are_plain_strings_only():
    """It grants nothing: no sha, no permission, no effect -- so no objects."""
    record = minimal()
    record["possibly_affected_repositories"] = [{"repo": "a/b", "sha": "0" * 40}]
    with pytest.raises(WorkRecordError):
        validate_work_record(record)


def test_unknown_field_is_rejected():
    record = minimal()
    record["permitted_effects"] = ["write"]
    with pytest.raises(WorkRecordError) as caught:
        validate_work_record(record)
    assert caught.value.kind == "invalid_record"


@pytest.mark.parametrize("field", ("record_kind", "work_id", "title", "state") + ARRAY_FIELDS)
def test_missing_required_field_is_rejected(field):
    record = minimal()
    del record[field]
    with pytest.raises(WorkRecordError):
        validate_work_record(record)


@pytest.mark.parametrize("field", ARRAY_FIELDS)
def test_empty_array_is_valid_but_missing_array_is_not(field):
    record = minimal()
    record[field] = []
    validate_work_record(record)
    del record[field]
    with pytest.raises(WorkRecordError):
        validate_work_record(record)


def test_record_kind_cannot_be_anything_else():
    assert minimal()["record_kind"] == RECORD_KIND
    record = minimal()
    record["record_kind"] = "packaging-revision"
    with pytest.raises(WorkRecordError):
        validate_work_record(record)


def test_unknown_state_is_rejected():
    record = minimal()
    record["state"] = "in-progress"
    with pytest.raises(WorkRecordError):
        validate_work_record(record)


@pytest.mark.parametrize("field", ("work_id", "title"))
def test_empty_identity_strings_are_rejected(field):
    record = minimal()
    record[field] = ""
    with pytest.raises(WorkRecordError):
        validate_work_record(record)


def test_non_object_is_rejected():
    with pytest.raises(WorkRecordError):
        validate_work_record(["not", "an", "object"])


def test_builder_rejects_a_string_where_a_list_belongs():
    with pytest.raises(WorkRecordError):
        build_work_record(work_id="w-1", title="t", observations="one observation")
