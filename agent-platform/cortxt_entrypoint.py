"""Collision-safe console entry point for the Cortxt CLI.

The generic top-level package name ``cli`` can be shadowed by third-party
modules in an operator environment. The installed command targets this unique
module and loads Cortxt's CLI implementation from its distribution path.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _implementation():
    path = Path(__file__).resolve().parent / "cli" / "unified_cli.py"
    spec = importlib.util.spec_from_file_location("_cortxt_unified_cli", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load Cortxt CLI from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main(argv: list[str] | None = None) -> int:
    return _implementation().main(argv)
