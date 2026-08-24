"""Tool registry, tier gating, and thin-wrapper handlers for the Cortxt MCP
server (`cortxt mcp serve`).

Deliberately transport-agnostic: nothing here imports the `mcp` SDK or does
any stdio I/O, so it's testable without either (see `cortxt_mcp.protocol` for the
stdio shim that calls into `call_tool`).

Tiers (locked decision, issue #184 step 3 / #187 plan):
  Tier 0 (read-only, default-on): route_engine, list_engine_manifests,
    cortxt_status, cortxt_sessions, cortxt_runtimes, cortxt_orchestrator,
    cortxt_pipeline.
  Tier 1 (`--allow-dispatch`): cortxt_dispatch, cortxt_addons_submit,
    cortxt_daemon_status (`cortxt daemon status`).
  Tier 2 (`--allow-credentials`): scaffolding only -- no credential tools
    exist yet, so nothing is registered at this tier today.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from . import run_lifecycle

TIER_READ_ONLY = 0
TIER_DISPATCH = 1
TIER_CREDENTIALS = 2


class ToolNotFoundError(LookupError):
    """Raised for a `tools/call` naming a tool that isn't registered at all."""


class ToolTierLockedError(PermissionError):
    """Raised for a `tools/call` naming a real tool the server wasn't
    started with the tier flag for."""

    def __init__(self, tool: str, tier: int) -> None:
        self.tool = tool
        self.tier = tier
        super().__init__(
            f"tool {tool!r} requires tier {tier}, which this server was not started with"
        )


class MandateRejectedError(PermissionError):
    """Raised for a `tools/call` naming a TIER_DISPATCH+ tool whose
    mandate envelope (or lack of one) failed verification. Distinct from
    `ToolTierLockedError` so the two failure modes are distinguishable in
    logs and in `protocol.py`'s error mapping (ADR-032)."""

    def __init__(self, tool: str, reason: str) -> None:
        self.tool = tool
        self.reason = reason
        super().__init__(f"mandate rejected for tool {tool!r}: {reason}")


def _ns(**kwargs: Any) -> argparse.Namespace:
    return argparse.Namespace(**kwargs)


def _path(value: Any) -> Path | None:
    return Path(value) if value else None


# --- Tier 0: read-only ------------------------------------------------------

def _tool_route_engine(arguments: dict[str, Any]) -> dict[str, Any]:
    """Wraps routing.engine_manifest.route() against DEFAULT_MANIFESTS.
    Not wrapped in ResultEnvelope -- route() doesn't return one."""
    from routing.engine_manifest import DEFAULT_MANIFESTS, route

    task_tags = arguments.get("task_tags")
    if not task_tags:
        raise ValueError("task_tags is required and must be a non-empty list of strings")
    fallback = arguments.get("fallback", "claude-direct")
    choice = route(list(task_tags), DEFAULT_MANIFESTS, fallback=fallback)
    return {
        "engine_id": choice.engine_id,
        "reason": choice.reason,
        "matched_tag": choice.matched_tag,
        "excluded": [list(pair) for pair in choice.excluded],
        "checkpoint_required": choice.checkpoint_required,
    }


def _tool_list_engine_manifests(arguments: dict[str, Any]) -> list[dict[str, Any]]:
    """Wraps the DEFAULT_MANIFESTS export as a list of plain dicts."""
    from routing.engine_manifest import DEFAULT_MANIFESTS

    return [
        {
            "engine_id": m.engine_id,
            "task_shapes": list(m.task_shapes),
            "cost_class": m.cost_class,
            "reliability_class": m.reliability_class,
            "notes": m.notes,
            "checkpoint_required": m.checkpoint_required,
        }
        for m in DEFAULT_MANIFESTS
    ]


