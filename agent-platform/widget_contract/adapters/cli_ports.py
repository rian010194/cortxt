"""Injected CLI port with no widget-supplied command text."""

from typing import Any, Callable, Mapping


def registered_cli(call: Callable[[str, Mapping[str, Any]], Any], operation: str, request: Mapping[str, Any]) -> Any:
    return call(operation, dict(request))


class ClaimRunDenied(RuntimeError):
    kind = "claim_run_denied"


def claim_run_via_launcher(operation: str, request: Mapping[str, Any], *,
                           resume: Callable[..., Any]) -> dict[str, Any]:
    """Route a claim/run request through the registered `cortxt work resume` surface.

    The injected `resume` callable is the WorkLauncher.resume entry point (or a
    test fake): it enforces the execution-map gate (fresh receipt + durable
    claim) before any claim, branch, worktree, label, adapter, or engine effect,
    and raises `ExecutionGateError` with a stable code on rejection. Widget and
    contract code expose no direct `Dispatcher.claim` path — the only reachable
    surface here is the injected launcher.
    """
    issue_id = request["issue_id"]
    if not isinstance(issue_id, str) or not issue_id:
        raise ClaimRunDenied("issue_id is required")
    result = resume(issue_id)
    if not isinstance(result, dict):
        raise ClaimRunDenied("launcher result must be an object")
    return result
