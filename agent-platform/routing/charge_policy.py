"""Versioned charge policy and route eligibility (design §2, §3.4; W11 / #542).

A route runs under one of two charging regimes: ``metered`` (the provider bills
the call) or ``zero_charge`` (a verified per-``(provider, model)`` record says
this model does not bill). The ``zero_charge`` regime's entire safety argument
is that *this specific model* answered and does not charge -- which rests on the
platform being able to verify what answered. A route whose runtime has no
structured completion channel cannot establish that, so ``zero_charge`` is
available **only** to a ``structured`` route (design §1.3, §3.4). A route that
declares ``report_channel: none`` (``dsh`` today) is refused ``zero_charge``.

The policy in force is immutable and auditable:

- ``charge_policy_id`` names the declared charging record.
- ``charge_policy_revision`` is a digest over the record's *semantic content* --
  the charging verdict, its official source, the date it was read, its expiry,
  and the route it is bound to. Binding the revision (not just the id) is
  deliberate: an id names a mutable record, and the predecessor's mistake was
  inferring charging from ``cost_class``, the field that stays ``free`` when the
  model changes underneath it (``engine_manifest.py``).

``charge_policy.route`` binds the policy to a regime. A change to that binding
is a revision, never a silent mutation: ``route`` is part of the digested
content, so re-binding a policy to a different route yields a different
``charge_policy_revision`` and invalidates any confirmation bound to the old one.

Canonicalisation reuses the shared rule in ``routing/execution_profile``
(``canonical_json`` / ``sha256_digest``): a new digest mechanism is exactly what
this item must not introduce.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from routing.completion_report import CHANNEL_STRUCTURED, REPORT_CHANNELS
from routing.execution_profile import canonical_json, sha256_digest

# The two charging regimes. `route` names which one a policy is bound to;
# `charging` is the verdict the official source recorded for the model.
ROUTE_ZERO_CHARGE = "zero_charge"
ROUTE_METERED = "metered"
VALID_ROUTES = frozenset({ROUTE_ZERO_CHARGE, ROUTE_METERED})

# The semantic fields the revision digests -- content, never identifiers
# (design §2.1: the revision is over "semantic content, not identifiers", so a
# pure rename of the record must not read as a material change). Order is
# load-bearing for the canonical serialisation; keep it fixed.
CHARGE_POLICY_FIELDS = (
    "charging",
    "official_source",
    "read_date",
    "expiry",
    "route",
)


class ChargePolicyError(ValueError):
    """A charge policy that cannot be constructed as declared."""


@dataclass(frozen=True)
class ChargePolicy:
    """One declared per-``(provider, model)`` charging record, bound to a route.

    ``charging`` is the verdict read from ``official_source`` on ``read_date``,
    valid until ``expiry``. ``route`` is the regime an operator confirms they
    are launching under. A ``zero_charge`` route requires the verdict to agree
    (``charging == "zero_charge"``); a route/verdict mismatch is not a valid
    policy.
    """

    charge_policy_id: str
    charging: str
    official_source: str
    read_date: str
    expiry: str
    route: str

    def __post_init__(self) -> None:
        if not self.charge_policy_id:
            raise ChargePolicyError("charge_policy_id must be a non-empty string")
        if self.charging not in VALID_ROUTES:
            raise ChargePolicyError(
                f"charging must be one of {sorted(VALID_ROUTES)}, got {self.charging!r}"
            )
        if self.route not in VALID_ROUTES:
            raise ChargePolicyError(
                f"route must be one of {sorted(VALID_ROUTES)}, got {self.route!r}"
            )
        if self.route == ROUTE_ZERO_CHARGE and self.charging != ROUTE_ZERO_CHARGE:
            raise ChargePolicyError(
                "a zero_charge route requires a zero_charge charging verdict; "
                f"got charging={self.charging!r}"
            )

    def as_content(self) -> dict[str, Any]:
        """The semantic content the revision digests (never identifiers)."""
        return {key: getattr(self, key) for key in CHARGE_POLICY_FIELDS}

    @property
    def charge_policy_revision(self) -> str:
        return charge_policy_revision(self)


def charge_policy_revision(policy: "ChargePolicy | Mapping[str, Any]") -> str:
    """Immutable digest over the policy's semantic content, including its route.

    Deterministic across identical content; any change to a digested field --
    the charging verdict, its source, the dates, or the bound ``route`` --
    yields a different revision, so a confirmation bound to the old revision is
    stale.
    """
    content = policy.as_content() if isinstance(policy, ChargePolicy) else dict(policy)
    return sha256_digest(canonical_json(content, CHARGE_POLICY_FIELDS))


@dataclass(frozen=True)
class EligibilityResult:
    """Whether a policy may run under ``zero_charge`` for a given runtime."""

    eligible: bool
    reason: str
    code: str | None = None


def zero_charge_eligible(runtime: str, policy: ChargePolicy) -> EligibilityResult:
    """Is ``policy`` allowed to run ``runtime`` under the ``zero_charge`` regime?

    Both conditions are required:

    1. The policy's bound ``route`` is ``zero_charge``. A ``metered`` policy is
       not eligible for -- and does not need -- the check; it is reported as a
       route mismatch rather than silently passing.
    2. ``runtime`` **explicitly** declares a ``structured`` completion channel
       in ``routing.completion_report.REPORT_CHANNELS``. This path fails
       *closed*: unlike ``report_channel()`` (which defaults an unregistered
       runtime to ``structured`` so a new adapter still owes a report), an
       unregistered runtime here is refused ``zero_charge``. The regime rests
       on a verified model identity (design §1.3, §3.4), and a runtime whose
       channel nobody has declared cannot supply one -- so a ``none``-channel
       runtime (``dsh``) and an unknown runtime are both refused.
    """
    if policy.route != ROUTE_ZERO_CHARGE:
        return EligibilityResult(
            False,
            f"policy route is {policy.route!r}, not {ROUTE_ZERO_CHARGE!r}",
            code="route_mismatch",
        )
    declared = REPORT_CHANNELS.get(runtime)
    if declared != CHANNEL_STRUCTURED:
        detail = (f"declares report channel {declared!r}" if declared is not None
                  else "has no declared completion channel")
        return EligibilityResult(
            False,
            f"runtime {runtime!r} {detail}; {ROUTE_ZERO_CHARGE!r} requires an "
            f"explicitly declared {CHANNEL_STRUCTURED!r} channel",
            code="unstructured_channel" if declared is not None else "undeclared_channel",
        )
    return EligibilityResult(
        True,
        f"runtime {runtime!r} explicitly declares a {CHANNEL_STRUCTURED!r} channel",
    )
