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


# --- W9: reported usage and cost from a completed report ------------------

def test_reported_usage_cost_extracts_telemetry_from_completed_payload():
    """A `completed` report that carries usage/cost yields the `reported`
    class: the runtime's own statement, exactly as strong as its honesty."""
    payload = {
        "completed": True,
        "report_version": 1,
        "cost_status": "estimated",
        "estimated_cost_usd": 0.5,
        "api_calls": 3,
        "input_tokens": 100,
        "output_tokens": 50,
        "total_tokens": 150,
    }
    reported = cr.reported_usage_cost(payload)
    assert reported is not None
    assert reported.cost == 0.5
    assert reported.cost_status == cr.COST_STATUS_ESTIMATED
    assert reported.api_calls == 3
    assert reported.usage == {"input_tokens": 100, "output_tokens": 50,
                              "total_tokens": 150}
    assert reported.provenance["cost"] == "reported"
    assert reported.provenance["api_calls"] == "reported"
    assert reported.provenance["input_tokens"] == "reported"


def test_reported_usage_cost_unknown_when_no_value_of_any_class():
    """A report that carries only `completed`/`failed`/`report_version` (as
    test doubles and a real runtime before it computed spend both do) yields
    None -- the caller keeps the `unknown` state, never a guessed amount."""
    payload = {"completed": True, "report_version": 1}
    assert cr.reported_usage_cost(payload) is None


def test_reported_usage_cost_never_reports_a_fabricated_amount():
    """A numeric amount is reported as `cost` ONLY under a recognised charge
    class. An `unknown` status with an amount is not a reported cost."""
    payload = {"completed": True, "report_version": 1,
               "cost_status": "unknown", "estimated_cost_usd": 0.5,
               "api_calls": 1}
    reported = cr.reported_usage_cost(payload)
    assert reported is not None
    assert reported.cost is None
    assert reported.cost_status == cr.COST_STATUS_UNKNOWN
    assert reported.provenance["cost"] == "unknown"


def test_reported_usage_cost_included_with_amount_is_estimated():
    """Hermes' subscription-included route computes an amount from its own
    price table; it is still the runtime's own estimate, so it is `reported`
    as `estimated`, never `approved`."""
    payload = {"completed": True, "report_version": 1,
               "cost_status": "included", "estimated_cost_usd": 0.0,
               "api_calls": 2}
    reported = cr.reported_usage_cost(payload)
    assert reported is not None
    assert reported.cost == 0.0
    assert reported.cost_status == cr.COST_STATUS_ESTIMATED


def test_reported_usage_cost_rejects_non_count_telemetry():
    """Token counts and `api_calls` are reported only when the field is a
    non-negative number; a bool or a negative value is never a count."""
    payload = {"completed": True, "report_version": 1,
               "cost_status": "estimated", "estimated_cost_usd": 0.1,
               "api_calls": True, "input_tokens": -5}
    reported = cr.reported_usage_cost(payload)
    assert reported is not None
    assert reported.api_calls is None
    assert "input_tokens" not in reported.usage
    assert reported.provenance["api_calls"] == "unknown"
    assert reported.provenance["input_tokens"] == "unknown"


# --- W12/#548: the measured-cost invariant and the advisory estimate path ---

def test_measured_cost_stays_reported_or_unknown_and_is_never_back_filled():
    """The invariant: measured `cost` is reported-or-`unknown`, never back-
    filled from a price table, manifest, or estimate. An unknown cost stays
    unknown even when an estimate for the same run exists."""
    # No cost statement of any class -> the caller keeps `unknown`.
    payload = {"completed": True, "report_version": 1, "api_calls": 1}
    reported = cr.reported_usage_cost(payload)
    assert reported is not None
    assert reported.cost is None
    assert reported.cost_status == cr.COST_STATUS_UNKNOWN
    assert reported.provenance["cost"] == "unknown"
    # The advisory estimate path exists separately and never touches `cost`.
    estimate = cr.EstimatedRunCost(
        amount=0.5, estimate_source="rate table", rate_date="2026-09-10")
    assert estimate.amount == 0.5
    assert reported.cost is None  # the estimate did not back-fill it
    assert reported.provenance["cost"] == "unknown"


