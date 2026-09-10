"""Charge policy and route eligibility (W11 / #542; design §2, §3.4).

Deterministic proof of the four acceptance rules:

- a ``report_channel: none`` route (``dsh``) is refused ``zero_charge``; only a
  ``structured`` route is eligible;
- ``charge_policy_id`` and ``charge_policy_revision`` are versioned on the policy;
- the policy is bound to a route, and a route-binding change is a revision
  (the digest changes), not a silent mutation;
- an unchanged policy keeps a stable revision.
"""

import pytest

from routing.charge_policy import (
    ChargePolicy,
    ChargePolicyError,
    charge_policy_revision,
    zero_charge_eligible,
)


def _policy(**overrides):
    base = dict(
        charge_policy_id="cp-nous-deepseek-v4-flash",
        charging="zero_charge",
        official_source="https://model.inferx.net pricing, read 2026-09-10",
        read_date="2026-09-10",
        expiry="2026-12-10",
        route="zero_charge",
    )
    base.update(overrides)
    return ChargePolicy(**base)


# --- zero_charge eligibility -------------------------------------------------

def test_none_channel_runtime_is_refused_zero_charge():
    """`dsh` declares `report_channel: none` -> not eligible for zero_charge."""
    result = zero_charge_eligible("dsh", _policy())
    assert result.eligible is False
    assert result.code == "unstructured_channel"


def test_structured_channel_runtime_is_eligible_for_zero_charge():
    """A structured route (hermes-free) with a zero_charge policy is eligible."""
    result = zero_charge_eligible("hermes-free", _policy())
    assert result.eligible is True


def test_unknown_runtime_defaults_structured_and_is_eligible():
    """An unrecognised runtime fails closed to `structured` in completion_report,
    so it is eligible -- the exemption must be declared, never inferred."""
    assert zero_charge_eligible("some-new-runtime", _policy()).eligible is True


def test_metered_policy_is_a_route_mismatch_not_a_silent_pass():
    result = zero_charge_eligible(
        "hermes-free", _policy(charging="metered", route="metered"))
    assert result.eligible is False
    assert result.code == "route_mismatch"


# --- versioned revision ----------------------------------------------------

def test_revision_is_deterministic_for_unchanged_content():
    assert _policy().charge_policy_revision == _policy().charge_policy_revision
    assert charge_policy_revision(_policy()).startswith("sha256:")


def test_route_binding_change_is_a_revision():
    """Re-binding the same record to a different route changes the revision."""
    zero = _policy(charging="zero_charge", route="zero_charge")
    metered = _policy(charging="metered", route="metered")
    assert zero.charge_policy_revision != metered.charge_policy_revision


def test_content_change_under_same_id_changes_the_revision():
    """The predecessor mistake -- an id naming a mutable record -- is closed:
    the digest is over content, so a changed expiry invalidates confirmation."""
    base = _policy()
    changed = _policy(expiry="2027-01-01")
    assert changed.charge_policy_id == base.charge_policy_id
    assert changed.charge_policy_revision != base.charge_policy_revision


def test_mapping_and_dataclass_digest_identically():
    policy = _policy()
    assert charge_policy_revision(policy.as_content()) == policy.charge_policy_revision


# --- construction invariants ---------------------------------------------

def test_zero_charge_route_requires_zero_charge_verdict():
    with pytest.raises(ChargePolicyError):
        _policy(charging="metered", route="zero_charge")


def test_invalid_route_is_rejected():
    with pytest.raises(ChargePolicyError):
        _policy(route="free")


def test_empty_id_is_rejected():
    with pytest.raises(ChargePolicyError):
        _policy(charge_policy_id="")
