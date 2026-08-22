"""MCP server entry point: `cortxt mcp serve`.

Tries the official `mcp` Python SDK's stdio server first; falls back to the
JSON-RPC 2.0 shim in `cortxt_mcp.protocol` when the SDK isn't usable in-process.
See `_try_import_sdk`'s docstring for the SDK-vs-shim selection, and the top
of this module's package docstring (`cortxt_mcp/__init__.py`) for the
tiering/audit decisions this wires together.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Public-key delivery mechanism (ADR-032, operator-approved as an
# implementation choice): an explicit env var, mirroring how
# `--allow-dispatch`/`--allow-credentials` are already explicit startup
# flags. Never a private key -- Ed25519 public keys are not secret by
# construction. Value is nested: {"granted_by-id": {"kid": "hex-pubkey"}}.
MANDATE_PUBLIC_KEYS_ENV = "CORTXT_MCP_MANDATE_PUBLIC_KEYS"
# Directory for the durable nonce-replay and cumulative-budget stores
# (ADR-032 / nonce_store.py). Defaults alongside the session_state store.
MANDATE_STATE_DIR_ENV = "CORTXT_MCP_MANDATE_STATE_DIR"


def _build_mandate_verifier_from_env(agent_platform_dir: Path) -> Any:
    """Builds a `mandate.MandateVerifier` from environment configuration
    only -- this module never imports `security.credential_broker` or
    references the mandate-signing private-key credential id (AC 8): it
    only ever handles the public key, which is not secret."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    from .mandate import MandateVerifier
    from .nonce_store import BudgetStore, NonceStore
    from .revocation_store import KeyRevocationStore

    class _DuplicateKey(ValueError):
        pass

    def _object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise _DuplicateKey(key)
            result[key] = value
        return result

    raw_keys = os.environ.get(MANDATE_PUBLIC_KEYS_ENV, "")
    public_keys: dict[str, dict[str, str]] = {}
    if raw_keys:
        try:
            parsed = json.loads(raw_keys, object_pairs_hook=_object)
            if not isinstance(parsed, dict) or not parsed:
                raise ValueError("keyring must be a non-empty object")
            for granted_by, keys in parsed.items():
                if not isinstance(granted_by, str) or not granted_by or not isinstance(keys, dict) or not keys:
                    raise ValueError("invalid issuer keyring")
                public_keys[granted_by] = {}
                for kid, material in keys.items():
                    if not isinstance(kid, str) or not kid or not isinstance(material, str):
                        raise ValueError("invalid key entry")
                    Ed25519PublicKey.from_public_bytes(bytes.fromhex(material))
                    public_keys[granted_by][kid] = material
        except Exception as error:
            logger.warning("%s is invalid; mandate verification is unconfigured: %s",
                           MANDATE_PUBLIC_KEYS_ENV, error)
            return MandateVerifier.unconfigured()

    state_dir = Path(os.environ.get(MANDATE_STATE_DIR_ENV, str(agent_platform_dir / ".mandate")))
    revocation_store = KeyRevocationStore(state_dir / "revocations.json")
    if not public_keys or not revocation_store.configured:
        return MandateVerifier.unconfigured()
    return MandateVerifier(
        public_keys=public_keys,
        nonce_store=NonceStore(state_dir / "used_nonces.json"),
        budget_store=BudgetStore(state_dir / "budget_spent.json"),
        revocation_store=revocation_store,
    )


def _try_import_sdk():
    """Best-effort import of the official `mcp` Python SDK's low-level
    server, stdio transport, and types modules.

    This repo's own package used to be *also* named `mcp`
    (`agent-platform/mcp/`, per the approved #187 plan / issue #184 step 3
    decisions), which collided with the pip-installed `mcp` SDK package the
    moment this module ran: it was itself loaded as `mcp.server`, so
    `sys.modules["mcp"]` was already bound to *this* package by the time this
    function executed, and `import mcp.server.lowlevel` resolved against this
    package's own flat-file `server` module (no `lowlevel` submodule) instead
    of the SDK's. That collision was resolved by renaming the package to
    `cortxt_mcp` (PR #203 / issue #202), so the imports below now resolve
    against the real SDK when it is installed.

    A failure here -- the SDK genuinely not being installed -- is treated as
    expected and handled: `serve()` falls back to `cortxt_mcp.protocol`'s
    stdio shim, which implements the same MCP stdio wire protocol without
    depending on the SDK package at all. This is the "thin stdio JSON-RPC 2.0
    shim as a documented fallback" the step-3 brief anticipates.
    """
    try:
        import importlib

        lowlevel = importlib.import_module("mcp.server.lowlevel")
        stdio = importlib.import_module("mcp.server.stdio")
        types_mod = importlib.import_module("mcp.types")
        return lowlevel, stdio, types_mod
    except Exception as error:
        logger.info("official mcp SDK not usable in-process (%s); using the stdio shim", error)
        return None


def serve(
    *,
    allow_dispatch: bool = False,
    allow_credentials: bool = False,
    store: Path | None = None,
    mandate_verifier: Any = None,
    lifecycle: Any = None,
) -> None:
    """Entry point for `cortxt mcp serve`. Blocks on stdio until the client
    disconnects (EOF on stdin), same foreground-blocking shape as
    `cortxt widget`.

    Tier 0 (read-only) tools are always on. `allow_dispatch` unlocks Tier 1
    (`cortxt_dispatch`, `cortxt_addons_submit`, `cortxt_daemon_status`, and
    the three run-lifecycle tools) -- but per ADR-032, a Tier-1+ call
    additionally requires a valid signed mandate envelope, verified by
    `mandate_verifier`. `allow_credentials` unlocks Tier 2 -- scaffolding
    only today, no credential tools are registered yet. `store` is the
    session_state ledger used for audit logging and the run-lifecycle
    store (default: `agent-platform/.sessions`, same default every other
    CLI subcommand uses). `mandate_verifier` defaults to one built from
    environment configuration (`_build_mandate_verifier_from_env`) -- see
    `MANDATE_PUBLIC_KEYS_ENV`/`MANDATE_STATE_DIR_ENV` above; this module
    never holds or references the mandate-signing private key. `lifecycle`
    defaults to a `run_lifecycle.RunLifecycleService` over the same store
    with the default engine context (issue #230 / ADR-034); a caller may
    inject a fake for tests.
    """
    from .audit import AuditLog

    agent_platform_dir = Path(__file__).resolve().parent.parent
    store = store or (agent_platform_dir / ".sessions")
    audit = AuditLog(store)
    if mandate_verifier is None:
        mandate_verifier = _build_mandate_verifier_from_env(agent_platform_dir)
    if lifecycle is None:
        from .run_lifecycle import RunLifecycleService

        lifecycle = RunLifecycleService.with_defaults()
        # The default service store is agent-platform/.sessions; align it
        # with the explicit `store` parameter when one was supplied.
        if store != agent_platform_dir / ".sessions":
            lifecycle.store = store

    sdk = _try_import_sdk()
    if sdk is not None:
        # Reserved for a real SDK integration: the rename (PR #203 / issue
        # #202) resolved the import collision, so this branch is now
        # reachable when the SDK is installed, but wiring the SDK's stdio
        # server in is a separate follow-up -- deliberately not implemented
        # against code paths this environment could not execute to verify.
        logger.warning("official mcp SDK detected but not wired up in this build; using the stdio shim instead")

    from .protocol import serve_stdio

    serve_stdio(
        allow_dispatch=allow_dispatch, allow_credentials=allow_credentials, audit=audit,
        mandate_verifier=mandate_verifier, lifecycle=lifecycle,
    )