def test_estimate_class_is_distinct_from_reported_and_unknown():
    """The advisory/estimate provenance class is its own value, distinct from
    the design §3.1 classes, and is what the estimate fields carry."""
    assert cr.PROVENANCE_ESTIMATE == "estimate"
    assert cr.PROVENANCE_ESTIMATE != "reported"
    assert cr.PROVENANCE_ESTIMATE != "unknown"
    estimate = cr.EstimatedRunCost(
        amount=0.4, estimate_source="rate table: inferx-published-2026-09-10",
        rate_date="2026-09-10")
    provenance = estimate.provenance()
    assert set(provenance.values()) == {cr.PROVENANCE_ESTIMATE}
    assert provenance["estimated_cost"] == "estimate"


def test_estimate_comparison_against_unknown_is_unverified_never_agree():
    """§3.4: comparing anything against an estimate or an unknown yields
    `unverified` -- never `agree`."""
    estimate = cr.EstimatedRunCost(
        amount=0.5, estimate_source="rate table", rate_date="2026-09-10")
    # Unknown reported cost against a known estimate: unverified.
    comparison, warning = cr.compare_cost_against_estimate(None, estimate)
    assert comparison == "unverified"
    assert "unverified" in warning
    # Known reported cost against no estimate: unverified too.
    comparison, warning = cr.compare_cost_against_estimate(0.5, None)
    assert comparison == "unverified"
    assert "unverified" in warning
    # Both unknown: unverified, never agree.
    comparison, _ = cr.compare_cost_against_estimate(None, None)
    assert comparison == "unverified"


def test_estimate_comparison_agrees_only_numerically_with_binding_unverified_warning():
    """Even when the amounts are close, the wording carries the §3.4
    "binding unverified"-style warning: an estimate is advisory and never
    verifies the reported amount."""
    estimate = cr.EstimatedRunCost(
        amount=0.50, estimate_source="rate table", rate_date="2026-09-10")
    comparison, warning = cr.compare_cost_against_estimate(0.52, estimate)
    assert comparison == "agree"
    assert "binding unverified" in warning


def test_estimate_comparison_diverges_beyond_tolerance():
    estimate = cr.EstimatedRunCost(
        amount=0.50, estimate_source="rate table", rate_date="2026-09-10")
    comparison, warning = cr.compare_cost_against_estimate(1.20, estimate)
    assert comparison == "diverge"
    assert "does not change the Run's status" in warning


def test_reconciliation_record_is_evidence_not_a_gate():
    """The optional post-hoc reconciliation against a provider billing surface
    emits an evidence record with a three-valued comparison; it never changes
    `status` and never enters the Evidence Gate (design §3.4 tiers)."""
    # Both amounts present and equal -> agree (numerical), still advisory.
    record = cr.reconcile_cost_with_billing_surface(
        0.50, 0.50, billing_surface="InferX token-billing panel")
    assert record["kind"] == "cost_reconciliation"
    assert record["comparison"] == "agree"
    assert record["warning"] is None
    # Divergence is recorded with the warning, never as a gate failure.
    record = cr.reconcile_cost_with_billing_surface(
        0.50, 0.90, billing_surface="InferX token-billing panel")
    assert record["comparison"] == "diverge"
    assert "does not change the Run's status" in record["warning"]
    # Unknown on either side -> unverified, never agree.
    record = cr.reconcile_cost_with_billing_surface(
        None, 0.50, billing_surface="InferX token-billing panel")
    assert record["comparison"] == "unverified"
    assert "unverified" in record["warning"]
    record = cr.reconcile_cost_with_billing_surface(
        0.50, None, billing_surface="InferX token-billing panel")
    assert record["comparison"] == "unverified"
