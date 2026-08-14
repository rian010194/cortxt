"""Static guard: reasoning/ must not import Hermes, Pi, InferX, or any concrete
provider — the core depends only on internal contracts (ADR-016 invariant)."""

import ast
import pathlib

_BANNED = {"hermes", "pi", "inferx", "openai", "anthropic", "moonshot", "kimi"}
_REPO = pathlib.Path(__file__).resolve().parents[2] / "reasoning"


def _all_imports():
    imports = []
    for py in _REPO.rglob("*.py"):
        if "site-packages" in py.parts or ".venv" in py.parts:
            continue
        tree = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    imports.append((str(py), a.name.split(".")[0]))
            elif isinstance(node, ast.ImportFrom) and node.module:
                # Relative imports (module starts with '.') are internal by definition.
                if node.level > 0:
                    continue
                imports.append((str(py), node.module.split(".")[0]))
    return imports


def test_reasoning_has_no_external_provider_deps():
    bad = [(p, top) for p, top in _all_imports() if top.lower() in _BANNED]
    assert bad == [], f"external provider imports found in reasoning/: {bad}"


def test_reasoning_imports_are_internal():
    externals = [top for _, top in _all_imports()
                 if top not in ("reasoning", "__future__", "ast", "hashlib", "math",
                                "collections", "dataclasses", "enum", "typing", "itertools", "time")]
    # Any unknown top-level must be stdlib.
    import sys

    stdlib = set(sys.stdlib_module_names)
    unexpected = [top for top in externals if top not in stdlib]
    assert unexpected == [], f"non-internal/non-stdlib imports: {unexpected}"
