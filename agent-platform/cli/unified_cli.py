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
  status           — Table/ledger view of agent/pipeline state, default operator surface (status.py)
  pipeline         — Live per-agent progress bars; --watch keeps redrawing (pipeline.py)
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from runtime.engine_registry import EngineContext

logger = logging.getLogger(__name__)


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
        from subprocess_windows import no_window_kwargs
        python_exe = shutil.which("python") or sys.executable
        profile_cli_path = Path(__file__).parent.parent.parent / "scripts" / "profile_cli.py"
        argv = [python_exe, str(profile_cli_path), args.command]
        if hasattr(args, 'name') and args.name:
            argv.append(args.name)
        if hasattr(args, 'json') and args.json:
            argv.append("--json")

        result = subprocess.run(
            argv, capture_output=True, text=True, cwd=Path(__file__).parent.parent, **no_window_kwargs()
        )
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


def _collect_orchestrator_projection(args: argparse.Namespace) -> dict[str, Any]:
    """Build the single read-only projection shared by CLI, chat, and widget."""
    ap_path = _get_agent_platform_path()
    if str(ap_path) not in sys.path:
        sys.path.insert(0, str(ap_path))
    cli_dir = Path(__file__).parent
    if str(cli_dir) not in sys.path:
        sys.path.insert(0, str(cli_dir))

    from cli import orchestrator as orchestrator_cli
    from cli import status as status_cli
    from routing.discovery import discover_installed_runtimes
    from routing.engine_manifest import DEFAULT_MANIFESTS
    from runtime.default_engine_context import build_default_engine_context

    store = args.store or (ap_path / ".sessions")
    snapshot_path = args.snapshot or (ap_path / "widget" / "snapshot.json")
    sessions = status_cli.load_sessions(store, stale_after_seconds=args.stale_after)
    active_runtimes = {
        item.get("runtime") for item in sessions
        if item.get("runtime") and item.get("display_status") == "running"
    }
    runtimes = [
        {
            "runtime_id": item.runtime_id,
            "installed": item.installed,
            "available": item.installed,
            "loaded": item.runtime_id in {"hermes", "claude", "codex"} and item.installed,
            "running": item.runtime_id in active_runtimes,
            "path": item.path,
        }
        for item in discover_installed_runtimes()
    ]
    context = build_default_engine_context()
    engines = orchestrator_cli.engine_inventory(DEFAULT_MANIFESTS, context)
    profile_roots, loaded_by_root = orchestrator_cli.hermes_profile_skill_roots()
    skills = orchestrator_cli.merge_skills(
        orchestrator_cli.discover_skills(orchestrator_cli.default_skill_roots(ap_path))
        + orchestrator_cli.discover_skills(profile_roots, loaded_by_root=loaded_by_root)
    )
    profiles = orchestrator_cli.discover_hermes_profiles()
    workstreams = status_cli.build_workstreams(sessions)
    summary = status_cli.build_orchestrator_summary(sessions)
    status_cli.write_snapshot(
        sessions,
        snapshot_path,
        runtimes=runtimes,
        engines=engines,
        skills=skills,
        profiles=profiles,
    )
    return {
        "orchestrator": summary,
        "workstreams": workstreams,
        "runtimes": runtimes,
        "engines": engines,
        "skills": skills,
        "profiles": profiles,
        "snapshot_path": snapshot_path,
    }


def _collect_session_projection(args: argparse.Namespace) -> dict[str, Any]:
    """Lightweight sessions/workstreams-only projection for `status` and `pipeline`.

    Deliberately does *not* call `_collect_orchestrator_projection`: that one
    also discovers engines, runtimes, and skills (a hermes-profile subprocess
    call plus a walk of ~900 skill files), which live-testing showed costs
    several seconds per call. That's fine for an occasional `orchestrator
    overview`, but `pipeline --watch` calls its collector every redraw --
    at that cost, a requested `--interval` under ~10s is a lie. `status` and
    `pipeline` only ever render sessions/workstreams, so this only computes
    that, keeping both commands fast and `--watch` actually live.

    Still inserts `ap_path` onto `sys.path` before `cli_dir`, and before any
    `from cli import ...`, for the same reason `_collect_orchestrator_
    projection` does: a stale editable-install finder for a *different*
    `agent-platform` checkout's `cli` package is registered globally in this
    environment, and importing `cli.status` before that ordering is set
    silently binds to the other checkout's copy.

    Still writes the shared widget snapshot via `write_snapshot`'s
    carry-forward semantics (only `sessions` is passed, so any
    runtimes/engines/skills/profiles a prior `orchestrator`/`runtimes` call
    wrote stay in the snapshot rather than being wiped).
    """
    ap_path = _get_agent_platform_path()
    if str(ap_path) not in sys.path:
        sys.path.insert(0, str(ap_path))
    cli_dir = Path(__file__).parent
    if str(cli_dir) not in sys.path:
        sys.path.insert(0, str(cli_dir))

    from cli import status as status_cli

    store = args.store or (ap_path / ".sessions")
    snapshot_path = args.snapshot or (ap_path / "widget" / "snapshot.json")
    sessions = status_cli.load_sessions(store, stale_after_seconds=args.stale_after)
    workstreams = status_cli.build_workstreams(sessions)
    summary = status_cli.build_orchestrator_summary(sessions)
    status_cli.write_snapshot(sessions, snapshot_path)
    return {"orchestrator": summary, "workstreams": workstreams, "snapshot_path": snapshot_path}


