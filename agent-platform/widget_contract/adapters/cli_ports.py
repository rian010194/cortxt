"""Injected CLI port with no widget-supplied command text."""

from pathlib import Path
from typing import Any, Callable, Mapping


def registered_cli(call: Callable[[str, Mapping[str, Any]], Any], operation: str, request: Mapping[str, Any]) -> Any:
    return call(operation, dict(request))


class ClaimRunDenied(RuntimeError):
    kind = "claim_run_denied"


class DispatchNotEligible(ClaimRunDenied):
    """The dispatch request is not eligible; carries the structured failures."""

    def __init__(self, request: Mapping[str, Any]) -> None:
        self.missing = list(request.get("missing") or [])
        self.errors = list(request.get("errors") or [])
        super().__init__("dispatch request is not eligible; missing: " + ", ".join(self.missing))


class ApprovalMismatch(ClaimRunDenied):
    """The provided approval reference does not match the issue-derived one."""


class StaleDispatchRequest(ClaimRunDenied):
    """The confirmed request snapshot no longer matches the current Issue."""


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


def gh_claim_run_resume(issue_id: str, *, registry: Path, scripts_dir: Path,
                        issue_reader: Callable[[str, int], Mapping[str, Any]] | None = None,
                        manifests: Any = None,
                        engine_has_provider: Callable[[str], bool] | None = None,
                        launcher: Any = None,
                        approval_ref: str | None = None,
                        request_id: str | None = None) -> dict[str, Any]:
    """Resume a ready issue through the execution-map-gated launcher (gh-backed default).

    S7b (#471): the launcher values (runtime, worker role, workflow, every
    dispatch limit, artifact policy) are resolved from the approved Issue
    dispatch projection, never hard-coded. The execution-map gate still enforces
    a fresh receipt and durable claim before any launch side effect, and raises
    a stable `ExecutionGateError` code on rejection.

    Isolation is part of that projection too: `request["isolation"]` decides
    whether the run gets its own linked worktree and `work/<run_id>` branch.
    It defaults closed (isolated) and is waived only by an approved artifact
    policy that explicitly says the run works in the shared checkout.

    Approval binding (AC8): when `approval_ref` is provided it must equal the
    issue-derived approval reference, and when `request_id` is provided it must
    equal the server-derived digest of the current request snapshot -- a changed
    Issue between preview and confirmation is rejected as stale, never silently
    launched as a different mandate. A not-eligible dispatch request raises
    `DispatchNotEligible` with the structured failures, so the browser cannot
    widen scope or limits.
    """
    import sys
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    from work_launcher import default_launcher

    from .github_ports import read_issue_detail as _read_issue_detail
    from ..dispatch_request import build_dispatch_request_v1, route_for_issue
    from routing.engine_manifest import DEFAULT_FALLBACK_ENGINE, DEFAULT_MANIFESTS

    repo, number = issue_id.rsplit("#", 1)
    reader = issue_reader or (lambda r, n: _read_issue_detail(r, n))
    issue = reader(repo, int(number))

    manifests = manifests if manifests is not None else DEFAULT_MANIFESTS
    choice, tags = route_for_issue(issue, manifests, fallback=DEFAULT_FALLBACK_ENGINE)

    if engine_has_provider is None:
        # Authoritative dispatchability: the WorkLauncher dispatches through
        # scripts.worker_adapters.ADAPTER_REGISTRY AND consults
        # runtime_launch_config_ok before creating any claim, so eligibility
        # here must consult exactly that same stricter function -- not the
        # weaker registry-only is_runtime_dispatchable -- or a runtime with a
        # registered adapter but missing provider/model/auth config would be
        # reported eligible and then rejected only after a claim exists
        # (S7b #482 dogfood defect / follow-on).
        from worker_adapters import runtime_launch_config_ok

        def engine_has_provider(engine_id: str) -> bool:
            return runtime_launch_config_ok(engine_id)

    request = build_dispatch_request_v1(
        issue, choice, repo=repo,
        engine_registered=bool(choice and engine_has_provider(choice.engine_id)),
        routable_tags=tags)
    if not request["eligible"]:
        raise DispatchNotEligible(request)
    if approval_ref is not None and approval_ref != request["approval_reference"]:
        raise ApprovalMismatch("approval reference does not match the approved issue mandate")
    if request_id is not None and request_id != request["request_id"]:
        raise StaleDispatchRequest(
            "dispatch request snapshot has changed; re-fetch and confirm the current request")

    launcher = launcher or default_launcher(registry)
    return launcher.resume(
        issue_id,
        runtime=request["engine"],
        worker_role=request["worker_role"],
        workflow=request["workflow_id"],
        max_runtime_seconds=int(request["max_runtime_seconds"]),
        max_cost_usd=float(request["max_cost_usd"]),
        max_parallel_workers=int(request["max_parallel_workers"]),
        delegation_depth=int(request["delegation_depth"]),
        artifact_policy=request["artifact_policy"],
        request_id=request["request_id"],
        # The isolation decision is the request's, never the caller's: it is
        # derived on the server from the approved artifact policy and covered
        # by `request_id`, so the browser cannot choose whether the worker gets
        # its own worktree (#472 findings 6/8).
        isolate=request["isolation"] == "worktree",
        prompt=f"Execute the approved dispatch request for {issue_id} per the issue body.")