def _tool_cortxt_status(arguments: dict[str, Any]) -> dict[str, Any]:
    from cli.unified_cli import _run_status

    args = _ns(
        store=_path(arguments.get("store")),
        snapshot=_path(arguments.get("snapshot")),
        stale_after=float(arguments.get("stale_after", 300.0)),
    )
    return _run_status(args).to_dict()


def _tool_cortxt_sessions(arguments: dict[str, Any]) -> dict[str, Any]:
    from cli.unified_cli import _run_sessions

    args = _ns(store=_path(arguments.get("store")), snapshot=_path(arguments.get("snapshot")))
    return _run_sessions(args).to_dict()


def _tool_cortxt_runtimes(arguments: dict[str, Any]) -> dict[str, Any]:
    from cli.unified_cli import _run_runtimes

    args = _ns(store=_path(arguments.get("store")), snapshot=_path(arguments.get("snapshot")))
    return _run_runtimes(args).to_dict()


def _tool_cortxt_orchestrator(arguments: dict[str, Any]) -> dict[str, Any]:
    """Overview only. `orchestrator chat` is a conversational stdin loop --
    it has no meaning as a single MCP tool call, so it is never reachable
    here regardless of what a caller passes."""
    from cli.unified_cli import _run_orchestrator

    args = _ns(
        orchestrator_command="overview",
        store=_path(arguments.get("store")),
        snapshot=_path(arguments.get("snapshot")),
        stale_after=float(arguments.get("stale_after", 300.0)),
    )
    return _run_orchestrator(args).to_dict()


def _tool_cortxt_pipeline(arguments: dict[str, Any]) -> dict[str, Any]:
    """One frame only -- `--watch` redraws until Ctrl+C, which has no
    meaning over a single MCP tool call/response, so it is never exposed
    here (locked decision: "NO --watch")."""
    from cli.unified_cli import _run_pipeline

    args = _ns(
        store=_path(arguments.get("store")),
        snapshot=_path(arguments.get("snapshot")),
        stale_after=float(arguments.get("stale_after", 300.0)),
        watch=False,
        interval=2.0,
    )
    return _run_pipeline(args).to_dict()


# --- Tier 1: --allow-dispatch ------------------------------------------------

def _tool_cortxt_dispatch(arguments: dict[str, Any]) -> dict[str, Any]:
    from cli.unified_cli import _run_dispatch

    args = _ns(
        tags=arguments["tags"],
        task_id=arguments["task_id"],
        prompt=arguments["prompt"],
        store=_path(arguments.get("store")),
        snapshot=_path(arguments.get("snapshot")),
        hermes_profile=arguments.get("hermes_profile"),
        timeout=int(arguments.get("timeout", 120)),
        model=arguments.get("model"),
        provider=arguments.get("provider"),
        workstream_id=arguments.get("workstream_id"),
        run_id=arguments.get("run_id"),
        issue_id=arguments.get("issue_id"),
        branch=arguments.get("branch"),
        worktree=arguments.get("worktree"),
    )
    return _run_dispatch(args).to_dict()


def _tool_cortxt_addons_submit(arguments: dict[str, Any]) -> dict[str, Any]:
    from cli.unified_cli import _run_addons

    args = _ns(
        candidate_id=arguments["candidate_id"],
        codex_security_passed=bool(arguments.get("codex_security_passed", False)),
        incomplete=bool(arguments.get("incomplete", False)),
        store=_path(arguments.get("store")),
        snapshot=_path(arguments.get("snapshot")),
    )
    return _run_addons(args).to_dict()


def _tool_cortxt_daemon_status(arguments: dict[str, Any]) -> dict[str, Any]:
    from cli.unified_cli import _run_daemon

    snapshot = arguments.get("snapshot")
    if not snapshot:
        raise ValueError("snapshot is required")
    args = _ns(daemon_command="status", snapshot=snapshot)
    return _run_daemon(args).to_dict()