def _run_orchestrator_chat(
    args: argparse.Namespace, *, engine_context: "EngineContext | None" = None,
    input_fn=None,
) -> ResultEnvelope:
    """Talk to the advisory orchestrator while deterministic commands stay local."""
    # _collect_orchestrator_projection() bootstraps agent-platform's root
    # (and thus top-level modules like subprocess_windows) onto sys.path --
    # it must run before any import that transitively needs that path,
    # which is why these imports come after it rather than at the top of
    # the function (a bare `python cli/unified_cli.py orchestrator chat`
    # invocation has no other mechanism to put agent-platform on sys.path).
    projection = _collect_orchestrator_projection(args)

    from cli import orchestrator as orchestrator_cli
    from runtime import session_state as state
    from runtime.default_engine_context import build_default_engine_context
    from runtime.engine_registry import default_timeout_seconds

    context = engine_context or build_default_engine_context()
    active_engine_id = getattr(args, "engine", None) or "hermes"
    engine_sessions: dict[str, str] = {}
    transcript_id = orchestrator_cli.new_transcript_id()
    store = args.store or (_get_agent_platform_path() / ".sessions")
    session_id: str | None = None
    sequence = 0
    read_input = input_fn or input
    turn = 0
    failed = False

    # Open question #4: resuming a *past* Cortxt session's engine-native
    # conversation across REPL restarts. `engine_session_id` is stored per
    # turn on every chat.assistant event (see below); a fresh REPL
    # invocation with --resume <cortxt session_id> reads that history back
    # so the active engine's next turn continues its own native
    # conversation instead of starting fresh. Each engine's last known
    # engine_session_id is restored independently (not just the active
    # engine's) so a later `/engine` switch mid-resumed-REPL also picks up
    # that engine's own last session, same per-engine tracking this REPL
    # already does for a single live run.
    resume_session_id = getattr(args, "resume", None)
    if resume_session_id:
        try:
            existing = state.load(store, resume_session_id)
        except state.SessionError as error:
            print(f"Could not resume session {resume_session_id}: {error.message}")
            return ResultEnvelope(
                status="failed",
                error={"category": error.category, "message": error.message},
            )
        session_id = resume_session_id
        sequence = state.latest_sequence(existing)
        for event in existing["events"]:
            if event["event_type"] != "chat.assistant":
                continue
            payload = event["payload"]
            engine_id = payload.get("engine")
            engine_session_id = payload.get("engine_session_id")
            if engine_id and engine_session_id:
                engine_sessions[engine_id] = engine_session_id
        print(f"Resumed session {session_id}.")

    print("Cortxt orchestrator chat — advisory, GitHub workflow state is authoritative.")
    print("Commands: /status /workstreams /runtimes /skills /engine <id> /quit")
    pending = [args.ask] if args.ask else None
    while True:
        try:
            value = pending.pop(0) if pending else read_input("cortxt> ")
        except (EOFError, KeyboardInterrupt):
            print("\nSession closed.")
            break
        value = value.strip()
        if not value:
            if pending is not None:
                break
            continue
        if value == "/quit":
            print("Session closed.")
            break
        if value.startswith("/engine"):
            parts = value.split(maxsplit=1)
            if len(parts) == 2 and parts[1].strip():
                candidate = parts[1].strip()
                if context.get(candidate).has_provider:
                    active_engine_id = candidate
                else:
                    print(f"Engine '{candidate}' is not available (no provider registered). Staying on '{active_engine_id}'.")
                    if pending is not None and not pending:
                        break
                    continue
            print(f"Active engine: {active_engine_id}")
            if pending is not None and not pending:
                break
            continue
        if value.startswith("/"):
            print(orchestrator_cli.render_chat_command(value, projection))
        else:
            local_reply = orchestrator_cli.local_conversation_reply(value)
            if local_reply is not None:
                print(local_reply)
                if pending is not None and not pending:
                    break
                continue
            turn += 1
            if session_id is None:
                session_doc = state.create(
                    store,
                    task_id=f"orchestrator-chat:{transcript_id[:8]}",
                    workstream_id=args.workstream_id or args.branch or "orchestrator-chat",
                    run_id=transcript_id,
                    branch=args.branch,
                    worker_role="orchestrator",
                    runtime=active_engine_id,
                )
                session_id = session_doc["session_id"]
            prompt, redactions = orchestrator_cli.build_chat_prompt(value, projection)
            user_record = orchestrator_cli.transcript_record(
                transcript_id=transcript_id, turn_index=turn, role="user",
                content=value, engine=active_engine_id, status="submitted", redactions=redactions,
            )
            state.append(store, session_id, sequence, "chat.user", user_record)
            sequence += 1
            broker = context.get(active_engine_id)
            # args.hermes_profile ("researcher" by default) is a Hermes
            # profile name; only Hermes understands it. Other engines get
            # no profile (None) unless a future flag adds an engine-aware
            # mapping -- passing a Hermes-shaped name to e.g. Codex's -p
            # would just fail against a real CLI.
            turn_profile = args.hermes_profile if active_engine_id == "hermes" else None
            # args.timeout is None unless the operator passed --timeout
            # explicitly; the default is per-engine, not one global 120s
            # (spec Open question #5 -- a Codex coding turn legitimately
            # needs longer than a Hermes advisory reply).
            turn_timeout = args.timeout if args.timeout is not None else default_timeout_seconds(active_engine_id)
            try:
                result = broker.invoke(
                    turn_profile,
                    prompt,
                    timeout_seconds=turn_timeout,
                    model=args.model,
                    provider=args.provider,
                    cwd=_get_agent_platform_path().parent,
                    session_id=engine_sessions.get(active_engine_id),
                )
            except Exception as error:
                result = {"status": "failed", "stdout": "", "stderr": str(error), "session_id": None}
            answer = result.get("stdout", "").strip()
            status = result.get("status", "failed")
            new_engine_session_id = result.get("session_id")
            if new_engine_session_id:
                engine_sessions[active_engine_id] = new_engine_session_id
            if answer:
                print(answer)
            else:
                print(f"{active_engine_id} {status}: {result.get('stderr') or 'no response'}")
            assistant_record = orchestrator_cli.transcript_record(
                transcript_id=transcript_id, turn_index=turn, role="assistant",
                content=answer or result.get("stderr", ""), engine=active_engine_id, status=status,
                engine_session_id=new_engine_session_id,
            )
            state.append(store, session_id, sequence, "chat.assistant", assistant_record)
            sequence += 1
            failed = failed or status != "succeeded"
        if pending is not None and not pending:
            break
    artifacts = [f"snapshot:{projection['snapshot_path']}"]
    if session_id is not None:
        state.append(
            store, session_id, sequence, "session.terminal",
            {"status": "failed" if failed else "succeeded"},
        )
        projection = _collect_orchestrator_projection(args)
        artifacts.append(f"session:{session_id}")
    return ResultEnvelope(
        status="failed" if failed else "succeeded",
        artifacts=artifacts,
        evidence=[{"transcript_id": transcript_id, "turns": turn, "content_persisted": False}],
    )


