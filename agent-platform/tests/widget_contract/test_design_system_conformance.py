from __future__ import annotations

import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / "scripts" / "design_system_conformance.py"


def _module():
    spec = importlib.util.spec_from_file_location("design_system_conformance", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_repository_conforms_to_global_design_system_contract():
    _module().validate()


def test_private_token_definition_pattern_rejects_consumer_owned_role():
    module = _module()
    assert module.PRIVATE_TOKEN_DEFINITION.search(":root { --token-accent: #fff; }")
    assert not module.PRIVATE_TOKEN_DEFINITION.search("color: var(--token-accent, #fff)")