def _tool_cortxt_widget_generate(arguments: dict[str, Any]) -> dict[str, Any]:
    from cli.unified_cli import _run_widget_generate

    try:
        args = _ns(
            prompt=arguments["prompt"],
            confirm=bool(arguments.get("confirm", False)),
            specs_dir=_path(arguments.get("specs_dir")),
        )
        return _run_widget_generate(args).to_dict()
    except Exception as exc:
        return {"status": "failed", "error": {"category": "runtime_error", "message": str(exc)}}


def _tool_cortxt_widget_edit(arguments: dict[str, Any]) -> dict[str, Any]:
    from cli.unified_cli import _run_widget_edit

    try:
        args = _ns(
            widget_id=arguments["widget_id"],
            widget_version=arguments["widget_version"],
            prompt=arguments["prompt"],
            confirm=bool(arguments.get("confirm", False)),
            specs_dir=_path(arguments.get("specs_dir")),
        )
        return _run_widget_edit(args).to_dict()
    except Exception as exc:
        return {"status": "failed", "error": {"category": "runtime_error", "message": str(exc)}}


def _tool_cortxt_widget_remove(arguments: dict[str, Any]) -> dict[str, Any]:
    from cli.unified_cli import _run_widget_remove

    try:
        args = _ns(
            widget_id=arguments["widget_id"],
            widget_version=arguments["widget_version"],
            specs_dir=_path(arguments.get("specs_dir")),
            confirm=bool(arguments.get("confirm", False)),
        )
        return _run_widget_remove(args).to_dict()
    except Exception as exc:
        return {"status": "failed", "error": {"category": "runtime_error", "message": str(exc)}}


def _tool_cortxt_widget_reset(arguments: dict[str, Any]) -> dict[str, Any]:
    from cli.unified_cli import _run_widget_reset

    try:
        args = _ns(
            specs_dir=_path(arguments.get("specs_dir")),
            confirm=bool(arguments.get("confirm", False)),
        )
        return _run_widget_reset(args).to_dict()
    except Exception as exc:
        return {"status": "failed", "error": {"category": "runtime_error", "message": str(exc)}}


def _tool_cortxt_run_create(arguments: dict[str, Any], *, mandate_binding: dict, lifecycle: Any) -> dict[str, Any]:
    return lifecycle.create_run(arguments, mandate_binding)


def _tool_cortxt_run_resume(arguments: dict[str, Any], *, mandate_binding: dict, lifecycle: Any) -> dict[str, Any]:
    return lifecycle.resume_run(arguments, mandate_binding)


def _tool_cortxt_run_submit_for_review(arguments: dict[str, Any], *, mandate_binding: dict, lifecycle: Any) -> dict[str, Any]:
    return lifecycle.submit_for_review(arguments, mandate_binding)


def _tool_cortxt_run_status(arguments: dict[str, Any], *, lifecycle: Any) -> dict[str, Any]:
    return lifecycle.status_of(arguments["run_id"], arguments.get("issue_ref"))


@dataclass(frozen=True)
class ToolSpec:
    name: str
    tier: int
    description: str
    handler: Callable[[dict[str, Any]], Any]
    mandate_binding: bool = False
    input_schema: dict[str, Any] | None = None
    lifecycle_required: bool = False


