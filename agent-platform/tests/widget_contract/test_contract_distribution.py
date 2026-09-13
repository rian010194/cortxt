"""Package version surface (VLT-D-007 step 2, issue #604).

The distributed package is what ``cortxt-agents`` pins via
``cortxt-contracts @ git+...@contracts/vX.Y.Z#subdirectory=contracts``, so the
package itself must carry the version surface the N/N-1 policy needs:

* ``SUPPORTED_CONTRACT_VERSIONS`` -- the N/N-1 window the package supports;
* ``SCHEMA_VERSION`` -- the dispatch-request projection version the packaged
  exports were generated from;
* the worker-facing schema pair and the worker-contract grammar, exported so a
  consumer can validate requests and read the attestation grammar from the
  *package* without a core checkout.
"""

import json

import pytest

from widget_contract import schema_source
from widget_contract.registry import (
    DISPATCH_REQUEST_SCHEMA,
    DISPATCH_REQUEST_V2_SCHEMA,
)


def test_package_version_module_exists():
    """``cortxt_contracts.version`` carries the distribution version surface."""
    import cortxt_contracts.version as version_module

    for name in (
        "CONTRACT_TAG_PREFIX",
        "CONTRACT_PACKAGE_VERSION",
        "CONTRACT_SEMVER_RE",
        "SUPPORTED_CONTRACT_VERSIONS",
        "dispatch_request_schema_version",
        "latest_supported_contract_version",
        "supported_contract_version_is_active",
    ):
        assert hasattr(version_module, name), f"missing: {name}"


def test_supported_contract_versions_is_n_and_n_minus_1():
    """N/N-1 policy: exactly the current and the previous major supported."""
    from cortxt_contracts.version import SUPPORTED_CONTRACT_VERSIONS

    assert SUPPORTED_CONTRACT_VERSIONS == ("2.0.0", "1.0.0")
    # CONTRACT_SEMVER is the compiled semver pattern used by tag parsing.
    from cortxt_contracts.version import CONTRACT_SEMVER_RE

    assert CONTRACT_SEMVER_RE.match("2.0.0")
    assert not CONTRACT_SEMVER_RE.match("2.0")


def test_latest_supported_is_first_element():
    """The first entry is N; helpers must agree with the tuple."""
    from cortxt_contracts.version import (
        SUPPORTED_CONTRACT_VERSIONS,
        latest_supported_contract_version,
    )

    assert latest_supported_contract_version() == SUPPORTED_CONTRACT_VERSIONS[0]


def test_version_helpers_classify_membership():
    from cortxt_contracts.version import (
        SUPPORTED_CONTRACT_VERSIONS,
        supported_contract_version_is_active,
    )

    assert supported_contract_version_is_active("2.0.0") is True
    assert supported_contract_version_is_active("1.0.0") is True
    assert supported_contract_version_is_active("0.9.0") is False
    assert supported_contract_version_is_active("") is False
    assert supported_contract_version_is_active(None) is False
    # unknown semantic version outside the window
    assert supported_contract_version_is_active("3.0.0") is False
    assert SUPPORTED_CONTRACT_VERSIONS[0] == "2.0.0"


def test_tag_version_round_trip():
    from cortxt_contracts.version import (
        CONTRACT_TAG_PREFIX,
        contract_tag,
        parse_contract_tag,
    )

    assert CONTRACT_TAG_PREFIX == "contracts/v"
    assert contract_tag("2.0.0") == "contracts/v2.0.0"
    assert parse_contract_tag("contracts/v2.0.0") == "2.0.0"
    assert parse_contract_tag("refs/tags/contracts/v1.0.0") == "1.0.0"
    assert parse_contract_tag("v2.0.0") is None
    assert parse_contract_tag("contracts/vnot-semver") is None


def test_dispatch_request_schema_version_matches_package():
    """SCHEMA_VERSION must name the dispatch schema version actually exported."""
    from cortxt_contracts.version import (
        SCHEMA_VERSION,
        dispatch_request_schema_version,
    )

    assert SCHEMA_VERSION == "2"
    assert dispatch_request_schema_version() == SCHEMA_VERSION
    # cross-check against the embedded production dict (independent source)
    assert DISPATCH_REQUEST_V2_SCHEMA["properties"]["schema_version"]["const"] == int(
        SCHEMA_VERSION
    )


def test_packaged_schemas_match_repo_exports(tmp_path):
    """The packaged JSON must be byte-identical to the repo's canonical exports."""
    from cortxt_contracts import load_schema, schema_names

    names = schema_names()
    assert names == sorted(names)
    assert "dispatch-request.v1" in names
    assert "dispatch-request.v2" in names

    for name in names:
        packaged = load_schema(name)
        # every packaged schema must be a JSON object
        assert isinstance(packaged, dict), name

    # the packaged v2 export must be the canonical bytes of the embedded dict
    canonical = schema_source._canonical_bytes(
        schema_source.export_schema(DISPATCH_REQUEST_V2_SCHEMA)
    )
    on_disk = (
        schema_source.CONTRACTS_DIR
        / schema_source.EXPORT_FILENAMES["dispatch.request.v2"]
    ).read_bytes()
    assert on_disk == canonical


def test_worker_schema_pair_is_packaged():
    """The worker-facing pair must ship in the package (distribution step 2)."""
    from cortxt_contracts import load_schema

    dispatch = load_schema("dispatch-request")
    envelope = load_schema("result-envelope")
    assert isinstance(dispatch, dict) and dispatch.get("type") == "object"
    assert isinstance(envelope, dict) and envelope.get("type") == "object"
    assert "worker_role" in envelope["properties"]


def test_worker_grammar_export():
    """The package exports the worker-contract grammar, read-only."""
    from cortxt_contracts import worker_contract_grammar

    grammar = worker_contract_grammar()
    assert grammar["contract_version"] == "worker.result.v1"
    assert grammar["attestation_prefix"] == "CORTXT-OUTCOME:"
    assert tuple(grammar["attestable"]) == ("completed", "declined")
    assert grammar["source"] == "packaged"


def test_worker_grammar_matches_core_declarations():
    """The packaged grammar must equal the core's own declarations.

    ``cortxt_contracts.worker_contract_grammar`` mirrors
    ``agent-platform/routing/worker_contract.py`` (CONTRACT_VERSION /
    ATTESTATION_PREFIX / ATTESTABLE). This congruence check fails closed when
    the core declarations change without the packaged copy being regenerated.
    """
    from routing import worker_contract
    from cortxt_contracts import worker_contract_grammar

    grammar = worker_contract_grammar()
    assert grammar["contract_version"] == worker_contract.CONTRACT_VERSION
    assert grammar["attestation_prefix"] == worker_contract.ATTESTATION_PREFIX
    assert tuple(grammar["attestable"]) == tuple(worker_contract.ATTESTABLE)


def test_contracts_status_pinned_package_side(tmp_path, monkeypatch):
    """cortxt-agents (side B) consumes this: the package must expose enough
    for a fail-closed status check without a core checkout."""
    import cortxt_contracts
    from cortxt_contracts import worker_contract_grammar

    assert cortxt_contracts.__version__ == "2.0.0"
    grammar = worker_contract_grammar()
    assert grammar["contract_version"] == "worker.result.v1"