def _run_orchestrator(args: argparse.Namespace) -> ResultEnvelope:
    """Refresh/render the projection, or enter conversational chat mode."""
    try:
        if args.orchestrator_command == "chat":
            return _run_orchestrator_chat(args)
        ap_path = _get_agent_platform_path()
        cli_dir = Path(__file__).parent
        if str(cli_dir) not in sys.path:
            sys.path.insert(0, str(cli_dir))

        from cli import orchestrator as orchestrator_cli
        projection = _collect_orchestrator_projection(args)
        summary = projection["orchestrator"]
        workstreams = projection["workstreams"]
        runtimes = projection["runtimes"]
        engines = projection["engines"]
        skills = projection["skills"]
        snapshot_path = projection["snapshot_path"]
        print(orchestrator_cli.render_overview(summary, workstreams, runtimes, engines, skills))
        return ResultEnvelope(
            status="succeeded",
            artifacts=[f"snapshot:{snapshot_path}"],
            evidence=[{"orchestrator": summary, "workstreams": len(workstreams)}],
        )
    except Exception as e:
        return ResultEnvelope(status="failed", error={"category": "runtime_error", "message": str(e)})


def _run_status(args: argparse.Namespace) -> ResultEnvelope:
    """`cortxt status` -- the default table/ledger view of current agent and pipeline state.

    Uses `_collect_session_projection` (sessions/workstreams only, not the
    full engine/skill/runtime discovery `orchestrator overview` also does)
    so this stays fast enough to be the go-to default command.

    `_collect_session_projection` must run before any `from cli import ...`
    here -- see its docstring: it's what puts this worktree's
    `agent-platform` root ahead of `cli_dir` on `sys.path`, needed because a
    stale editable-install finder for a *different* `agent-platform`
    checkout's `cli` package is registered globally in this environment
    (found live: `AttributeError: module 'cli.status' has no attribute
    'render_status_table'`, since that copy predates this feature).
    """
    try:
        projection = _collect_session_projection(args)
        from cli import status as status_cli
        workstreams = projection["workstreams"]
        print(status_cli.render_status_table(projection["orchestrator"], workstreams))
        return ResultEnvelope(
            status="succeeded",
            artifacts=[f"workstreams:{len(workstreams)}", f"snapshot:{projection['snapshot_path']}"],
            evidence=[{"orchestrator": projection["orchestrator"], "workstreams": len(workstreams)}],
        )
    except Exception as e:
        return ResultEnvelope(status="failed", error={"category": "runtime_error", "message": str(e)})


def _run_pipeline(args: argparse.Namespace) -> ResultEnvelope:
    """`cortxt pipeline` -- one live-progress frame; `--watch` keeps redrawing until Ctrl+C.

    Uses `_collect_session_projection` (see its docstring), not the full
    `_collect_orchestrator_projection` -- live-testing found the full
    projection's engine/skill/runtime discovery costs several seconds per
    call, which `--watch` pays on *every* redraw. At that cost, any
    `--interval` under ~10s doesn't reflect reality; sessions/workstreams
    are all `pipeline` renders, so that's all it collects.
    """
    try:
        projection = _collect_session_projection(args)
        from cli import pipeline as pipeline_cli

        def _collect() -> tuple[dict[str, Any], list[dict[str, Any]]]:
            fresh = _collect_session_projection(args)
            return fresh["orchestrator"], fresh["workstreams"]

        if not getattr(args, "watch", False):
            workstreams = projection["workstreams"]
            print(pipeline_cli.render_frame(projection["orchestrator"], workstreams))
            return ResultEnvelope(status="succeeded", artifacts=[f"workstreams:{len(workstreams)}"])

        iterations = pipeline_cli.run_watch(
            _collect,
            interval=args.interval,
            clear_fn=lambda: print("\x1b[2J\x1b[H", end=""),
        )
        return ResultEnvelope(status="succeeded", artifacts=[f"frames:{iterations}"])
    except Exception as e:
        return ResultEnvelope(status="failed", error={"category": "runtime_error", "message": str(e)})


def _run_widget(args: argparse.Namespace) -> ResultEnvelope:
    """Serve the sessions widget (loopback-only static server, widget/serve.py).

    Blocks in the foreground until interrupted, same shape as any other
    local dev-server CLI command. No new logic here -- this just calls the
    existing, already-tested serve.main().
    """
    try:
        candidate_mode = getattr(args, "widget_command", None) == "candidates" or getattr(args, "view", None) == "candidates"
        if candidate_mode:
            ap_path = _get_agent_platform_path()
            if str(ap_path) not in sys.path:
                sys.path.insert(0, str(ap_path))
            from widget_contract.adapters.github_ports import list_all_open_issues, resolve_blocker_status
            from widget_contract.candidates import build_candidates_view, dependency_targets, render_candidates_tree
            repo = getattr(args, "repo", None)
            if not repo:
                return ResultEnvelope(status="failed", error={"category": "input_error", "message": "--repo is required for candidates"})
            raw = list_all_open_issues(repo)
            blocker_statuses = {number: resolve_blocker_status(repo, number)
                                for number in dependency_targets(raw["issues"])}
            model = build_candidates_view(raw["issues"], complete=raw["complete"], blocker_statuses=blocker_statuses)
            if getattr(args, "widget_command", None) is None:
                print(json.dumps(render_candidates_tree(model), indent=2))
            elif args.format == "json":
                print(json.dumps(model, indent=2))
            else:
                for group in model["groups"]:
                    print(f"{group['id']} ({group['count']})")
                    for row in group["rows"]:
                        area = f" | {row['area']}" if row["area"] else ""
                        milestone = f" | {row['milestone']}" if row["milestone"] else ""
                        print(f"  #{row['number']} {row['title']} | {row['workflow']}{area}{milestone} | blockers:{row['open_blocker_count']}")
            return ResultEnvelope(status="succeeded", evidence=[{"candidates": model}])
        ap_path = _get_agent_platform_path()
        if str(ap_path) not in sys.path:
            sys.path.insert(0, str(ap_path))
        from widget import serve as widget_serve

        widget_serve.main()
        return ResultEnvelope(status="succeeded", artifacts=["widget:stopped"])
    except Exception as e:
        return ResultEnvelope(status="failed", error={"category": "runtime_error", "message": str(e)})


