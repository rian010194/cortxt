"""Unified CLI entry point for Cortxt agent platform.

Chains the 6 existing CLI interfaces with a consistent result envelope,
evidence chain, and resume support.

Commands:
  provider-policy  — Run provider policy evaluation (provider_policy_cli.py)
  state            — State ledger operations (state_cli.py)
  profile          — Profile management (profile_cli.py)
  supervisor       — Supervisor operations (supervisor_cli.py)
  coding           — Coding loop execution (coding_loop_cli.py)
  rlm              — RLM node execution (rlm_child_cli.py)
  sessions         — List real session state, write widget snapshot (status.py)
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class ResultEnvelope:
    """Standard result envelope for all CLI commands."""
    issue_id: str | None = None
    run_id: str | None = None
    status: str = "pending"
    runtime: str = "unified_cli/v0.1"
    worker_role: str = "coordinator"
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    finished_at: str | None = None
    model: str | None = None
    usage: dict[str, int] = field(default_factory=dict)
    cost: float = 0.0
    cost_currency: str = "USD"
    artifacts: list[str] = field(default_factory=list)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    error: dict[str, str] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "issue_id": self.issue_id,
            "run_id": self.run_id,
            "status": self.status,
            "runtime": self.runtime,
            "worker_role": self.worker_role,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "model": self.model,
            "usage": self.usage,
            "cost": self.cost,
            "cost_currency": self.cost_currency,
            "artifacts": self.artifacts,
            "evidence": self.evidence,
            "error": self.error,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, default=str)


def _get_agent_platform_path() -> Path:
    """Get the agent-platform directory path for dynamic imports."""
    return Path(__file__).parent.parent


def _run_provider_policy(args: argparse.Namespace) -> ResultEnvelope:
    """Run provider policy evaluation."""
    try:
        ap_path = _get_agent_platform_path()
        inference_path = ap_path / "inference"
        import sys
        if str(inference_path) not in sys.path:
            sys.path.insert(0, str(inference_path))
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "provider_policy_cli", inference_path / "provider_policy_cli.py"
        )
        provider_cli = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(provider_cli)
        code = provider_cli.run(args.request)
        return ResultEnvelope(status="succeeded" if code == 0 else "failed", artifacts=[f"provider_policy:{args.request}"])
    except Exception as e:
        return ResultEnvelope(status="failed", error={"category": "runtime_error", "message": str(e)})


def _run_state(args: argparse.Namespace) -> ResultEnvelope:
    """Run state ledger operations."""
    try:
        ap_path = _get_agent_platform_path()
        state_path = ap_path / "state"
        import sys
        if str(state_path) not in sys.path:
            sys.path.insert(0, str(state_path))
        # Import and call state_cli.main()
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "state_cli", state_path / "state_cli.py"
        )
        state_cli = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(state_cli)

        argv = []
        if args.command == "create":
            argv = [
                "create",
                "--store", str(args.store),
                "--task-id", args.task_id,
                "--data-class", args.data_class,
                "--workflow", args.workflow,
                "--max-cost-usd", str(args.max_cost_usd),
                "--provider-evidence-file", args.provider_evidence_file,
            ]
        elif args.command == "append":
            argv = [
                "append",
                "--store", str(args.store),
                "--run-id", args.run_id,
                "--expected-sequence", str(args.expected_sequence),
                "--event-type", args.event_type,
                "--payload-file", args.payload_file,
            ]
        elif args.command == "show":
            argv = ["show", "--store", str(args.store), "--run-id", args.run_id]

        code = state_cli.main(argv)
        return ResultEnvelope(status="succeeded" if code == 0 else "failed", artifacts=[f"state:{args.command}"])
    except Exception as e:
        return ResultEnvelope(status="failed", error={"category": "runtime_error", "message": str(e)})


def _run_profile(args: argparse.Namespace) -> ResultEnvelope:
    """Run profile management operations."""
    try:
        import subprocess
        import shutil
        python_exe = shutil.which("python") or sys.executable
        profile_cli_path = Path(__file__).parent.parent.parent / "scripts" / "profile_cli.py"
        argv = [python_exe, str(profile_cli_path), args.command]
        if hasattr(args, 'name') and args.name:
            argv.append(args.name)
        if hasattr(args, 'json') and args.json:
            argv.append("--json")

        result = subprocess.run(argv, capture_output=True, text=True, cwd=Path(__file__).parent.parent)
        if result.returncode == 0:
            return ResultEnvelope(status="succeeded", artifacts=[f"profile:{args.command}"], evidence=[{"stdout": result.stdout}])
        else:
            return ResultEnvelope(status="failed", error={"category": "cli_error", "message": result.stderr or f"exit code {result.returncode}"})
    except Exception as e:
        return ResultEnvelope(status="failed", error={"category": "runtime_error", "message": str(e)})


def _run_supervisor(args: argparse.Namespace) -> ResultEnvelope:
    """Run supervisor operations."""
    try:
        ap_path = _get_agent_platform_path()
        import sys
        if str(ap_path) not in sys.path:
            sys.path.insert(0, str(ap_path))
        from supervisor.supervisor_cli import main as supervisor_main
        argv = []
        if args.command == "status":
            argv = ["status", "--store", str(args.store), "--root-session-id", args.root_session_id]
        elif args.command == "cancel":
            argv = ["cancel", "--store", str(args.store), "--root-session-id", args.root_session_id]

        code = supervisor_main(argv)
        return ResultEnvelope(status="succeeded" if code == 0 else "failed", artifacts=[f"supervisor:{args.command}"])
    except Exception as e:
        return ResultEnvelope(status="failed", error={"category": "runtime_error", "message": str(e)})


def _run_coding(args: argparse.Namespace) -> ResultEnvelope:
    """Run coding loop execution."""
    try:
        ap_path = _get_agent_platform_path()
        import sys
        if str(ap_path) not in sys.path:
            sys.path.insert(0, str(ap_path))
        # Import and call coding_loop_cli.main()
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "coding_loop_cli", ap_path / "runtime" / "coding_loop_cli.py"
        )
        coding_cli = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(coding_cli)

        argv = [
            "--session-id", args.session_id,
            "--store", str(args.store),
            "--config-json", str(args.config_json),
        ]
        code = coding_cli.main(argv)
        return ResultEnvelope(status="succeeded" if code == 0 else "failed", artifacts=[f"coding:{args.session_id}"])
    except Exception as e:
        return ResultEnvelope(status="failed", error={"category": "runtime_error", "message": str(e)})


def _run_rlm(args: argparse.Namespace) -> ResultEnvelope:
    """Run RLM node execution."""
    try:
        ap_path = _get_agent_platform_path()
        import sys
        if str(ap_path) not in sys.path:
            sys.path.insert(0, str(ap_path))
        # Import and call rlm_child_cli.main()
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "rlm_child_cli", ap_path / "runtime" / "rlm_child_cli.py"
        )
        rlm_cli = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(rlm_cli)

        argv = [
            "--session-id", args.session_id,
            "--store", str(args.store),
            "--config-json", str(args.config_json),
            "--context-ref-json", str(args.context_ref_json),
            "--depth", str(args.depth),
        ]
        code = rlm_cli.main(argv)
        return ResultEnvelope(status="succeeded" if code == 0 else "failed", artifacts=[f"rlm:{args.session_id}"])
    except Exception as e:
        return ResultEnvelope(status="failed", error={"category": "runtime_error", "message": str(e)})


def _run_sessions(args: argparse.Namespace) -> ResultEnvelope:
    """List sessions from real session state; write the widget's snapshot.

    Normal import (`cli` sibling module `status.py`, `runtime.session_state`
    underneath it) -- unlike the other subcommands here, there's no reason
    this one needs importlib.util dynamic loading.
    """
    try:
        cli_dir = Path(__file__).parent
        if str(cli_dir) not in sys.path:
            sys.path.insert(0, str(cli_dir))
        import status as status_cli

        store = args.store or (_get_agent_platform_path() / ".sessions")
        snapshot = args.snapshot or (_get_agent_platform_path() / "widget" / "snapshot.json")

        sessions = status_cli.load_sessions(store)
        status_cli.write_snapshot(sessions, snapshot)
        print(status_cli.render_table(sessions))

        return ResultEnvelope(
            status="succeeded",
            artifacts=[f"sessions:{len(sessions)}", f"snapshot:{snapshot}"],
            evidence=[{"sessions": sessions}],
        )
    except Exception as e:
        return ResultEnvelope(status="failed", error={"category": "runtime_error", "message": str(e)})


def _run_widget(args: argparse.Namespace) -> ResultEnvelope:
    """Serve the sessions widget (loopback-only static server, widget/serve.py).

    Blocks in the foreground until interrupted, same shape as any other
    local dev-server CLI command. No new logic here -- this just calls the
    existing, already-tested serve.main().
    """
    try:
        ap_path = _get_agent_platform_path()
        if str(ap_path) not in sys.path:
            sys.path.insert(0, str(ap_path))
        from widget import serve as widget_serve

        widget_serve.main()
        return ResultEnvelope(status="succeeded", artifacts=["widget:stopped"])
    except Exception as e:
        return ResultEnvelope(status="failed", error={"category": "runtime_error", "message": str(e)})


def _run_dispatch(args: argparse.Namespace) -> ResultEnvelope:
    """Orchestrator Dispatch v0.1: route a tagged task to an engine, invoke
    it, and record the outcome in the same session_state Fas 2 already
    tracks. See .hermes/plans/2026-08-19-orchestrator-dispatch-v01.md.

    "claude-direct" has no headless invocation here -- there is no
    confirmed one-shot Claude Code CLI entry point in this repo, and
    guessing one would repeat the exact mistake ADR-022 was written to
    avoid (coding in an assumption nothing verified). Routed-to-claude-direct
    tasks are recorded as "blocked" -- picked up by a human/Claude Code
    session, not auto-executed.
    """
    try:
        ap_path = _get_agent_platform_path()
        if str(ap_path) not in sys.path:
            sys.path.insert(0, str(ap_path))
        from routing import hermes_invoker
        from routing.engine_manifest import DEFAULT_MANIFESTS, route
        from runtime import session_state as state

        tags = [t.strip() for t in args.tags.split(",") if t.strip()]
        choice = route(tags, DEFAULT_MANIFESTS)

        store = args.store or (_get_agent_platform_path() / ".sessions")
        session = state.create(store, task_id=args.task_id)
        session_id = session["session_id"]
    except Exception as e:
        return ResultEnvelope(status="failed", error={"category": "runtime_error", "message": str(e)})

    # From here on, a session exists on disk. Any exception below must
    # still leave it with a terminal event -- otherwise it's stuck showing
    # "running" forever even though the CLI already reported failure
    # (caught by review: a whitespace-only --prompt or a missing hermes
    # binary raised between session creation and the terminal append,
    # orphaning the session).
    try:
        evidence = {
            "engine": choice.engine_id,
            "routing_reason": choice.reason,
            "matched_tag": choice.matched_tag,
            "excluded": list(choice.excluded),
        }

        if choice.engine_id == "hermes":
            result = hermes_invoker.invoke_hermes(
                args.hermes_profile, args.prompt, timeout_seconds=args.timeout,
                model=args.model, provider=args.provider,
            )
            state.append(store, session_id, 0, "session.terminal", {"status": result["status"]})
            evidence["hermes_result"] = {k: v for k, v in result.items() if k != "stdout"}
            status = "succeeded" if result["status"] == "succeeded" else "failed"
        else:
            if choice.engine_id == "claude-direct":
                reason = "routed to claude-direct: pick this up in a Claude Code session"
            else:
                reason = f"routed to {choice.engine_id}: no invoker wired for this engine yet"
            state.append(store, session_id, 0, "session.terminal", {"status": "blocked", "reason": reason})
            status = "succeeded"  # dispatch itself succeeded: routing + recording worked

        return ResultEnvelope(
            status=status,
            artifacts=[f"session:{session_id}", f"engine:{choice.engine_id}"],
            evidence=[evidence],
        )
    except Exception as e:
        state.append(store, session_id, 0, "session.terminal", {"status": "failed", "reason": str(e)})
        return ResultEnvelope(status="failed", error={"category": "runtime_error", "message": str(e)})


def _run_runtimes(args: argparse.Namespace) -> ResultEnvelope:
    """List known agent runtimes and whether each is on PATH (Fas 4 admin surface)."""
    try:
        ap_path = _get_agent_platform_path()
        if str(ap_path) not in sys.path:
            sys.path.insert(0, str(ap_path))
        from routing.discovery import discover_installed_runtimes

        statuses = discover_installed_runtimes()
        print(f"{'RUNTIME':<14} {'INSTALLED':<10} PATH")
        print("-" * 60)
        for s in statuses:
            print(f"{s.runtime_id:<14} {'yes' if s.installed else 'no':<10} {s.path or ''}")

        return ResultEnvelope(
            status="succeeded",
            evidence=[{"runtimes": [
                {"runtime_id": s.runtime_id, "installed": s.installed, "path": s.path} for s in statuses
            ]}],
        )
    except Exception as e:
        return ResultEnvelope(status="failed", error={"category": "runtime_error", "message": str(e)})


def _run_credentials(args: argparse.Namespace) -> ResultEnvelope:
    """Admin surface over security.credential_broker.CredentialBroker (Fas 4).

    `store` reads the secret from stdin, never a CLI argument -- an
    argument would leak into shell history and the process list. `inject`
    prints only the plaintext value to stdout; the envelope's own
    evidence/artifacts never carry it, only the credential_id.
    """
    try:
        ap_path = _get_agent_platform_path()
        if str(ap_path) not in sys.path:
            sys.path.insert(0, str(ap_path))
        from security.credential_broker import CredentialBroker, NotOperatorConfirmedError

        store_dir = args.store_dir or (ap_path / ".credentials")
        broker = CredentialBroker.with_dpapi(store_dir)

        if args.credentials_command == "store":
            if not args.confirm:
                return ResultEnvelope(
                    status="failed",
                    error={"category": "not_confirmed", "message": "pass --confirm to store a credential"},
                )
            value = sys.stdin.read().rstrip("\n")
            broker.store(args.id, value, operator_confirmed=True)
            return ResultEnvelope(status="succeeded", artifacts=[f"credential:{args.id}"])

        # inject
        value = broker.inject(args.id, requesting_runtime=args.runtime, purpose=args.purpose)
        print(value)
        return ResultEnvelope(status="succeeded", artifacts=[f"credential:{args.id}"])
    except NotOperatorConfirmedError as e:
        return ResultEnvelope(status="failed", error={"category": "not_confirmed", "message": str(e)})
    except Exception as e:
        return ResultEnvelope(status="failed", error={"category": "runtime_error", "message": str(e)})


def _run_addons(args: argparse.Namespace) -> ResultEnvelope:
    """Admin surface over learning.addon_review.AddonReviewGate (Fas 5).

    Only the `submit` action: run one candidate through the review gate
    and print the verdict. No addon registry/list here -- none exists yet
    (see .hermes/plans/2026-08-19-orchestrator-dispatch-v01.md); inventing
    one is a separate, larger decision, not CLI plumbing over already-tested code.
    """
    try:
        ap_path = _get_agent_platform_path()
        if str(ap_path) not in sys.path:
            sys.path.insert(0, str(ap_path))
        from learning.addon_review import AddonReviewGate
        from learning.promotion_gate import PromotionGate

        matrix = {
            "complete": not args.incomplete,
            "codex_security_passed": args.codex_security_passed,
        }
        verdict = AddonReviewGate(PromotionGate()).submit(matrix, args.candidate_id)
        print(verdict)

        return ResultEnvelope(
            status="succeeded" if verdict != "REJECT" else "failed",
            evidence=[{"candidate_id": args.candidate_id, "verdict": verdict, "matrix": matrix}],
        )
    except Exception as e:
        return ResultEnvelope(status="failed", error={"category": "runtime_error", "message": str(e)})


def main(argv: list[str] | None = None) -> int:
    """Unified CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Cortxt agent platform unified CLI — chains 6 existing CLIs with result envelope and evidence chain."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # provider-policy subcommand
    policy_parser = sub.add_parser("provider-policy", help="Provider policy evaluation")
    policy_parser.add_argument("--request", default="-", help="JSON file, or - for stdin")
    policy_parser.set_defaults(func=_run_provider_policy)

    # state subcommand
    state_parser = sub.add_parser("state", help="State ledger operations")
    state_parser.add_argument("command", choices=["create", "append", "show"], help="Command")
    state_parser.add_argument("--store", type=Path, help="Store path")
    state_parser.add_argument("--task-id", help="Task ID")
    state_parser.add_argument("--data-class", help="Data class")
    state_parser.add_argument("--workflow", help="Workflow")
    state_parser.add_argument("--max-cost-usd", type=float, help="Max cost USD")
    state_parser.add_argument("--provider-evidence-file", help="Provider evidence file")
    state_parser.add_argument("--run-id", help="Run ID")
    state_parser.add_argument("--expected-sequence", type=int, help="Expected sequence")
    state_parser.add_argument("--event-type", help="Event type")
    state_parser.add_argument("--payload-file", help="Payload file")
    state_parser.set_defaults(func=_run_state)

    # profile subcommand
    profile_parser = sub.add_parser("profile", help="Profile management")
    profile_parser.add_argument("command", choices=["create", "validate", "list", "export"], help="Command")
    profile_parser.add_argument("name", nargs="?", help="Profile name")
    profile_parser.add_argument("--json", action="store_true", help="Output as JSON")
    profile_parser.set_defaults(func=_run_profile)

    # supervisor subcommand
    supervisor_parser = sub.add_parser("supervisor", help="Supervisor operations")
    supervisor_parser.add_argument("command", choices=["status", "cancel"], help="Command")
    supervisor_parser.add_argument("--store", type=Path, required=True, help="Store path")
    supervisor_parser.add_argument("--root-session-id", required=True, help="Root session ID")
    supervisor_parser.set_defaults(func=_run_supervisor)

    # coding subcommand
    coding_parser = sub.add_parser("coding", help="Coding loop execution")
    coding_parser.add_argument("--session-id", required=True, help="Session ID")
    coding_parser.add_argument("--store", type=Path, required=True, help="Store path")
    coding_parser.add_argument("--config-json", type=Path, required=True, help="Config JSON path")
    coding_parser.set_defaults(func=_run_coding)

    # rlm subcommand
    rlm_parser = sub.add_parser("rlm", help="RLM node execution")
    rlm_parser.add_argument("--session-id", required=True, help="Session ID")
    rlm_parser.add_argument("--store", type=Path, required=True, help="Store path")
    rlm_parser.add_argument("--config-json", type=Path, required=True, help="Config JSON path")
    rlm_parser.add_argument("--context-ref-json", type=Path, required=True, help="Context ref JSON path")
    rlm_parser.add_argument("--depth", type=int, required=True, help="Depth")
    rlm_parser.set_defaults(func=_run_rlm)

    # sessions subcommand
    sessions_parser = sub.add_parser("sessions", help="List real session state, write widget snapshot")
    sessions_parser.add_argument("--store", type=Path, help="Session store path (default: agent-platform/.sessions)")
    sessions_parser.add_argument("--snapshot", type=Path, help="Snapshot output path (default: agent-platform/widget/snapshot.json)")
    sessions_parser.set_defaults(func=_run_sessions)

    # widget subcommand
    widget_parser = sub.add_parser("widget", help="Serve the sessions widget (loopback-only, blocks until Ctrl+C)")
    widget_parser.set_defaults(func=_run_widget)

    # dispatch subcommand
    dispatch_parser = sub.add_parser("dispatch", help="Route a tagged task to an engine and invoke it (Orchestrator Dispatch v0.1)")
    dispatch_parser.add_argument("--tags", required=True, help="Comma-separated task-shape tags (e.g. research,background-task)")
    dispatch_parser.add_argument("--task-id", required=True, help="Task identity recorded in session state")
    dispatch_parser.add_argument("--prompt", required=True, help="Prompt to send if routed to an LLM-backed engine")
    dispatch_parser.add_argument("--store", type=Path, help="Session store path (default: agent-platform/.sessions)")
    dispatch_parser.add_argument("--hermes-profile", default="builder", help="Hermes profile to use if routed to hermes (default: builder)")
    dispatch_parser.add_argument("--timeout", type=int, default=120, help="Timeout in seconds for an engine invocation (default: 120)")
    dispatch_parser.add_argument("--model", help="Model override passed to hermes -m (optional)")
    dispatch_parser.add_argument("--provider", help="Provider override passed to hermes --provider (optional)")
    dispatch_parser.set_defaults(func=_run_dispatch)

    # runtimes subcommand
    runtimes_parser = sub.add_parser("runtimes", help="List known agent runtimes and whether each is on PATH")
    runtimes_parser.set_defaults(func=_run_runtimes)

    # credentials subcommand
    credentials_parser = sub.add_parser("credentials", help="Admin surface over the credential broker")
    credentials_sub = credentials_parser.add_subparsers(dest="credentials_command", required=True)
    cred_store_parser = credentials_sub.add_parser("store", help="Store a credential (value read from stdin)")
    cred_store_parser.add_argument("--id", required=True, help="Credential id")
    cred_store_parser.add_argument("--confirm", action="store_true", help="Required to actually persist the credential")
    cred_store_parser.add_argument("--store-dir", type=Path, help="Credential store dir (default: agent-platform/.credentials)")
    cred_inject_parser = credentials_sub.add_parser("inject", help="Print a credential's value (purpose-bound)")
    cred_inject_parser.add_argument("--id", required=True, help="Credential id")
    cred_inject_parser.add_argument("--runtime", required=True, help="Requesting runtime identity")
    cred_inject_parser.add_argument("--purpose", required=True, help="Why this credential is being requested")
    cred_inject_parser.add_argument("--store-dir", type=Path, help="Credential store dir (default: agent-platform/.credentials)")
    credentials_parser.set_defaults(func=_run_credentials)

    # addons subcommand
    addons_parser = sub.add_parser("addons", help="Admin surface over the addon review gate")
    addons_sub = addons_parser.add_subparsers(dest="addons_command", required=True)
    addons_submit_parser = addons_sub.add_parser("submit", help="Submit one candidate through the addon review gate")
    addons_submit_parser.add_argument("--candidate-id", required=True, help="e.g. addon@my-addon")
    addons_submit_parser.add_argument("--codex-security-passed", action="store_true", help="Codex security review passed")
    addons_submit_parser.add_argument("--incomplete", action="store_true", help="Mark the evidence matrix incomplete (fails closed)")
    addons_parser.set_defaults(func=_run_addons)

    args = parser.parse_args(argv)

    envelope = ResultEnvelope(run_id=args.command)
    try:
        result = args.func(args)
        envelope.status = result.status
        envelope.artifacts = result.artifacts
        envelope.evidence = result.evidence
        envelope.error = result.error
        envelope.finished_at = datetime.now(timezone.utc).isoformat()
    except Exception as e:
        envelope.status = "failed"
        envelope.finished_at = datetime.now(timezone.utc).isoformat()
        envelope.error = {"category": "unhandled_exception", "message": str(e)}

    print(envelope.to_json())
    return 0 if envelope.status == "succeeded" else 1


if __name__ == "__main__":
    sys.exit(main())
