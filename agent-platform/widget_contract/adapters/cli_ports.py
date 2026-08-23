"""Injected CLI port with no widget-supplied command text."""

from pathlib import Path
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


def gh_claim_run_resume(issue_id: str, *, registry: Path, scripts_dir: Path) -> dict[str, Any]:
    """Resume a ready issue through the execution-map-gated launcher (gh-backed default).

    Loads `work_launcher` from the platform scripts directory and resumes through
    `default_launcher(registry).resume`; the execution-map gate enforces a fresh
    receipt and durable claim before any launch side effect, and raises a stable
    `ExecutionGateError` code on rejection. This is the default injected resume
    port shared by the CLI and the loopback action host; tests inject fakes.
    """
    import sys
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    from work_launcher import default_launcher
    launcher = default_launcher(registry)
    return launcher.resume(issue_id, runtime="hermes-coordinator", worker_role="builder",
                           workflow="work-launcher/v1", max_runtime_seconds=3600,
                           prompt=f"Execute the approved dispatch request for {issue_id} per the issue body.")
