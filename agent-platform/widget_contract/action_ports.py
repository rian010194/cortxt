"""Shared authorized action wiring for the CLI and the loopback action host (ADR-038).

The widget contract registers inert actions; executing one requires the same
operator-gated assembly wherever it is invoked. This module is that single
assembly: it builds the Action model from a declared widget action, builds the
operator authorize callback, builds the github-transition and cli adapters from
injected GitHub/launcher ports, and assembles the ActionExecutor. Both
`cortxt widget action` (cli/unified_cli.py) and the reviewed browser host
(agent-platform/widget/action_host.py) use exactly this path, so the browser
cannot drift from the CLI's execution or authorization semantics.
"""
from __future__ import annotations

from typing import Any, Callable, Mapping

from .action_executor import ActionContext, ActionExecutor
from .adapters.cli_ports import claim_run_via_launcher
from .adapters.github_ports import (mark_ready_transition, record_decision_transition,
                                    return_to_ready_transition)
from .models import Action, Widget


class UnknownAction(KeyError):
    pass


def declared_action(widget: Widget, action_id: str) -> Action:
    """Resolve one declared widget action by id, or raise UnknownAction."""
    for action in widget.actions:
        if action.id == action_id:
            return action
    raise UnknownAction(action_id)


def build_action(widget: Widget, action_id: str, issue_id: str,
                 approval_ref: str, confirm: bool) -> Action:
    """Build the Action exactly as the CLI does for one authorized execution."""
    declared = declared_action(widget, action_id)
    return Action(declared.id, declared.port, declared.operation, {"issue_id": issue_id},
                  {"mode": declared.authorization["mode"], "reference": approval_ref},
                  declared.confirm, declared.result_type, declared.idempotency_key)


def operator_authorize(confirm: bool) -> Callable[[Action, ActionContext], bool]:
    """The operator gate: matching approval reference + approved operation + confirm."""
    def authorize(action: Action, context: ActionContext) -> bool:
        return (context.authorization_reference == action.authorization.get("reference")
                and action.operation in context.approved_operations
                and (not action.confirm.get("required") or confirm))
    return authorize


def github_transition_adapter(labels_reader: Callable[[str], list[str]],
                              transition_writer: Callable[[str], Mapping[str, Any]],
                              *, review_transition_writer: Callable[[str], Mapping[str, Any]] | None = None,
                              recover_transition_writer: Callable[[str], Mapping[str, Any]] | None = None
                              ) -> Callable[[str, Mapping[str, Any]], Any]:
    """github-transition port adapter, routed by operation.

    `workflow.mark-ready.v1` performs the inbox -> ready swap;
    `workflow.record-decision.v1` performs the review -> done swap;
    `workflow.recover-to-ready.v1` performs the in-progress -> ready recovery
    swap. Each is a separate fixed-effect transition function -- this adapter
    only dispatches on the declared action's operation, it never becomes a
    general label editor.
    """
    def reader(issue_id: str) -> Mapping[str, Any]:
        return {"issue_id": issue_id, "labels": [{"name": x} for x in labels_reader(issue_id)]}

    def writer(operation: str, request: Mapping[str, Any]) -> Any:
        return transition_writer(request["issue_id"])

    def review_writer(operation: str, request: Mapping[str, Any]) -> Any:
        if review_transition_writer is None:
            raise ValueError(
                "github_transition_adapter: workflow.record-decision.v1 requires "
                "review_transition_writer; refusing to fall back to the inbox->ready "
                "transition_writer and mis-edit the issue's labels")
        return review_transition_writer(request["issue_id"])

    def recover_writer(operation: str, request: Mapping[str, Any]) -> Any:
        if recover_transition_writer is None:
            raise ValueError(
                "github_transition_adapter: workflow.recover-to-ready.v1 requires "
                "recover_transition_writer; refusing to fall back to the inbox->ready "
                "transition_writer and mis-edit the issue's labels")
        return recover_transition_writer(request["issue_id"])

    def adapter(operation: str, request: Mapping[str, Any]) -> Any:
        if operation == "workflow.record-decision.v1":
            return record_decision_transition(operation, request, issue_reader=reader, transition=review_writer)
        if operation == "workflow.recover-to-ready.v1":
            return return_to_ready_transition(operation, request, issue_reader=reader, transition=recover_writer)
        return mark_ready_transition(operation, request, issue_reader=reader, transition=writer)
    return adapter


def cli_claim_adapter(resume: Callable[[str], Any]) -> Callable[[str, Mapping[str, Any]], Any]:
    """cli claim/run port adapter routed only through the execution-map-gated launcher."""
    def adapter(operation: str, request: Mapping[str, Any]) -> Any:
        return claim_run_via_launcher(operation, request, resume=resume)
    return adapter


def build_executor(widget: Widget, *, action_id: str, approval_ref: str, confirm: bool,
                   labels_reader: Callable[[str], list[str]],
                   transition_writer: Callable[[str], Mapping[str, Any]],
                   resume: Callable[[str], Any],
                   review_transition_writer: Callable[[str], Mapping[str, Any]] | None = None,
                   recover_transition_writer: Callable[[str], Mapping[str, Any]] | None = None,
                   authoritative_reference: str | None = None
                   ) -> tuple[ActionExecutor, ActionContext]:
    """Assemble the shared executor + per-action context for one execution.

    The approve/confirm semantics and the adapter set are identical to what
    `cortxt widget action` uses; callers only differ in where the injected
    GitHub/launcher ports come from (CLI defaults vs. the host's defaults).

    `authoritative_reference` is the server-derived approval reference (e.g. the
    issue-derived dispatch-request approval). When provided, the ActionContext
    carries it while the Action carries the caller-supplied `approval_ref`, so
    the executor's reference comparison is non-circular: a caller-supplied
    reference that does not match the authoritative one fails closed. When
    omitted (CLI path), both sides keep the caller-supplied value and the
    authoritative check happens in the claim-run adapter itself
    (`gh_claim_run_resume`).

    `review_transition_writer` must be passed by every caller wiring a
    `workflow.record-decision.v1` action, and `recover_transition_writer` by
    every caller wiring a `workflow.recover-to-ready.v1` action: without them,
    `github_transition_adapter` would have to fall back to `transition_writer`
    (the inbox -> ready writer) and silently perform the wrong label edit, so
    it raises instead.
    """
    declared = declared_action(widget, action_id)
    executor = ActionExecutor(
        {"github-transition": github_transition_adapter(
            labels_reader, transition_writer,
            review_transition_writer=review_transition_writer,
            recover_transition_writer=recover_transition_writer),
         "cli": cli_claim_adapter(resume)},
        operator_authorize(confirm),
    )
    context_reference = authoritative_reference if authoritative_reference is not None else approval_ref
    context = ActionContext(context_reference, frozenset({declared.operation}))
    return executor, context
