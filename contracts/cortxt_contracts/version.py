"""Contract version surface (VLT-D-007 step 2, issue #604).

This module is the package-side half of the N/N-1 contract-version policy:

* the distribution tag schema (``contracts/vX.Y.Z``) and its round-trip;
* ``SUPPORTED_CONTRACT_VERSIONS`` -- the N/N-1 window the core still accepts;
* ``SCHEMA_VERSION`` -- the dispatch-request projection version the packaged
  exports were generated from (kept in step with the embedded
  ``DISPATCH_REQUEST_V2_SCHEMA`` by the congruence test).

N−1 stops being supported when ``contracts/agents.yaml`` shows full migration
(VLT-D-007 §2); until that record exists both lines stay listed here.
"""

from __future__ import annotations

import re

__all__ = [
    "CONTRACT_PACKAGE_VERSION",
    "CONTRACT_SEMVER_RE",
    "CONTRACT_TAG_PREFIX",
    "SUPPORTED_CONTRACT_VERSIONS",
    "contract_package_version",
    "contract_tag",
    "dispatch_request_schema_version",
    "latest_supported_contract_version",
    "parse_contract_tag",
    "supported_contract_version_is_active",
]

#: The tag namespace the core publishes contracts under (VLT-D-007 §1).
CONTRACT_TAG_PREFIX = "contracts/v"

#: N/N-1: the current major and the previous one, newest first. A consumer pin
#: may use either; anything older is outside the supported window. N−1 is
#: removed when ``contracts/agents.yaml`` shows full migration (VLT-D-007 §2).
SUPPORTED_CONTRACT_VERSIONS: tuple[str, ...] = ("2.0.0", "1.0.0")

#: The package version that ships the current schema exports. Step 1 shipped
#: 1.0.0 (dispatch.request.v1 + v2); step 2 re-issues the exports as 2.0.0,
#: matching N. The tag cut for a release must equal this version.
CONTRACT_PACKAGE_VERSION = "2.0.0"

#: The dispatch-request schema version these exports were generated from.
#: Asserted against the embedded production dict by the congruence test.
SCHEMA_VERSION = "2"

#: A strict semantic version, digits only (no pre-release/build metadata in
#: this tag vocabulary -- a contract tag must sort trivially).
CONTRACT_SEMVER_RE = re.compile(r"(\d+)\.(\d+)\.(\d+)\Z")

_TAG_RE = re.compile(
    r"(?:refs/tags/)?" + re.escape(CONTRACT_TAG_PREFIX) + r"(\d+\.\d+\.\d+)\Z"
)


def contract_package_version() -> str:
    """The ``cortxt-contracts`` package version (== N)."""
    return CONTRACT_PACKAGE_VERSION


def latest_supported_contract_version() -> str:
    """N -- the first (newest) entry of :data:`SUPPORTED_CONTRACT_VERSIONS`."""
    return SUPPORTED_CONTRACT_VERSIONS[0]


def supported_contract_version_is_active(version: object) -> bool:
    """Return ``True`` when ``version`` is inside the N/N-1 window.

    Unknown, empty and non-string values are *not* active (fail-closed): the
    caller must treat them as an unsupported contract, never as "latest".
    """
    if not isinstance(version, str):
        return False
    return version in SUPPORTED_CONTRACT_VERSIONS


def contract_tag(version: str) -> str:
    """Return the distribution tag for ``version`` (``contracts/vX.Y.Z``)."""
    if not CONTRACT_SEMVER_RE.match(version):
        raise ValueError(f"not a semantic contract version: {version!r}")
    return f"{CONTRACT_TAG_PREFIX}{version}"


def parse_contract_tag(ref: str) -> str | None:
    """Return the version inside a ``contracts/vX.Y.Z`` ref, or ``None``.

    Accepts the bare tag and the full ``refs/tags/`` form; anything else
    (including other tag namespaces) is ``None``.
    """
    if not isinstance(ref, str):
        return None
    match = _TAG_RE.match(ref)
    return match.group(1) if match else None


def dispatch_request_schema_version() -> str:
    """The dispatch-request projection version the exports carry."""
    return SCHEMA_VERSION
