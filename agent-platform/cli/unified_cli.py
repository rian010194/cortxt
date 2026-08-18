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
        from widget import serve as widget_serve

        widget_serve.main()
        return ResultEnvelope(status="succeeded", artifacts=["widget:stopped"])
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