# Which Hermes profile a matched task_shape defaults to, when --hermes-profile
# isn't given explicitly. Evidence-based, not speculative: tonight both Phase 2
# Kanban-dispatch failures (#165, #166) and both admin-surface-CLI failures
# (#174, #175) happened on "builder" -- a research-shaped task defaulting to
# "builder" just because that was the flag's own default was never a real
# choice. Only "research" is mapped for now; other tags fall back to "builder"
# until there's similar evidence for a different default.
_HERMES_PROFILE_BY_TAG = {"research": "researcher"}


def _run_dispatch(
    args: argparse.Namespace, *, engine_context: "EngineContext | None" = None
) -> ResultEnvelope:
    """Orchestrator Dispatch v0.1: route a tagged task to an engine, invoke
    it, and record the outcome in the same session_state Phase 2 already
    tracks. See .hermes/plans/2026-08-19-orchestrator-dispatch-v01.md.

    Invocation goes through an EngineContext broker (ADR-026/027) instead of
    a hardcoded if/elif on engine_id -- "claude-direct" has no adapter
    registered (no confirmed one-shot Claude Code CLI entry point exists;
    guessing one would repeat the exact mistake ADR-022 was written to
    avoid), so its broker has no provider and the task is recorded as
    "blocked" -- picked up by a human/Claude Code session, not auto-executed.
    Any other engine_id with no registered adapter gets the same treatment,
    not a silent fallback to whatever IS registered.

    `engine_context` is None in every real CLI invocation (build_default_
    engine_context() is used); tests inject a fake one directly.
    """
    try:
        ap_path = _get_agent_platform_path()
        if str(ap_path) not in sys.path:
            sys.path.insert(0, str(ap_path))
        from routing.engine_manifest import DEFAULT_MANIFESTS, route
        from runtime import session_state as state
        from runtime.default_engine_context import build_default_engine_context

        tags = [t.strip() for t in args.tags.split(",") if t.strip()]
        choice = route(tags, DEFAULT_MANIFESTS)
        context = engine_context if engine_context is not None else build_default_engine_context()

        store = args.store or (_get_agent_platform_path() / ".sessions")
        session = state.create(
            store,
            task_id=args.task_id,
            workstream_id=getattr(args, "workstream_id", None),
            run_id=getattr(args, "run_id", None),
            issue_id=getattr(args, "issue_id", None),
            branch=getattr(args, "branch", None),
            worktree=getattr(args, "worktree", None),
            worker_role="builder" if choice.engine_id == "hermes" else "agent",
            runtime=choice.engine_id,
        )
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
            "checkpoint_required": choice.checkpoint_required,
        }

        broker = context.get(choice.engine_id)
        if broker.has_provider:
            # Check the full supplied tag set, not choice.matched_tag: route()
            # picks matched_tag as the alphabetically-first tag in the
            # intersection with the winning engine's task_shapes, which isn't
            # necessarily "research" even when "research" was among --tags
            # (e.g. --tags research,parallel-dispatch matches "parallel-dispatch"
            # alphabetically first, silently defeating this default -- caught
            # by review before merge).
            hermes_profile = args.hermes_profile if args.hermes_profile is not None else next(
                (profile for tag, profile in _HERMES_PROFILE_BY_TAG.items() if tag in tags),
                "builder",
            )
            result = broker.invoke(
                hermes_profile, args.prompt, timeout_seconds=args.timeout,
                model=args.model, provider=args.provider,
            )
            state.append(store, session_id, 0, "session.terminal", {"status": result["status"]})
            # Kept as "hermes_result" even though the broker is generic:
            # dsh now also routes here (research/background-task, operator
            # decision 2026-08-21), but renaming this key would be a real
            # (if currently invisible) evidence-shape change with no consumer
            # that would exercise the difference -- not done speculatively.
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
    finally:
        # Best-effort: the widget polls this same file (cli/status.py's
        # write_snapshot), so a dispatch result should show up there without
        # the operator having to run `cortxt sessions` afterward. Runs
        # whichever branch above returned, success or failure, via `finally`
        # -- a snapshot write failure must never mask the dispatch's own
        # result, but per review it must not vanish silently either
        # (status.py's own load_sessions() logs exactly this class of gap
        # for the same reason).
        #
        # Scope note (review): this only refreshes the snapshot for
        # `dispatch`. Other session.terminal producers (agent_loop.py,
        # coding_loop.py, rlm_child_cli.py, supervisor/coordinator.py) don't
        # -- extending to all of them is a real, larger change, not covered
        # by this fix. Also note load_sessions() rescans the whole store, so
        # this is O(n) in total session history per dispatch call; fine at
        # v0.1 scale, a candidate to revisit if the store grows large.
        try:
            cli_dir = Path(__file__).parent
            if str(cli_dir) not in sys.path:
                sys.path.insert(0, str(cli_dir))
            import status as status_cli

            snapshot_path = args.snapshot or (ap_path / "widget" / "snapshot.json")
            status_cli.write_snapshot(status_cli.load_sessions(store), snapshot_path)
        except Exception as snapshot_error:
            logger.warning("dispatch: could not refresh widget snapshot: %s", snapshot_error)


def _run_runtimes(args: argparse.Namespace) -> ResultEnvelope:
    """List known agent runtimes and whether each is on PATH (Phase 4 admin surface).

    Refreshes the widget snapshot's `runtimes` key on every call, same
    best-effort-but-visible pattern _run_dispatch uses for `sessions`: a
    snapshot write failure is logged, never masks this command's own
    result (Track 1, (internal design archive)).
    """
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

        runtimes_payload = [
            {"runtime_id": s.runtime_id, "installed": s.installed, "path": s.path} for s in statuses
        ]

        try:
            cli_dir = Path(__file__).parent
            if str(cli_dir) not in sys.path:
                sys.path.insert(0, str(cli_dir))
            import status as status_cli

            store = args.store or (_get_agent_platform_path() / ".sessions")
            snapshot_path = args.snapshot or (ap_path / "widget" / "snapshot.json")
            status_cli.write_snapshot(
                status_cli.load_sessions(store), snapshot_path, runtimes=runtimes_payload,
            )
        except Exception as snapshot_error:
            logger.warning("runtimes: could not refresh widget snapshot: %s", snapshot_error)

        return ResultEnvelope(
            status="succeeded",
            evidence=[{"runtimes": runtimes_payload}],
        )
    except Exception as e:
        return ResultEnvelope(status="failed", error={"category": "runtime_error", "message": str(e)})


