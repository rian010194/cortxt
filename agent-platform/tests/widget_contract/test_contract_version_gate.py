"""Producer-CI-gate tests: contract change without version bump must be red.

VLT-D-007 §3 (issue #604): the core's PR-CI runs a schema diff against the
latest ``contracts/vX.Y.Z`` tag and blocks a contract change without a
version bump, and a MAJOR bump without a ``SUPPORTED_CONTRACT_VERSIONS``
extension (the buf pattern, in miniature).

Independent source of truth: the tag list and the tagged bytes are injected,
never probed, so the tests stay offline and deterministic.
"""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "contract_version_gate.py"


def _load_gate():
    """Import ``scripts/contract_version_gate.py`` by path (it is not a package)."""
    spec = importlib.util.spec_from_file_location("contract_version_gate", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_version_module(
    contracts: Path, version: str = "2.0.0", supported: tuple = ("2.0.0", "1.0.0")
) -> None:
    """Write a minimal version policy module (the shape the gate parses)."""
    (contracts / "cortxt_contracts").mkdir(parents=True, exist_ok=True)
    (contracts / "cortxt_contracts" / "version.py").write_text(
        f"CONTRACT_PACKAGE_VERSION = {version!r}\n"
        f"SUPPORTED_CONTRACT_VERSIONS = {supported!r}\n",
        encoding="utf-8",
    )


def _write_schema(contracts: Path, name: str, payload: dict) -> bytes:
    target = contracts / "cortxt_contracts" / "schemas"
    target.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(payload, indent=2) + "\n").encode("utf-8")
    target.joinpath(name).write_bytes(raw)
    return raw


def _dump(contracts: Path, schemas: dict[str, dict]) -> dict[str, bytes]:
    blobs: dict[str, bytes] = {}
    for name, doc in schemas.items():
        blobs[name] = _write_schema(contracts, name, doc)
    return blobs


def _tag_blobs(blobs: dict[str, bytes]) -> "callable":
    def reader(relpath: str) -> bytes | None:
        name = relpath.rsplit("/", 1)[-1]
        return blobs.get(name)

    return reader


def _gate(
    contracts: Path, *, tags: list[str], tag_blobs: dict[str, bytes] | None = None
) -> list[str]:
    gate = _load_gate()
    return gate.evaluate(
        contracts,
        tags,
        tag_blob=_tag_blobs(tag_blobs) if tag_blobs is not None else None,
    )


V2 = {"schema_version": {"const": 2}}
V2_CHANGED = {"schema_version": {"const": 2}, "tampered": True}
V1 = {"schema_version": {"const": 1}}
ENVELOPE = {"type": "object"}
ALL_SCHEMAS = {
    "dispatch-request.v2.schema.json": V2,
    "dispatch-request.v1.schema.json": V1,
    "dispatch-request.schema.json": ENVELOPE,
    "result-envelope.schema.json": ENVELOPE,
}


def test_gate_script_exists():
    assert SCRIPT.is_file(), f"missing {SCRIPT}"


def test_no_tag_yet_is_green(tmp_path):
    """The first distribution has nothing to diff against."""
    contracts = tmp_path / "contracts"
    _write_version_module(contracts)
    assert _gate(contracts, tags=[]) == []


def test_schema_change_with_bump_is_green(tmp_path):
    contracts = tmp_path / "contracts"
    _write_version_module(contracts, "2.1.0", ("2.1.0", "2.0.0"))
    assert _gate(contracts, tags=["contracts/v2.0.0"]) == []


def test_schema_change_without_bump_is_red(tmp_path):
    contracts = tmp_path / "contracts"
    _write_version_module(contracts, "2.0.0", ("2.0.0", "1.0.0"))
    _write_schema(contracts, "dispatch-request.v2.schema.json", V2_CHANGED)
    findings = _gate(contracts, tags=["contracts/v2.0.0"])
    assert findings, "unchanged version with changed schema must be red"
    assert any("bump" in finding.lower() for finding in findings)


def test_unchanged_tree_against_tag_is_green(tmp_path):
    """Same version, byte-identical schemas = green."""
    contracts = tmp_path / "contracts"
    _write_version_module(contracts, "2.0.0", ("2.0.0", "1.0.0"))
    blobs = _dump(contracts, ALL_SCHEMAS)
    assert _gate(contracts, tags=["contracts/v2.0.0"], tag_blobs=blobs) == []


def test_breaking_major_bump_without_supported_extension_is_red(tmp_path):
    contracts = tmp_path / "contracts"
    _write_version_module(contracts, "3.0.0", ("2.0.0", "1.0.0"))
    findings = _gate(contracts, tags=["contracts/v2.0.0"])
    assert any("SUPPORTED_CONTRACT_VERSIONS" in f for f in findings)


def test_major_bump_with_dual_acceptance_is_green(tmp_path):
    contracts = tmp_path / "contracts"
    _write_version_module(contracts, "3.0.0", ("3.0.0", "2.0.0"))
    assert _gate(contracts, tags=["contracts/v2.0.0"]) == []


def test_window_wider_than_n_minus_1_is_red(tmp_path):
    contracts = tmp_path / "contracts"
    _write_version_module(contracts, "2.1.0", ("2.1.0", "2.0.0", "1.0.0"))
    findings = _gate(contracts, tags=["contracts/v2.0.0"])
    assert any("N/N-1" in f for f in findings)


def test_window_head_must_equal_package_version(tmp_path):
    contracts = tmp_path / "contracts"
    _write_version_module(contracts, "2.1.0", ("2.0.0", "1.0.0"))
    findings = _gate(contracts, tags=["contracts/v2.0.0"])
    assert any("SUPPORTED_CONTRACT_VERSIONS[0]" in f for f in findings)


def test_minor_bump_needs_no_dual_acceptance(tmp_path):
    contracts = tmp_path / "contracts"
    _write_version_module(contracts, "2.1.0", ("2.1.0", "2.0.0"))
    assert _gate(contracts, tags=["contracts/v2.0.0"]) == []


def test_version_module_missing_is_red(tmp_path):
    """Fail-closed: no policy module under contracts/ cannot be green."""
    contracts = tmp_path / "contracts"
    contracts.mkdir(parents=True)
    findings = _gate(contracts, tags=["contracts/v2.0.0"])
    assert findings and "version module unreadable" in findings[0]


def test_agents_yaml_never_read_by_routing():
    """ADR-026 / VLT-D-007 §6: routing must never read agents.yaml."""
    routing_dir = REPO_ROOT / "agent-platform" / "routing"
    offenders = []
    for path in sorted(routing_dir.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        if "agents.yaml" in text or "agents_yaml" in text:
            offenders.append(path.name)
    assert offenders == [], (
        "routing must never read contracts/agents.yaml (ADR-026, VLT-D-007 "
        f"§6); offenders: {offenders}"
    )