_SPECS = (
    ToolSpec(
        "route_engine", TIER_READ_ONLY,
        "Route task tags to an engine via routing.engine_manifest.route() "
        "against DEFAULT_MANIFESTS. Returns an EngineChoice, not a ResultEnvelope.",
        _tool_route_engine,
    ),
    ToolSpec(
        "list_engine_manifests", TIER_READ_ONLY,
        "List the DEFAULT_MANIFESTS engine capability manifests.",
        _tool_list_engine_manifests,
    ),
    ToolSpec(
        "cortxt_status", TIER_READ_ONLY,
        "Table/ledger view of current agent and pipeline state (ResultEnvelope).",
        _tool_cortxt_status,
    ),
    ToolSpec(
        "cortxt_sessions", TIER_READ_ONLY,
        "List real session state, write the widget snapshot (ResultEnvelope).",
        _tool_cortxt_sessions,
    ),
    ToolSpec(
        "cortxt_runtimes", TIER_READ_ONLY,
        "List known agent runtimes and whether each is on PATH (ResultEnvelope).",
        _tool_cortxt_runtimes,
    ),
    ToolSpec(
        "cortxt_orchestrator", TIER_READ_ONLY,
        "Operator overview projection (read-only; chat mode is not exposed over MCP) (ResultEnvelope).",
        _tool_cortxt_orchestrator,
    ),
    ToolSpec(
        "cortxt_pipeline", TIER_READ_ONLY,
        "One live-progress frame (--watch is not exposed over MCP) (ResultEnvelope).",
        _tool_cortxt_pipeline,
    ),
    ToolSpec("cortxt_run_status", TIER_READ_ONLY,
             "Read the durable state of a run (dispatch-contract envelope).",
             _tool_cortxt_run_status, False, run_lifecycle.STATUS_SCHEMA, True),
    ToolSpec(
        "cortxt_dispatch", TIER_DISPATCH,
        "LEGACY single-call execution path (kept for compatibility during the "
        "lifecycle transition; new launchers use cortxt_run_create/resume/review). "
        "Route a tagged task to an engine and invoke it (ResultEnvelope).",
        _tool_cortxt_dispatch,
    ),
    ToolSpec(
        "cortxt_addons_submit", TIER_DISPATCH,
        "Submit one candidate through the addon review gate (ResultEnvelope).",
        _tool_cortxt_addons_submit,
    ),
    ToolSpec(
        "cortxt_daemon_status", TIER_DISPATCH,
        "Print the daemon section of the widget snapshot (ResultEnvelope).",
        _tool_cortxt_daemon_status,
    ),
    ToolSpec(
        "cortxt_widget_generate", TIER_DISPATCH,
        "Generate a widget spec by prompt through the strict ADR-038 loader; "
        "preview-only unless confirm=true (ResultEnvelope).",
        _tool_cortxt_widget_generate,
    ),
    ToolSpec(
        "cortxt_widget_edit", TIER_DISPATCH,
        "Edit an installed widget spec by prompt through the strict ADR-038 "
        "loader; preview-only unless confirm=true (ResultEnvelope).",
        _tool_cortxt_widget_edit,
    ),
    ToolSpec(
        "cortxt_widget_remove", TIER_DISPATCH,
        "Remove one installed widget spec (ResultEnvelope).",
        _tool_cortxt_widget_remove,
    ),
    ToolSpec(
        "cortxt_widget_reset", TIER_DISPATCH,
        "Remove all installed widget specs (ResultEnvelope).",
        _tool_cortxt_widget_reset,
    ),
    ToolSpec("cortxt_run_create", TIER_DISPATCH,
             "Create a durable mandate-bound run and invoke its engine broker "
             "synchronously (dispatch-contract envelope).",
             _tool_cortxt_run_create, True,
             run_lifecycle.CREATE_SCHEMA, True),
    ToolSpec("cortxt_run_resume", TIER_DISPATCH,
             "Resume a durable run through its stored engine broker with its "
             "stored opaque session id (dispatch-contract envelope).",
             _tool_cortxt_run_resume, True,
             run_lifecycle.RESUME_SCHEMA, True),
    ToolSpec("cortxt_run_submit_for_review", TIER_DISPATCH,
             "Submit a terminal run result for independent review (local "
             "review record; no GitHub transition) (dispatch-contract envelope).",
             _tool_cortxt_run_submit_for_review, True,
             run_lifecycle.REVIEW_SCHEMA, True),
)

TOOL_REGISTRY: dict[str, ToolSpec] = {spec.name: spec for spec in _SPECS}


def unlocked_tiers(*, allow_dispatch: bool, allow_credentials: bool) -> set[int]:
    tiers = {TIER_READ_ONLY}
    if allow_dispatch:
        tiers.add(TIER_DISPATCH)
    if allow_credentials:
        tiers.add(TIER_CREDENTIALS)
    return tiers