def _run_credentials(args: argparse.Namespace) -> ResultEnvelope:
    """Admin surface over security.credential_broker.CredentialBroker (Phase 4).

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
            # Pass --confirm straight through to broker.store() rather than
            # short-circuiting here: the broker's own audit log is required
            # to record every attempt, granted or denied (credential_broker.py's
            # own documented invariant) -- a CLI-side pre-check bypassed that
            # for every unconfirmed attempt made through this admin surface.
            value = sys.stdin.read().rstrip("\n")
            broker.store(args.id, value, operator_confirmed=args.confirm)
            result = ResultEnvelope(status="succeeded", artifacts=[f"credential:{args.id}"])
        else:
            # inject
            value = broker.inject(args.id, requesting_runtime=args.runtime, purpose=args.purpose)
            print(value)
            result = ResultEnvelope(status="succeeded", artifacts=[f"credential:{args.id}"])

        _refresh_credentials_snapshot(args, ap_path, broker)
        return result
    except NotOperatorConfirmedError as e:
        return ResultEnvelope(status="failed", error={"category": "not_confirmed", "message": str(e)})
    except Exception as e:
        return ResultEnvelope(status="failed", error={"category": "runtime_error", "message": str(e)})


def _refresh_credentials_snapshot(args: argparse.Namespace, ap_path: Path, broker) -> None:
    """Derive credential metadata (id, last action/result/timestamp) from
    the broker's own audit log -- never the plaintext value, which never
    leaves `inject`'s stdout. Best-effort, same pattern as _run_dispatch's
    and _run_runtimes' snapshot refresh: a failure here is logged, never
    masks the store/inject result that already succeeded."""
    try:
        cli_dir = Path(__file__).parent
        if str(cli_dir) not in sys.path:
            sys.path.insert(0, str(cli_dir))
        import status as status_cli

        latest_by_id: dict[str, dict] = {}
        for record in broker.audit_log():
            if record.result != "ok":
                continue
            latest_by_id[record.credential_id] = {
                "credential_id": record.credential_id,
                "last_action": record.action,
                "last_result": record.result,
                "last_timestamp": record.timestamp,
            }

        store = args.store or (_get_agent_platform_path() / ".sessions")
        snapshot_path = args.snapshot or (ap_path / "widget" / "snapshot.json")
        status_cli.write_snapshot(
            status_cli.load_sessions(store), snapshot_path,
            credentials=list(latest_by_id.values()),
        )
    except Exception as snapshot_error:
        logger.warning("credentials: could not refresh widget snapshot: %s", snapshot_error)


def _run_addons(args: argparse.Namespace) -> ResultEnvelope:
    """Admin surface over learning.addon_review.AddonReviewGate (Phase 5).

    Only the `submit` action: run one candidate through the review gate
    and print the verdict. No addon registry/list here -- none exists yet
    (see .hermes/plans/2026-08-19-orchestrator-dispatch-v01.md); inventing
    one is a separate, larger decision, not CLI plumbing over already-tested code.

    Records each submission as a session_state entry tagged
    `addon:<candidate_id>` instead of a bespoke addon registry -- reusing
    the sessions mechanism the widget already renders gives visibility for
    free (Track 1, (internal design archive)).
    """
    try:
        ap_path = _get_agent_platform_path()
        if str(ap_path) not in sys.path:
            sys.path.insert(0, str(ap_path))
        from learning.addon_review import AddonReviewGate
        from learning.promotion_gate import PromotionGate
        from runtime import session_state as state

        matrix = {
            "complete": not args.incomplete,
            "codex_security_passed": args.codex_security_passed,
        }

        store = args.store or (ap_path / ".sessions")
        session = state.create(store, task_id=f"addon:{args.candidate_id}")
        session_id = session["session_id"]
    except Exception as e:
        return ResultEnvelope(status="failed", error={"category": "runtime_error", "message": str(e)})

    # From here on, a session exists on disk. Any exception below must
    # still leave it with a terminal event -- same orphaned-session bug
    # class fixed in _run_dispatch (a mid-flight exception between session
    # creation and the terminal append would otherwise leave it stuck
    # showing "running" forever).
    try:
        verdict = AddonReviewGate(PromotionGate()).submit(matrix, args.candidate_id)
        print(verdict)
        status = "succeeded" if verdict != "REJECT" else "failed"
        state.append(store, session_id, 0, "session.terminal", {"status": status, "verdict": verdict})

        return ResultEnvelope(
            status=status,
            evidence=[{"candidate_id": args.candidate_id, "verdict": verdict, "matrix": matrix}],
        )
    except Exception as e:
        state.append(store, session_id, 0, "session.terminal", {"status": "failed", "reason": str(e)})
        return ResultEnvelope(status="failed", error={"category": "runtime_error", "message": str(e)})
    finally:
        try:
            cli_dir = Path(__file__).parent
            if str(cli_dir) not in sys.path:
                sys.path.insert(0, str(cli_dir))
            import status as status_cli

            snapshot_path = args.snapshot or (ap_path / "widget" / "snapshot.json")
            status_cli.write_snapshot(status_cli.load_sessions(store), snapshot_path)
        except Exception as snapshot_error:
            logger.warning("addons: could not refresh widget snapshot: %s", snapshot_error)


def _run_daemon(args: argparse.Namespace) -> ResultEnvelope:
    """Run the Supervisor Daemon (workflow:ready dispatch loop)."""
    try:
        ap_path = _get_agent_platform_path()
        if str(ap_path) not in sys.path:
            sys.path.insert(0, str(ap_path))

        from daemon.stop_flag import request_stop

        if args.daemon_command == "sync-review":
            from daemon.review_sync import report_counts, sync_review_submissions

            report = sync_review_submissions(
                store=Path(args.store) if args.store else ap_path / ".sessions",
                state_dir=Path(args.state_dir), repo=args.repo,
            )
            return ResultEnvelope(status="succeeded",
                                  evidence=[{"review_sync": report_counts(report)}])

        if args.daemon_command == "stop":
            request_stop(Path(args.state_dir))
            return ResultEnvelope(status="succeeded", evidence=[{"stopped": args.state_dir}])

        if args.daemon_command == "status":
            snapshot_path = Path(args.snapshot)
            try:
                doc = json.loads(snapshot_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                doc = {}
            return ResultEnvelope(status="succeeded", evidence=[{"daemon": doc.get("daemon")}])

        if args.daemon_command == "start":
            from daemon.autonomy import AutonomyTracker
            from daemon.budget import SessionBudget
            from daemon.loop import DaemonLoop
            from daemon.stop_flag import clear_stop

            clear_stop(Path(args.state_dir))

            loop = DaemonLoop(
                repo=args.repo,
                state_dir=Path(args.state_dir),
                snapshot_path=Path(args.snapshot),
                budget=SessionBudget(max_cost_usd=args.max_cost_usd, max_wall_clock_seconds=args.max_wall_clock_seconds),
                autonomy=AutonomyTracker(),
                supervised=not args.unattended,
            )
            max_iterations = 1 if args.once else None
            reason = loop.run_forever(poll_interval_seconds=args.poll_interval, max_iterations=max_iterations)
            return ResultEnvelope(status="succeeded", evidence=[{"stop_reason": reason}])

        return ResultEnvelope(status="failed", error={"category": "invalid_args", "message": "unknown daemon_command"})
    except Exception as e:
        return ResultEnvelope(status="failed", error={"category": "runtime_error", "message": str(e)})


def _run_mcp(args: argparse.Namespace) -> ResultEnvelope:
    """`cortxt mcp serve` -- MCP stdio server exposing routing/admin tools.

    Blocks in the foreground until the client disconnects (EOF on stdin),
    same shape as `_run_widget` blocking until Ctrl+C -- an MCP client owns
    this process's lifecycle, not the operator.
    """
    try:
        if args.mcp_command != "serve":
            return ResultEnvelope(status="failed", error={"category": "invalid_args", "message": "unknown mcp_command"})
        ap_path = _get_agent_platform_path()
        if str(ap_path) not in sys.path:
            sys.path.insert(0, str(ap_path))
        from cortxt_mcp.server import serve as mcp_serve

        mcp_serve(
            allow_dispatch=args.allow_dispatch,
            allow_credentials=args.allow_credentials,
            store=args.store,
        )
        return ResultEnvelope(status="succeeded", artifacts=["mcp:stopped"])
    except Exception as e:
        return ResultEnvelope(status="failed", error={"category": "runtime_error", "message": str(e)})


def _run_work(args: argparse.Namespace) -> ResultEnvelope:
    """Create, inspect, resume, or submit contract-backed worker runs."""
    try:
        scripts = _get_agent_platform_path().parent / "scripts"
        if str(scripts) not in sys.path:
            sys.path.insert(0, str(scripts))
        if args.work_command == "plan":
            from execution_map import plan_from_json
            source = json.loads(args.input.read_text(encoding="utf-8"))
            projection = plan_from_json(source)
            print(json.dumps(projection, indent=2, sort_keys=True))
            return ResultEnvelope(status="succeeded", evidence=[{"execution_map": projection}])

        from work_launcher import default_launcher, parse_scope_file

        registry = args.registry or (_get_agent_platform_path() / ".dispatch" / "runs.json")
        registry.parent.mkdir(parents=True, exist_ok=True)
        launcher = default_launcher(registry)
        if args.work_command == "list":
            rows = launcher.list_active()
            print(json.dumps(rows, indent=2))
            return ResultEnvelope(status="succeeded", evidence=[{"runs": rows}])
        if args.work_command == "new":
            block = parse_scope_file(args.scope_file)
            data = launcher.create(
                args.repo, block["title"], block["scope"], block["acceptance_criteria"],
                runtime=args.runtime, worker_role=args.worker_role, workflow=args.workflow,
                max_runtime_seconds=args.max_runtime_seconds, max_cost_usd=args.max_cost_usd,
                approved=args.approve,
            )
        elif args.work_command == "resume":
            data = launcher.resume(
                args.issue_id, runtime=args.runtime, worker_role=args.worker_role,
                workflow=args.workflow, max_runtime_seconds=args.max_runtime_seconds,
                prompt=args.prompt,
            )
        else:
            data = launcher.submit(args.run_id, json.loads(args.result_file.read_text(encoding="utf-8")))
        print(data["run_id"])
        return ResultEnvelope(issue_id=data.get("issue_id"), run_id=data["run_id"],
                              status="succeeded", evidence=[data])
    except Exception as exc:
        return ResultEnvelope(status="failed", error={"category": "work_error", "message": str(exc)})


def main(argv: list[str] | None = None) -> int:
    """Unified CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Cortxt agent platform unified CLI — chains 6 existing CLIs with result envelope and evidence chain."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    work_parser = sub.add_parser("work", help="Launch and inspect parallel contract-backed work")
    work_sub = work_parser.add_subparsers(dest="work_command", required=True)
    work_new = work_sub.add_parser("new", help="Create, approve, claim, and dispatch a scope file")
    work_new.add_argument("scope_file", type=Path)
    work_new.add_argument("--repo", required=True)
    work_new.add_argument("--approve", action="store_true", help="Confirm operator approval")
    work_new.add_argument("--runtime", default="hermes-coordinator")
    work_new.add_argument("--worker-role", default="builder")
    work_new.add_argument("--workflow", default="work-launcher/v1")
    work_new.add_argument("--max-runtime-seconds", type=int, default=3600)
    work_new.add_argument("--max-cost-usd", type=float, required=True)
    work_new.add_argument("--registry", type=Path)
    work_new.set_defaults(func=_run_work)
    work_list = work_sub.add_parser("list", help="List active runs")
    work_list.add_argument("--registry", type=Path)
    work_list.set_defaults(func=_run_work)
    work_plan = work_sub.add_parser("plan", help="Render a read-only execution map projection")
    work_plan.add_argument("--input", type=Path, required=True,
                           help="Content-free JSON issue/claim snapshot")
    work_plan.set_defaults(func=_run_work)
    work_resume = work_sub.add_parser("resume", help="Claim a ready issue as a fresh run")
    work_resume.add_argument("issue_id")
    work_resume.add_argument("--prompt", required=True)
    work_resume.add_argument("--runtime", default="hermes-coordinator")
    work_resume.add_argument("--worker-role", default="builder")
    work_resume.add_argument("--workflow", default="work-launcher/v1")
    work_resume.add_argument("--max-runtime-seconds", type=int, default=3600)
    work_resume.add_argument("--registry", type=Path)
    work_resume.set_defaults(func=_run_work)
    work_submit = work_sub.add_parser("submit", help="Submit a terminal result for review")
    work_submit.add_argument("run_id")
    work_submit.add_argument("result_file", type=Path)
    work_submit.add_argument("--registry", type=Path)
    work_submit.set_defaults(func=_run_work)

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

    # status subcommand -- the default operator-facing table/ledger view
    status_parser = sub.add_parser(
        "status", help="Table/ledger view of current agent and pipeline state (default operator surface)"
    )
    status_parser.add_argument("--store", type=Path, help="Session store path")
    status_parser.add_argument("--snapshot", type=Path, help="Widget snapshot output path")
    status_parser.add_argument(
        "--stale-after", type=float, default=300.0,
        help="Seconds without an event before a running agent session is shown as stale",
    )
    status_parser.set_defaults(func=_run_status)

    # pipeline subcommand -- live per-agent progress bars
    pipeline_parser = sub.add_parser(
        "pipeline", help="Per-agent progress bars; add --watch to keep it redrawing until Ctrl+C"
    )
    pipeline_parser.add_argument("--store", type=Path, help="Session store path")
    pipeline_parser.add_argument("--snapshot", type=Path, help="Widget snapshot output path")
    pipeline_parser.add_argument(
        "--stale-after", type=float, default=300.0,
        help="Seconds without an event before a running agent session is shown as stale",
    )
    pipeline_parser.add_argument("--watch", action="store_true", help="Keep redrawing on --interval until Ctrl+C")
    pipeline_parser.add_argument("--interval", type=float, default=2.0, help="Seconds between redraws in --watch mode")
    pipeline_parser.set_defaults(func=_run_pipeline)

    orchestrator_parser = sub.add_parser(
        "orchestrator", help="Show the operator overview or talk to the local orchestrator"
    )
    orchestrator_parser.add_argument(
        "orchestrator_command", nargs="?", choices=["overview", "chat"], default="overview",
        help="overview (default) or interactive chat",
    )
    orchestrator_parser.add_argument("--store", type=Path, help="Session store path")
    orchestrator_parser.add_argument("--snapshot", type=Path, help="Widget snapshot output path")
    orchestrator_parser.add_argument(
        "--stale-after", type=float, default=300.0,
        help="Seconds without an event before a running agent session is shown as stale",
    )
    orchestrator_parser.add_argument("--ask", help="Run one chat turn non-interactively")
    orchestrator_parser.add_argument("--hermes-profile", default="researcher", help="Hermes profile for advisory chat (Hermes only -- ignored when --engine is not hermes)")
    orchestrator_parser.add_argument("--engine", default="hermes", help="Engine to talk to in chat mode (hermes, codex, ...)")
    orchestrator_parser.add_argument(
        "--timeout", type=int, default=None,
        help="Turn timeout in seconds (default: per-engine -- 120s for hermes, 300s for codex; "
             "see runtime.engine_registry.default_timeout_seconds)",
    )
    orchestrator_parser.add_argument(
        "--resume", help="Resume a past Cortxt orchestrator-chat session_id, "
        "restoring each engine's last engine-native session id",
    )
    orchestrator_parser.add_argument("--model", help="Optional Hermes model override")
    orchestrator_parser.add_argument("--provider", help="Optional Hermes provider override")
    orchestrator_parser.add_argument("--workstream-id", help="Attach the chat session to a workstream")
    orchestrator_parser.add_argument("--branch", help="Attach the chat session to a branch/worktree stream")
    orchestrator_parser.set_defaults(func=_run_orchestrator)

    # widget subcommand
    widget_parser = sub.add_parser("widget", help="Serve the sessions widget (loopback-only, blocks until Ctrl+C)")
    widget_parser.add_argument("--view", choices=["candidates"], help="Render a named read-only widget view")
    widget_parser.add_argument("--repo", help="GitHub owner/repo for a named view")
    widget_sub = widget_parser.add_subparsers(dest="widget_command")
    widget_candidates = widget_sub.add_parser("candidates", help="List the canonical actionable frontier and all open issues")
    widget_candidates.add_argument("--repo", required=True, help="GitHub owner/repo")
    widget_candidates.add_argument("--format", choices=["table", "json"], default="table")
    widget_parser.set_defaults(func=_run_widget)

    # mcp subcommand
    mcp_parser = sub.add_parser("mcp", help="MCP server (stdio transport) exposing routing/admin tools")
    mcp_sub = mcp_parser.add_subparsers(dest="mcp_command", required=True)
    mcp_serve_parser = mcp_sub.add_parser("serve", help="Start the MCP stdio server (blocks until the client disconnects)")
    mcp_serve_parser.add_argument(
        "--allow-dispatch", action="store_true",
        help="Unlock tier 1 tools (cortxt_dispatch, cortxt_addons_submit, cortxt_daemon_status)",
    )
    mcp_serve_parser.add_argument(
        "--allow-credentials", action="store_true",
        help="Unlock tier 2 tools (scaffolding -- no credential tools exist yet)",
    )
    mcp_serve_parser.add_argument(
        "--store", type=Path, help="Session store path for audit logging (default: agent-platform/.sessions)",
    )
    mcp_serve_parser.set_defaults(func=_run_mcp)

    # dispatch subcommand
    dispatch_parser = sub.add_parser("dispatch", help="Route a tagged task to an engine and invoke it (Orchestrator Dispatch v0.1)")
    dispatch_parser.add_argument("--tags", required=True, help="Comma-separated task-shape tags (e.g. research,background-task)")
    dispatch_parser.add_argument("--task-id", required=True, help="Task identity recorded in session state")
    dispatch_parser.add_argument("--prompt", required=True, help="Prompt to send if routed to an LLM-backed engine")
    dispatch_parser.add_argument("--store", type=Path, help="Session store path (default: agent-platform/.sessions)")
    dispatch_parser.add_argument("--snapshot", type=Path, help="Widget snapshot output path (default: agent-platform/widget/snapshot.json, same as `sessions`)")
    dispatch_parser.add_argument("--hermes-profile", default=None, help="Hermes profile to use if routed to hermes (default: inferred from matched tag, else builder)")
    dispatch_parser.add_argument("--timeout", type=int, default=120, help="Timeout in seconds for an engine invocation (default: 120)")
    dispatch_parser.add_argument("--model", help="Model override passed to hermes -m (optional)")
    dispatch_parser.add_argument("--provider", help="Provider override passed to hermes --provider (optional)")
    dispatch_parser.add_argument("--workstream-id", help="Operator-visible workstream identity")
    dispatch_parser.add_argument("--run-id", help="Durable attempt identity (generated externally when omitted)")
    dispatch_parser.add_argument("--issue-id", help="Canonical owner/repo#number correlation")
    dispatch_parser.add_argument("--branch", help="Git branch attached to the workstream")
    dispatch_parser.add_argument("--worktree", help="Worktree path attached to the workstream")
    dispatch_parser.set_defaults(func=_run_dispatch)

    # runtimes subcommand
    runtimes_parser = sub.add_parser("runtimes", help="List known agent runtimes and whether each is on PATH")
    runtimes_parser.add_argument("--store", type=Path, help="Session store path (default: agent-platform/.sessions)")
    runtimes_parser.add_argument("--snapshot", type=Path, help="Widget snapshot output path (default: agent-platform/widget/snapshot.json)")
    runtimes_parser.set_defaults(func=_run_runtimes)

    # credentials subcommand
    credentials_parser = sub.add_parser("credentials", help="Admin surface over the credential broker")
    credentials_sub = credentials_parser.add_subparsers(dest="credentials_command", required=True)
    cred_store_parser = credentials_sub.add_parser("store", help="Store a credential (value read from stdin)")
    cred_store_parser.add_argument("--id", required=True, help="Credential id")
    cred_store_parser.add_argument("--confirm", action="store_true", help="Required to actually persist the credential")
    cred_store_parser.add_argument("--store-dir", type=Path, help="Credential store dir (default: agent-platform/.credentials)")
    cred_store_parser.add_argument("--store", type=Path, help="Session store path (default: agent-platform/.sessions)")
    cred_store_parser.add_argument("--snapshot", type=Path, help="Widget snapshot output path (default: agent-platform/widget/snapshot.json)")
    cred_inject_parser = credentials_sub.add_parser("inject", help="Print a credential's value (purpose-bound)")
    cred_inject_parser.add_argument("--id", required=True, help="Credential id")
    cred_inject_parser.add_argument("--runtime", required=True, help="Requesting runtime identity")
    cred_inject_parser.add_argument("--purpose", required=True, help="Why this credential is being requested")
    cred_inject_parser.add_argument("--store-dir", type=Path, help="Credential store dir (default: agent-platform/.credentials)")
    cred_inject_parser.add_argument("--store", type=Path, help="Session store path (default: agent-platform/.sessions)")
    cred_inject_parser.add_argument("--snapshot", type=Path, help="Widget snapshot output path (default: agent-platform/widget/snapshot.json)")
    credentials_parser.set_defaults(func=_run_credentials)

    # addons subcommand
    addons_parser = sub.add_parser("addons", help="Admin surface over the addon review gate")
    addons_sub = addons_parser.add_subparsers(dest="addons_command", required=True)
    addons_submit_parser = addons_sub.add_parser("submit", help="Submit one candidate through the addon review gate")
    addons_submit_parser.add_argument("--candidate-id", required=True, help="e.g. addon@my-addon")
    addons_submit_parser.add_argument("--codex-security-passed", action="store_true", help="Codex security review passed")
    addons_submit_parser.add_argument("--incomplete", action="store_true", help="Mark the evidence matrix incomplete (fails closed)")
    addons_submit_parser.add_argument("--store", type=Path, help="Session store path (default: agent-platform/.sessions)")
    addons_submit_parser.add_argument("--snapshot", type=Path, help="Widget snapshot output path (default: agent-platform/widget/snapshot.json)")
    addons_parser.set_defaults(func=_run_addons)

    # daemon subcommand
    daemon_parser = sub.add_parser("daemon", help="Background Supervisor Daemon (workflow:ready dispatch loop)")
    daemon_sub = daemon_parser.add_subparsers(dest="daemon_command", required=True)

    daemon_start = daemon_sub.add_parser("start", help="Start the dispatch loop")
    daemon_start.add_argument("--repo", required=True, help="owner/repo to scan for workflow:ready issues")
    daemon_start.add_argument("--state-dir", required=True)
    daemon_start.add_argument("--snapshot", required=True)
    daemon_start.add_argument("--max-cost-usd", type=float, default=10.0)
    daemon_start.add_argument("--max-wall-clock-seconds", type=float, default=6 * 3600.0)
    daemon_start.add_argument("--poll-interval", type=float, default=30.0)
    daemon_start.add_argument("--once", action="store_true", help="Run a single iteration and exit (testing/proof-step)")
    daemon_start.add_argument("--unattended", action="store_true", help="Skip forced supervised-mode pausing (only after a class has earned autonomy)")
    daemon_start.set_defaults(func=_run_daemon)

    daemon_stop = daemon_sub.add_parser("stop", help="Request the running daemon to stop")
    daemon_stop.add_argument("--state-dir", required=True)
    daemon_stop.set_defaults(func=_run_daemon)

    daemon_status = daemon_sub.add_parser("status", help="Print the daemon section of the widget snapshot")
    daemon_status.add_argument("--snapshot", required=True)
    daemon_status.set_defaults(func=_run_daemon)

    daemon_sync_review = daemon_sub.add_parser("sync-review", help="Synchronize submitted reviews once")
    daemon_sync_review.add_argument("--repo", help="Optional owner/repo filter")
    daemon_sync_review.add_argument("--store", type=Path, help="Run store (default: agent-platform/.sessions)")
    daemon_sync_review.add_argument("--state-dir", required=True)
    daemon_sync_review.set_defaults(func=_run_daemon)

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
