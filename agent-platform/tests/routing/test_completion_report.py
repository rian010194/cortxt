"""W6: the completion-report reader assigns exactly one of six states, and
four of them refuse a Run terminally and can never be raised to success.

Design record: `lab/cortxt-execution-confirmation-design-2026-09-08-corrected.md`
section 1 (the completion-report contract). The no-upgrade invariant is
section 1.4: a required report that is missing, unreadable, invalid or
incomplete can never be raised to success by attestation, exit code, stdout,
transport classification, the Evidence Gate, or a downstream default.

These tests are behavioural: they exercise the reader and the adapter, not mere
string searches in the source.
"""
import json
import time
from pathlib import Path

import pytest

from routing import completion_report as cr


def _write(tmp_path, payload, name="completion.json"):
    p = tmp_path / name
    if isinstance(payload, str):
        p.write_text(payload, encoding="utf-8")
    else:
        p.write_text(json.dumps(payload), encoding="utf-8")
    return p


def _invoked_after():
    return time.time()


# --- P1: monotonicity is structural at the reader -------------------------

def test_missing_is_requested_but_missing_and_refuses(tmp_path):
    # No file exists at the requested path: the route asked and got no answer.
    p = tmp_path / "completion.json"
    read = cr.read_completion_report(p, invoked_after=_invoked_after())
    assert read.state == cr.REQUESTED_BUT_MISSING
    assert read.refusing


# --- P2: the four refusing states -----------------------------------------

def test_unreadable_is_distinct_from_missing(tmp_path):
    """A truncated/undecodable file is `unreadable`, never `missing` -- the two
    are separate constants so a partial write is not silently treated as absent
    evidence."""
    p = _write(tmp_path, '{"completed": true, ')  # truncated JSON
    read = cr.read_completion_report(p, invoked_after=_invoked_after())
    assert read.state == cr.UNREADABLE
    assert read.refusing
    assert read.state != cr.REQUESTED_BUT_MISSING


def test_invalid_completed_string_false(tmp_path):
    """`completed: "false"` as a string is INVALID, not success -- the truthiness
    defect that made the string `"false"` read as success in the unmerged
    predecessor is closed by construction."""
    p = _write(tmp_path, {"completed": "false", "report_version": 1})
    read = cr.read_completion_report(p, invoked_after=_invoked_after())
    assert read.state == cr.INVALID
    assert "completed" in read.detail


def test_invalid_non_boolean_completed(tmp_path):
    p = _write(tmp_path, {"completed": 1, "report_version": 1})
    assert cr.read_completion_report(p, invoked_after=_invoked_after()).state == cr.INVALID


def test_invalid_missing_completed_key(tmp_path):
    p = _write(tmp_path, {"failed": False, "report_version": 1})
    assert cr.read_completion_report(p, invoked_after=_invoked_after()).state == cr.INVALID


def test_invalid_non_boolean_failed(tmp_path):
    p = _write(tmp_path, {"completed": True, "failed": "yes", "report_version": 1})
    assert cr.read_completion_report(p, invoked_after=_invoked_after()).state == cr.INVALID


def test_invalid_unknown_version(tmp_path):
    p = _write(tmp_path, {"completed": True, "report_version": 999})
    assert cr.read_completion_report(p, invoked_after=_invoked_after()).state == cr.INVALID


def test_invalid_not_a_json_object(tmp_path):
    p = _write(tmp_path, "[1, 2, 3]")
    assert cr.read_completion_report(p, invoked_after=_invoked_after()).state == cr.INVALID


def test_incomplete_when_failed_true(tmp_path):
    p = _write(tmp_path, {"completed": True, "failed": True, "report_version": 1})
    read = cr.read_completion_report(p, invoked_after=_invoked_after())
    assert read.state == cr.INCOMPLETE
    assert read.refusing


def test_incomplete_when_completed_false(tmp_path):
    p = _write(tmp_path, {"completed": False, "failed": False, "report_version": 1})
    assert cr.read_completion_report(p, invoked_after=_invoked_after()).state == cr.INCOMPLETE


# --- P3: the two non-refusing outcomes ------------------------------------

def test_completed(tmp_path):
    p = _write(tmp_path, {"completed": True, "failed": False, "report_version": 1})
    read = cr.read_completion_report(p, invoked_after=_invoked_after())
    assert read.state == cr.COMPLETED
    assert not read.refusing
    assert read.payload is not None  # W9 reads usage/cost from the payload


def test_not_requested_is_not_a_refusal():
    outcome = cr.not_requested("dsh")
    assert outcome.state == cr.NOT_REQUESTED
    assert not outcome.refusing


# --- Correlation ----------------------------------------------------------

def test_stale_report_is_invalid(tmp_path):
    """A file that predates the invocation window does not correlate and is
    `invalid`: a stale `usage.json` from a previous call is a worker choosing
    whether to be checked."""
    p = _write(tmp_path, {"completed": True, "report_version": 1})
    # Bump the mtime so it looks older than the invocation start.
    old = time.time() - 600
    import os
    os.utime(p, (old, old))
    read = cr.read_completion_report(p, invoked_after=time.time())
    assert read.state == cr.INVALID
    assert "correlate" in read.detail


# --- When a report is required --------------------------------------------

def test_report_required_only_for_structured_terminated_run():
    assert cr.report_required("hermes-free", cr.TERMINATED) is True
    assert cr.report_required("hermes", cr.TERMINATED) is True
    assert cr.report_required("dsh", cr.TERMINATED) is False          # channel none
    assert cr.report_required("hermes-free", cr.NEVER_LAUNCHED) is False
    assert cr.report_required("hermes-free", cr.INVOCATION_RAISED) is False
    assert cr.report_required("hermes-free", cr.TIMED_OUT) is False    # never reads


def test_report_channel_fails_closed_for_unknown_runtime():
    # An unrecognised runtime is NOT exempt: a new runtime must state its
    # channel to be exempt from the contract.
    assert cr.report_channel("some-future-runtime") == cr.CHANNEL_STRUCTURED
