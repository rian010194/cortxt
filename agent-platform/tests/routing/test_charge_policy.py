"""Charge policy and route eligibility (W11 / #542; design §2, §3.4).

Deterministic proof of the acceptance rules:

- a ``report_channel: none`` route (``dsh``) is refused ``zero_charge``; only a
  ``structured`` route is eligible;
- ``charge_policy_id`` and ``charge_policy_revision`` are versioned on the policy;
- the policy is bound to a route, and a route-binding change is a revision
  (the digest changes), not a silent mutation;
- an unchanged policy keeps a stable revision;
- W12/#548: the rate the verdict rests on (``rate_source`` + ``rate_snapshot``)
  is part of the digested content -- a provider rate change is a revision that
  invalidates any confirmation bound to the old one.
"""

import pytest

from routing.charge_policy import (
    CHARGE_POLICY_FIELDS,
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
        rate_source="InferX token-billing panel (provider's own billing surface)",
        rate_snapshot="USD 0.00 per 1k tokens (free tier), read 2026-09-10",
    )
    base.update(overrides)
    return ChargePolicy(**base)


# --- zero_charge eligibility -------------------------------------------------

def test_none_channel_runtime_is_refused_zero_charge():
    """`dsh` explicitly declares `report_channel: none` -> not eligible for
    zero_charge, classified as `none_channel`."""
    result = zero_charge_eligible("dsh", _policy())
    assert result.eligible is False
    assert result.code == "none_channel"


def test_structured_channel_runtime_is_eligible_for_zero_charge():
    """A structured route (hermes-free) with a zero_charge policy is eligible."""
    result = zero_charge_eligible("hermes-free", _policy())
    assert result.eligible is True


def test_unknown_runtime_is_refused_zero_charge():
    """The zero_charge path fails closed: a runtime whose completion channel
    nobody has declared cannot supply a verified model identity, so it is
    refused even though `report_channel()` would default it to `structured`."""
    result = zero_charge_eligible("some-new-runtime", _policy())
    assert result.eligible is False
    assert result.code == "undeclared_channel"


def test_explicit_non_structured_non_none_channel_is_defensively_refused(monkeypatch):
    """A declared channel that is neither `structured` nor `none` is refused
    via `unstructured_channel`. Defensive: no such value exists in
    `REPORT_CHANNELS` today, so this pins the fallback classification."""
    from routing import completion_report as cr
    monkeypatch.setitem(cr.REPORT_CHANNELS, "some-runtime", "unstructured")
    result = zero_charge_eligible("some-runtime", _policy())
    assert result.eligible is False
    assert result.code == "unstructured_channel"


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


def test_pure_id_rename_does_not_change_the_revision():
    """Design §2.1: the revision is over semantic content, not identifiers.
    Renaming the record (same verdict/source/dates/route) is not a revision."""
    base = _policy(charge_policy_id="cp-old-name")
    renamed = _policy(charge_policy_id="cp-new-name")
    assert renamed.charge_policy_revision == base.charge_policy_revision


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


# --- W12/#548: the rate the verdict rests on is digested content ------------

def test_rate_fields_are_part_of_the_digested_content():
    """`rate_source` + `rate_snapshot` are in `CHARGE_POLICY_FIELDS`, so they
    participate in the revision digest -- a provider rate change cannot ride
    an old confirmation."""
    assert "rate_source" in CHARGE_POLICY_FIELDS
    assert "rate_snapshot" in CHARGE_POLICY_FIELDS
    content = _policy().as_content()
    assert "rate_source" in content
    assert "rate_snapshot" in content


def test_provider_rate_change_changes_the_revision():
    """A provider rate change (a different snapshot from the same source)
    produces a new `charge_policy_revision`."""
    base = _policy()
    repriced = _policy(
        rate_snapshot="USD 0.002 per 1k tokens, read 2026-09-11")
    assert repriced.rate_source == base.rate_source
    assert repriced.charge_policy_revision != base.charge_policy_revision


def test_rate_source_change_changes_the_revision():
    """Reading the rate from a different surface is a revision too."""
    base = _policy()
    other = _policy(rate_source="provider pricing page, mirrored read")
    assert other.charge_policy_revision != base.charge_policy_revision


def test_identical_rate_fields_keep_a_stable_revision():
    assert charge_policy_revision(_policy()) == charge_policy_revision(_policy())


def test_empty_rate_source_is_rejected():
    """A verdict resting on nothing readable is not a policy (fail closed)."""
    with pytest.raises(ChargePolicyError):
        _policy(rate_source="")


def test_empty_rate_snapshot_is_rejected():
    with pytest.raises(ChargePolicyError):
        _policy(rate_snapshot="")


def test_metered_verdict_official_source_requirements_are_documented():
    """`metered` reads the provider's own billing surface; a published
    aggregator is acceptable only when the provider publishes none of its
    own. `zero_charge` keeps W11's provider's-own-free-tier-statement rule.
    Pinned as documentation so the module cannot silently drop it."""
    from routing.charge_policy import ROUTE_METERED, ROUTE_ZERO_CHARGE
    import routing.charge_policy as cp_module
    module_doc = cp_module.__doc__ or ""
    # `metered`: the provider's own billing surface (InferX token-billing
    # panel); OpenRouter only when the provider publishes no billing surface
    # of its own.
    assert "InferX" in module_doc
    assert "OpenRouter" in module_doc
    assert "token-billing panel" in module_doc
    # `zero_charge` keeps the provider's own free-tier statement (W11).
    assert "free-tier statement" in module_doc
    assert ROUTE_METERED == "metered" and ROUTE_ZERO_CHARGE == "zero_charge"
