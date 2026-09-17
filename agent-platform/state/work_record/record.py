"""Work-record domain model: the artefact a dialogue produces (ADR-050).

A work record carries what a dialogue actually produced -- observations,
proposals, open questions, goals, limits and acceptance criteria -- as a
durable, revisable, readable object. Three rules from ADR-050 shape every
decision in this module:

1. **A work record exists before a repository and before an issue.** Nothing
   here takes a repository or an issue reference; the store's ``issue_ref``
   stays optional at the layer above. A record that could not be built
   without a repository would violate the ADR.
2. **Revision is supersession, never mutation.** This module builds and
   validates a payload; it never edits a stored one. A changed record is a
   NEW record appended with ``supersedes`` naming the earlier one, which
   stays readable and byte-identical.
3. **A work record may be a finished result.** ``state`` is a CONTENT field
   -- the same kind of thing as the packaging decision slot's ``verdict``,
   which is deliberately inside the record rather than an outcome record next
   to it. ``STATE_SETTLED`` with no code change, no issue and no Run is a
   delivery, not an incomplete step toward one.

``possibly_affected_repositories`` is the field most likely to be misread
later, so it is stated twice -- here and in the schema. It is the MIDDLE of
the product's three levels -- available context, *possibly affected
repositories*, approved change targets -- and the middle one only. It holds
free-text names or paths as surfaced by discovery. **It carries no sha, no
permission, no effect and no ordering, and it must never be read as a change
target.** Discovery and read access never grant write access; an approved
change target is a separate, later, operator-approved artefact.

Deliberately ABSENT, and the absence IS the decision: no pinned sha, no
permitted effects, no isolation, no limits-on-effects, no write allowlist.
Those belong to the frozen packaging revision form and to mandate
preparation (ADR-050 D5). Do not add them and do not add placeholders.

Validation loads ``schemas/work_record/record.schema.json`` from the file.
The schema is the single copy on purpose: a second copy restated as Python
dicts drifts, which is exactly the defect
``test_exports_are_canonical_bytes_of_embedded_dicts`` exists to catch
elsewhere in this repository.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Mapping

import jsonschema

RECORD_KIND = "work_record"

STATE_OPEN = "open"
STATE_SETTLED = "settled"

SCHEMA_PATH = (Path(__file__).resolve().parents[3]
               / "schemas" / "work_record" / "record.schema.json")


class WorkRecordError(ValueError):
    """Fail-closed work-record rejection with a stable kind."""

    def __init__(self, message: str, *, kind: str = "invalid_input") -> None:
        super().__init__(message)
        self.kind = kind


@lru_cache(maxsize=1)
def load_schema() -> dict[str, Any]:
    """The closed record schema, read from the one file that defines it."""
    try:
        text = SCHEMA_PATH.read_text(encoding="utf-8")
    except OSError as error:
        raise WorkRecordError(f"work-record schema is unreadable: {SCHEMA_PATH}",
                              kind="schema_unavailable") from error
    try:
        schema = json.loads(text)
    except json.JSONDecodeError as error:
        raise WorkRecordError(f"work-record schema is not valid JSON: {SCHEMA_PATH}",
                              kind="schema_unavailable") from error
    return schema


def _strings(values: Iterable[str], *, field: str) -> list[str]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Iterable):
        raise WorkRecordError(f"{field} must be a sequence of strings")
    return list(values)


def build_work_record(*, work_id: str, title: str, state: str = STATE_OPEN,
                      observations: Iterable[str] = (),
                      proposals: Iterable[str] = (),
                      open_questions: Iterable[str] = (),
                      goals: Iterable[str] = (),
                      limits: Iterable[str] = (),
                      acceptance_criteria: Iterable[str] = (),
                      possibly_affected_repositories: Iterable[str] = (),
                      ) -> dict[str, Any]:
    """Build one validated work-record payload.

    Every list field defaults to empty and stays required in the payload: an
    empty list is a statement ("nothing observed"), a missing key is not. No
    parameter names a repository target, an issue, a sha or an effect -- rule
    1 is enforced by the signature, not only by the tests.
    """
    record: dict[str, Any] = {
        "record_kind": RECORD_KIND,
        "work_id": work_id,
        "title": title,
        "state": state,
        "observations": _strings(observations, field="observations"),
        "proposals": _strings(proposals, field="proposals"),
        "open_questions": _strings(open_questions, field="open_questions"),
        "goals": _strings(goals, field="goals"),
        "limits": _strings(limits, field="limits"),
        "acceptance_criteria": _strings(acceptance_criteria,
                                        field="acceptance_criteria"),
        "possibly_affected_repositories": _strings(
            possibly_affected_repositories, field="possibly_affected_repositories"),
    }
    validate_work_record(record)
    return record


def validate_work_record(record: Mapping[str, Any]) -> None:
    """Validate against the closed schema; raise ``WorkRecordError`` on any fault."""
    if not isinstance(record, Mapping):
        raise WorkRecordError("work record must be a JSON object")
    try:
        jsonschema.validate(dict(record), load_schema())
    except jsonschema.ValidationError as error:
        location = "/".join(str(part) for part in error.absolute_path) or "<record>"
        raise WorkRecordError(f"{location}: {error.message}",
                              kind="invalid_record") from error


__all__ = [
    "RECORD_KIND",
    "SCHEMA_PATH",
    "STATE_OPEN",
    "STATE_SETTLED",
    "WorkRecordError",
    "build_work_record",
    "load_schema",
    "validate_work_record",
]
