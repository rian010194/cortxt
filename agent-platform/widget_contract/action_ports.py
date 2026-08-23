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
from .adapters.github_ports import mark_ready_transition
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
                              transition_writer: Callable[[str], Mapping[str, Any]]) -> Callable[[str, Mapping[str, Any]], Any]:
    """github-transition port adapter performing exactly the inbox -> ready swap.

    `labels_reader(issue_id)` and `transition_writer(issue_id)` are the
    platform gh-backed ports (injectable for tests); the writer is adapted to
    the `mark_ready_transition` (operation, request) contract.
    """
    def adapter(operation: str, request: Mapping[str, Any]) -> Any:
        def reader(issue_id: str) -> Mapping[str, Any]:
            return {"issue_id": issue_id, "labels": [{"name": x} for x in labels_reader(issue_id)]}

        def writer(operation: str, request: Mapping[str, Any]) -> Any:
            return transition_writer(request["issue_id"])

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
                   resume: Callable[[str], Any]) -> tuple[ActionExecutor, ActionContext]:
    """Assemble the shared executor + per-action context for one execution.

    The approve/confirm semantics and the adapter set are identical to what
    `cortxt widget action` uses; callers only differ in where the injected
    GitHub/launcher ports come from (CLI defaults vs. the host's defaults).
    """
    declared = declared_action(widget, action_id)
    executor = ActionExecutor(
        {"github-transition": github_transition_adapter(labels_reader, transition_writer),
         "cli": cli_claim_adapter(resume)},
        operator_authorize(confirm),
    )
    context = ActionContext(approval_ref, frozenset({declared.operation}))
    return executor, context