def list_tools(*, allow_dispatch: bool, allow_credentials: bool) -> list[ToolSpec]:
    """Tools unlocked for the current server tier flags -- what `tools/list`
    advertises. A locked tool is not merely rejected on call, it's absent
    from discovery entirely."""
    tiers = unlocked_tiers(allow_dispatch=allow_dispatch, allow_credentials=allow_credentials)
    return [spec for spec in TOOL_REGISTRY.values() if spec.tier in tiers]


def call_tool(
    name: str,
    arguments: dict[str, Any] | None,
    *,
    allow_dispatch: bool,
    allow_credentials: bool,
    mandate: dict[str, Any] | None = None,
    mandate_verifier: Any = None,
    call_context: Any = None,
    lifecycle: Any = None,
) -> Any:
    """Invoke one registered tool.

    `mandate`/`mandate_verifier`/`call_context` are only consulted for
    tools at TIER_DISPATCH or above (ADR-032); Tier-0 tools ignore all
    three and run exactly as before. `mandate_verifier` defaults to a
    fail-closed `mandate.MandateVerifier.unconfigured()` (no registered
    public keys -> every envelope, including none at all, is rejected)
    when not supplied -- callers that don't wire mandate verification in
    get "Tier-1+ is unusable" rather than "Tier-1+ is unchecked."

    `lifecycle` is a `run_lifecycle.RunLifecycleService` required by the
    three run-lifecycle tools (`spec.lifecycle_required`); it is passed
    through to their handlers so the engine broker, store path, and clock
    stay injectable (AC11). A call to a lifecycle-required tool without a
    service is rejected before the handler runs (fail closed), mirroring
    the unconfigured-mandate-verifier posture.
    """
    if name not in TOOL_REGISTRY:
        raise ToolNotFoundError(name)
    spec = TOOL_REGISTRY[name]
    tiers = unlocked_tiers(allow_dispatch=allow_dispatch, allow_credentials=allow_credentials)
    if spec.tier not in tiers:
        raise ToolTierLockedError(name, spec.tier)
    if spec.lifecycle_required and lifecycle is None:
        raise RuntimeError(
            f"tool {name!r} requires a lifecycle service (RunLifecycleService) that was not supplied"
        )
    if spec.tier >= TIER_DISPATCH:
        from . import mandate as mandate_module

        verifier = mandate_verifier if mandate_verifier is not None else mandate_module.MandateVerifier.unconfigured()
        if spec.lifecycle_required:
            # Authoritative call context (AC3): derived from validated
            # arguments and durable state via the lifecycle service --
            # never from a client-supplied `mandate_context`. Building it
            # here, inside call_tool and before verification, means every
            # caller (protocol shim, future SDK/REST facade) inherits the
            # same strict-schema validation and the same issue/scope
            # binding, and a missing service fails closed before anything
            # runs.
            context = lifecycle.build_call_context(name, arguments or {})
        else:
            context = call_context if call_context is not None else mandate_module.CallContext()
        decision = verifier.verify(mandate, tool=name, tier=spec.tier, call_context=context)
        if not decision.accepted:
            raise MandateRejectedError(name, decision.reason)
        if spec.mandate_binding:
            binding = {key: mandate.get(key) for key in (
                "mandate_id", "granted_by", "issue_ref", "scope_fingerprint",
                "budget_usd_max", "max_runtime_seconds", "data_class_max"
            )}
            if spec.lifecycle_required:
                return spec.handler(arguments or {}, mandate_binding=binding, lifecycle=lifecycle)
            return spec.handler(arguments or {}, mandate_binding=binding)
    if spec.lifecycle_required:
        lifecycle.build_call_context(name, arguments or {})
        return spec.handler(arguments or {}, lifecycle=lifecycle)
    return spec.handler(arguments or {})
