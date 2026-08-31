"""Unified CLI entry point for Cortxt agent platform.

Chains the 6 existing CLI interfaces with a consistent result envelope,
evidence chain, and resume support.

Commands:
  provider-policy  — Run provider policy evaluation (provider_policy_cli.py)
  state            — State ledger operations (state_cli.py)
  profile          — Profile management (profile_cli.py)
  theme            — List/inspect/preview/select visual theme presets (widget_contract.tokens/theme_resolver)
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
import os
import re
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from runtime.engine_registry import EngineContext
    from widget_contract.generation import GenerationOutcome

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


# Short display name + one-line description per preset id (issue #375). The
# visual-tokens.v2 preset documents (issue #373) carry no name/description
# fields of their own -- only color/typography/etc. role values -- so this
# CLI-owned metadata is the source for `theme list`/`theme inspect` display
# text. Keyed by preset id; keep in sync with widget/presets/visual-tokens.v2.json.
_THEME_PRESET_DISPLAY: dict[str, tuple[str, str]] = {
    "quiet-slate": ("Quiet Slate", "Balanced dark neutral with slate-blue accents (default)."),
    "graphite-ink": ("Graphite Ink", "Cooler ink-dark background with subdued graphite tones."),
    "soft-dusk": ("Soft Dusk", "Warmer twilight palette with periwinkle-lavender accents."),
}


def _theme_display_name(preset_id: str) -> str:
    return _THEME_PRESET_DISPLAY.get(preset_id, (preset_id, ""))[0]


def _theme_description(preset_id: str) -> str:
    return _THEME_PRESET_DISPLAY.get(preset_id, (preset_id, "No description available."))[1]


def _theme_preview_tree(preset_id: str) -> dict[str, Any]:
    """A small render tree exercising the status roles + a few UI tones.

    Deliberately built from the same primitives `widget_contract.tui.render_tui`
    already knows how to color (badge -> colorize_status for ok/warn/bad,
    metric -> accent/strong, text -> dim label), so `theme preview` reuses the
    existing renderer rather than reimplementing ANSI wrapping here.
    """
    return {
        "render": {
            "primitive": "stack",
            "props": {"label": f"Theme preview: {preset_id}"},
            "children": [
                {
                    "primitive": "row",
                    "props": {},
                    "children": [
                        {"primitive": "badge", "props": {"value": "ok"}},
                        {"primitive": "badge", "props": {"value": "warn"}},
                        {"primitive": "badge", "props": {"value": "bad"}},
                    ],
                },
                {"primitive": "metric", "props": {"label": "accent", "value": "Sample metric"}},
                {"primitive": "text", "props": {"label": "muted", "value": "Sample muted text"}},
            ],
        }
    }


def _run_theme(args: argparse.Namespace) -> ResultEnvelope:
    """List, inspect, preview, and select visual theme presets (issue #375).

    Consumes the issue #373 preset documents and the issue #374 resolver
    directly -- no subprocess indirection, matching the `widget generate`/
    `edit`/`remove`/`reset` subcommands added for issue #369.
    """
    ap_path = _get_agent_platform_path()
    if str(ap_path) not in sys.path:
        sys.path.insert(0, str(ap_path))
    from widget_contract.theme_resolver import (
        ThemeResolverError,
        resolve_theme,
        save_persisted_theme,
        sync_widget_tokens,
    )
    from widget_contract.tokens import TokensError, load_preset_tokens, load_presets
    from widget_contract.tui import render_tui

    command = args.theme_command
    pref_path = getattr(args, "path", None)

    try:
        if command == "list":
            envelope = load_presets()
            active = resolve_theme(path=pref_path)
            preset_ids = sorted(envelope["presets"])
            for preset_id in preset_ids:
                marker = "*" if preset_id == active else " "
                name = _theme_display_name(preset_id)
                desc = _theme_description(preset_id)
                print(f"{marker} {preset_id:<14} {name:<14} {desc}")
            return ResultEnvelope(
                status="succeeded",
                artifacts=[f"theme:list:{len(preset_ids)}"],
                evidence=[{"presets": preset_ids, "active": active}],
            )

        if command == "inspect":
            preset_id = getattr(args, "preset", None) or resolve_theme(path=pref_path)
            tokens = load_preset_tokens(preset_id)
            print(f"Preset: {preset_id} ({_theme_display_name(preset_id)})")
            print("Colors:")
            for key, value in tokens.get("colors", {}).items():
                print(f"  {key:<12} {value}")
            print("Typography:")
            for key, value in tokens.get("typography", {}).items():
                print(f"  {key:<14} {value}")
            return ResultEnvelope(
                status="succeeded",
                artifacts=[f"theme:inspect:{preset_id}"],
                evidence=[{"preset": preset_id, "tokens": tokens}],
            )

        if command == "preview":
            preset_id = getattr(args, "preset", None) or resolve_theme(path=pref_path)
            tokens = load_preset_tokens(preset_id)
            if getattr(args, "no_ansi", False):
                force_ansi: bool | None = False
            elif getattr(args, "force_ansi", False):
                force_ansi = True
            else:
                force_ansi = None
            truecolor = bool(getattr(args, "truecolor", False))
            auto_truecolor = False
            if not truecolor:
                # `ansi_map()` only fills in colors NOT already present in
                # DEFAULT_ANSI_MAP, and every preset defines the same 14
                # standard keys -- so the 256-color fallback path never
                # reflects the actual preset. Auto-enable 24-bit rendering
                # when the terminal advertises support (COLORTERM convention
                # used by most modern terminal emulators) so `preview`
                # reflects the requested preset by default; explicit
                # --truecolor/--no-ansi/--force-ansi still take precedence.
                colorterm = os.environ.get("COLORTERM", "").strip().lower()
                if colorterm in ("truecolor", "24bit"):
                    truecolor = True
                    auto_truecolor = True
            rendered = render_tui(
                _theme_preview_tree(preset_id), tokens=tokens, force_ansi=force_ansi, truecolor=truecolor
            )
            print(rendered)
            return ResultEnvelope(
                status="succeeded",
                artifacts=[f"theme:preview:{preset_id}"],
                evidence=[{"preset": preset_id, "truecolor": truecolor, "auto_truecolor": auto_truecolor}],
            )

        if command == "use":
            preset_id = args.preset
            save_persisted_theme(preset_id, path=pref_path)
            print(f"Theme preference set to '{preset_id}' ({_theme_display_name(preset_id)}).")
            # Also push the newly-selected preset into the widget host's
            # live tokens.json (issue #376 review finding 1): without this,
            # `cortxt widget --tui` (which resolves through theme_resolver)
            # and the widget host / site (which serve widget/tokens.json)
            # would render two different, unsynced palettes after a preset
            # switch. sync_widget_tokens() guards against clobbering a
            # hand-edited Widget Maker tokens.json -- see its docstring.
            sync_result = sync_widget_tokens(preset_id, path=pref_path)
            if sync_result.written:
                print(f"Widget host tokens synced to '{preset_id}'.")
            else:
                print(f"warning: widget host tokens NOT synced -- {sync_result.reason}")
            return ResultEnvelope(
                status="succeeded",
                artifacts=[f"theme:use:{preset_id}"],
                evidence=[{
                    "preset": preset_id,
                    "widget_tokens_synced": sync_result.written,
                    "widget_tokens_sync_reason": sync_result.reason,
                }],
            )

        return ResultEnvelope(
            status="failed",
            error={"category": "input_error", "message": f"Unknown theme command: {command}"},
        )
    except (ThemeResolverError, TokensError) as err:
        return ResultEnvelope(status="failed", error={"category": "input_error", "message": str(err)})
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


def _write_widget_artifact(artifact: dict, output_path: Path) -> None:
    """Atomically write a widget render artifact (tmp file + os.replace)."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, tmp = tempfile.mkstemp(prefix=".widget-", suffix=".tmp", dir=output_path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(artifact, handle, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, output_path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _run_widget_export(args: argparse.Namespace) -> ResultEnvelope:
    """Bundle and export a widget as a self-contained package (.cw / JSON)."""
    try:
        ap_path = _get_agent_platform_path()
        if str(ap_path) not in sys.path:
            sys.path.insert(0, str(ap_path))
        from widget_contract.package import PackageError, export_package

        pkg = export_package(
            args.widget_id,
            out_path=args.out,
            tokens_path=getattr(args, "tokens", None),
            ap_path=ap_path,
        )
        manifest_meta = pkg.get("manifest", {})
        print(json.dumps(manifest_meta, indent=2))
        return ResultEnvelope(
            status="succeeded",
            artifacts=[f"package:{args.out}"],
            evidence=[{"widget_id": args.widget_id, "out": str(args.out), "manifest": manifest_meta}],
        )
    except Exception as exc:
        if exc.__class__.__name__ == "PackageError":
            return ResultEnvelope(status="failed", error={"category": "package_export", "message": str(exc)})
        if exc.__class__.__name__ == "ContractError":
            return ResultEnvelope(status="failed", error={"category": "contract_error", "message": str(exc)})
        return ResultEnvelope(status="failed", error={"category": "unexpected_error", "message": str(exc)})


def _run_widget_load(args: argparse.Namespace) -> ResultEnvelope:
    """Validate, load, execute, and render a machine-emitted widget spec or install a package.

    The LLM-dogfood intake (issue #286): a spec file produced by any emitter
    (LLM or deterministic fixture) enters through the strict loader, its
    declared reads execute through the registered adapters, the renderer
    produces the tree, and the artifact is written for the loopback host.
    Unsafe/invalid specs fail closed with ContractError before any read.

    Package installation (issue #346): --package <file.cw> installs a self-contained
    widget package into the widget directory and registers it in widgets.json.
    """
    if getattr(args, "package", None):
        try:
            ap_path = _get_agent_platform_path()
            if str(ap_path) not in sys.path:
                sys.path.insert(0, str(ap_path))
            from widget_contract.package import PackageError, load_package

            installed = load_package(
                args.package,
                target_dir=getattr(args, "dir", None),
                ap_path=ap_path,
            )
            artifacts = [f"spec:{installed['spec_path']}", f"manifest:{installed['manifest_path']}"]
            if installed.get("artifact_path"):
                artifacts.append(f"artifact:{installed['artifact_path']}")
            print(json.dumps(installed, indent=2))
            return ResultEnvelope(
                status="succeeded",
                artifacts=artifacts,
                evidence=[installed],
            )
        except Exception as exc:
            if exc.__class__.__name__ == "PackageError":
                return ResultEnvelope(status="failed", error={"category": "package_load", "message": str(exc)})
            if exc.__class__.__name__ == "ContractError":
                return ResultEnvelope(status="failed", error={"category": "contract_error", "message": str(exc)})
            return ResultEnvelope(status="failed", error={"category": "unexpected_error", "message": str(exc)})

    if not getattr(args, "spec", None):
        return ResultEnvelope(
            status="failed",
            error={"category": "input_error", "message": "Either --package or --spec is required"},
        )
    try:
        ap_path = _get_agent_platform_path()
        if str(ap_path) not in sys.path:
            sys.path.insert(0, str(ap_path))
        from widget_contract.loader import load_widget_file
        from widget_contract.renderer import render

        spec = Path(args.spec)
        widget = load_widget_file(spec)  # strict validation before any I/O
        data: dict = {}
        read_states: dict[str, str] = {}
        repo = getattr(args, "repo", None)
        for read in widget.reads:
            if read.source == "github":
                if read.operation == "issues.all_open.list.v1":
                    if not repo:
                        return ResultEnvelope(status="failed", error={"category": "input_error",
                                                                      "message": "--repo is required for github reads"})
                    from widget_contract.adapters.github_ports import list_all_open_issues
                    data[read.id] = list_all_open_issues(repo)
                elif read.operation == "candidates.view.v1":
                    if not repo:
                        return ResultEnvelope(status="failed", error={"category": "input_error",
                                                                      "message": "--repo is required for github reads"})
                    from widget_contract.adapters.github_ports import read_candidates_view
                    action_descriptors = [{"id": a.id, "operation": a.operation, "port": a.port,
                                           "effect_class": a.confirm["effect_class"],
                                           "authorization": dict(a.authorization), "confirm": dict(a.confirm)}
                                          for a in widget.actions]
                    data[read.id] = read_candidates_view(repo, actions=action_descriptors)
                else:
                    return ResultEnvelope(status="failed", error={"category": "input_error",
                                                                  "message": f"unsupported emitted github read {read.operation}"})
                read_states[read.id] = "fresh"
            elif read.source == "store":
                if read.operation == "sessions.snapshot.v2":
                    from widget_contract.adapters.store_reads import read_snapshot_v2
                    snapshot_input = getattr(args, "snapshot_input", None) or (ap_path / "widget" / "snapshot.json")
                    data[read.id] = read_snapshot_v2(json.loads(Path(snapshot_input).read_text(encoding="utf-8")))
                elif read.operation == "docker.status.v1":
                    from widget_contract.adapters.store_reads import read_docker_status_v1
                    docker_input = getattr(args, "docker_input", None)
                    if docker_input and Path(docker_input).is_file():
                        data[read.id] = read_docker_status_v1(json.loads(Path(docker_input).read_text(encoding="utf-8")))
                    else:
                        reader = getattr(args, "docker_reader", None) or _default_docker_reader
                        data[read.id] = read_docker_status_v1(reader())
                elif read.operation == "webhooks.status.v1":
                    from widget_contract.adapters.store_reads import read_webhooks_status_v1
                    webhooks_input = getattr(args, "webhooks_input", None) or (ap_path / "widget" / "webhooks.json")
                    data[read.id] = read_webhooks_status_v1(json.loads(Path(webhooks_input).read_text(encoding="utf-8")))
                elif read.operation == "pages.deploys.v1":
                    from widget_contract.adapters.store_reads import read_pages_deploys_v1
                    pages_input = getattr(args, "pages_input", None) or (ap_path / "widget" / "pages-deploys.json")
                    data[read.id] = read_pages_deploys_v1(json.loads(Path(pages_input).read_text(encoding="utf-8")))
                elif read.operation == "usage-cost.v1":
                    from widget_contract.adapters.store_reads import read_usage_cost_v1
                    usage_input = getattr(args, "usage_input", None)
                    if usage_input and Path(usage_input).is_file():
                        data[read.id] = read_usage_cost_v1(json.loads(Path(usage_input).read_text(encoding="utf-8")))
                    else:
                        reader = getattr(args, "usage_reader", None) or _default_usage_reader
                        data[read.id] = read_usage_cost_v1(reader())
                elif read.operation == "session-agents.v1":
                    from widget_contract.adapters.store_reads import read_session_agents_v1
                    agents_input = getattr(args, "agents_input", None) or (ap_path / "widget" / "session-agents.json")
                    if agents_input and Path(agents_input).is_file():
                        data[read.id] = read_session_agents_v1(json.loads(Path(agents_input).read_text(encoding="utf-8")))
                    else:
                        reader = getattr(args, "agents_reader", None) or _default_session_agents_reader
                        data[read.id] = read_session_agents_v1(reader())
                else:
                    return ResultEnvelope(status="failed", error={"category": "input_error",
                                                                  "message": f"unsupported emitted store read {read.operation}"})
                read_states[read.id] = "fresh"
            else:
                return ResultEnvelope(status="failed", error={"category": "input_error",
                                                              "message": f"unsupported emitted source {read.source}"})
        tree = render(widget, data, read_states)
        view = getattr(args, "view", None) or widget.id
        output_path = getattr(args, "snapshot", None) or (ap_path / "widget" / f"{view}.json")
        _write_widget_artifact({**tree, "emitted": True, "document_hash": widget.document_hash}, output_path)
        print(json.dumps(tree["render"], indent=2))
        return ResultEnvelope(status="succeeded", artifacts=[f"{view}:{output_path}"],
                              evidence=[{"widget": tree, "document_hash": widget.document_hash}])
    except Exception as exc:
        if exc.__class__.__name__ == "ContractError":
            return ResultEnvelope(status="failed", error={"category": "contract_error", "message": str(exc)})
        return ResultEnvelope(status="failed", error={"category": "load_error", "message": str(exc)})


# Deliberately conservative and shorter than the loader's widget/read `_ID`
# pattern (widget_contract/loader.py:19) -- versions are short strings, and
# this pattern is what stands between LLM-derived `widget.version` text (the
# real loader validates `widget.id` but not `widget.version`'s format) and a
# filesystem path built from it.
_WIDGET_VERSION_ID = re.compile(r"^[a-z0-9][a-z0-9.-]{0,31}$")


def _widget_outcome_to_envelope(
    outcome: "GenerationOutcome",
    *,
    build_target_path: Callable[["GenerationOutcome"], Path],
    confirmed: bool,
    allow_overwrite: bool,
) -> ResultEnvelope:
    """Shared missing_operation/invalid/ok branching and confirm-gated write
    for `_run_widget_generate` and `_run_widget_edit`.

    `build_target_path` is called only once the outcome is "ok" (and its
    `widget_version` has passed the filename-safety check below), so each
    caller can derive its own install path from the outcome without either
    of them repeating the missing_operation/invalid handling or the
    confirm-gated write. `allow_overwrite=False` (generate) rejects writing
    over a file that already exists at the resolved target path; edit's own
    pre-existing installed file is the intended write target
    (`allow_overwrite=True`).
    """
    if outcome.status == "missing_operation":
        return ResultEnvelope(
            status="failed",
            error={
                "category": "missing_operation",
                "message": (
                    f"Unregistered read operation(s): {', '.join(outcome.missing_operations)}. "
                    f"Scaffold written to: {', '.join(outcome.scaffold_paths)}"
                ),
            },
        )
    if outcome.status == "invalid":
        return ResultEnvelope(status="failed", error={"category": "generation_error", "message": outcome.error_message})

    evidence = [{
        "widget_id": outcome.widget_id, "widget_version": outcome.widget_version,
        "capabilities": list(outcome.capabilities), "document_hash": outcome.document_hash,
        "confirmed": confirmed,
    }]
    if not confirmed:
        print(json.dumps(evidence[0], indent=2))
        print("Not installed -- re-run with --confirm to write this spec.")
        return ResultEnvelope(status="succeeded", artifacts=[], evidence=evidence)

    if not _WIDGET_VERSION_ID.fullmatch(outcome.widget_version or ""):
        return ResultEnvelope(
            status="failed",
            error={
                "category": "generation_error",
                "message": f"Generated widget_version {outcome.widget_version!r} is not filename-safe",
            },
        )

    target_path = build_target_path(outcome)
    if not allow_overwrite and target_path.exists():
        return ResultEnvelope(
            status="failed",
            error={
                "category": "input_error",
                "message": f"A spec already exists at {target_path}; use 'edit' to modify it, or remove it first.",
            },
        )

    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(outcome.spec_text, encoding="utf-8")
    print(json.dumps(evidence[0], indent=2))
    return ResultEnvelope(status="succeeded", artifacts=[f"spec:{target_path}"], evidence=evidence)


def _run_widget_generate(args: argparse.Namespace) -> ResultEnvelope:
    """Generate a widget spec by prompt (ADR-038 SS5 LLM-generability path).

    Never installs without --confirm; a missing read operation halts
    generation and reports the scaffold path instead of installing anything.
    Refuses to overwrite an existing installed spec at the same id+version
    (use `edit` instead).
    """
    ap_path = _get_agent_platform_path()
    if str(ap_path) not in sys.path:
        sys.path.insert(0, str(ap_path))
    from widget_contract.generation import generate_widget_spec

    specs_dir = Path(getattr(args, "specs_dir", None) or (ap_path / "widget_contract" / "specs"))
    scaffold_dir = specs_dir.parent / "scaffolds"
    outcome = generate_widget_spec(args.prompt, scaffold_dir=scaffold_dir)

    return _widget_outcome_to_envelope(
        outcome,
        build_target_path=lambda o: specs_dir / f"{o.widget_id}-{o.widget_version}.yaml",
        confirmed=bool(getattr(args, "confirm", False)),
        allow_overwrite=False,
    )


def _run_widget_edit(args: argparse.Namespace) -> ResultEnvelope:
    """Edit an existing widget spec by prompt; same confirm/scaffold rules as generate."""
    ap_path = _get_agent_platform_path()
    if str(ap_path) not in sys.path:
        sys.path.insert(0, str(ap_path))
    from widget_contract.generation import generate_widget_spec

    specs_dir = Path(getattr(args, "specs_dir", None) or (ap_path / "widget_contract" / "specs"))
    scaffold_dir = specs_dir.parent / "scaffolds"
    existing_path = specs_dir / f"{args.widget_id}-{args.widget_version}.yaml"
    if not existing_path.exists():
        return ResultEnvelope(status="failed", error={"category": "input_error",
                              "message": f"No installed spec at {existing_path}"})
    existing_spec = existing_path.read_text(encoding="utf-8")
    outcome = generate_widget_spec(args.prompt, existing_spec=existing_spec, scaffold_dir=scaffold_dir)

    return _widget_outcome_to_envelope(
        outcome,
        build_target_path=lambda o: existing_path,
        confirmed=bool(getattr(args, "confirm", False)),
        allow_overwrite=True,
    )


def _run_widget_remove(args: argparse.Namespace) -> ResultEnvelope:
    """Remove an installed widget spec. Preview-only unless --confirm (mirrors
    generate/edit's confirm gate; deletion is irreversible for a committed,
    hand-authored spec)."""
    ap_path = _get_agent_platform_path()
    specs_dir = getattr(args, "specs_dir", None) or (ap_path / "widget_contract" / "specs")
    target = Path(specs_dir) / f"{args.widget_id}-{args.widget_version}.yaml"
    if not target.exists():
        return ResultEnvelope(status="failed", error={"category": "input_error",
                              "message": f"No installed spec at {target}"})

    confirmed = bool(getattr(args, "confirm", False))
    if not confirmed:
        print(f"Would remove: {target}")
        print("Not removed -- re-run with --confirm to delete this spec.")
        return ResultEnvelope(status="succeeded", artifacts=[], evidence=[{"would_remove": [str(target)], "confirmed": False}])

    target.unlink()
    return ResultEnvelope(status="succeeded", artifacts=[f"removed:{target}"],
                          evidence=[{"widget_id": args.widget_id, "confirmed": True}])


def _run_widget_reset(args: argparse.Namespace) -> ResultEnvelope:
    """Remove all installed widget specs under specs_dir (replaces the 'Reset widget' UI
    button). Preview-only unless --confirm: `specs_dir` defaults to
    widget_contract/specs, which holds committed, hand-authored specs alongside
    any AI-generated ones, so an unconfirmed call must never delete anything."""
    ap_path = _get_agent_platform_path()
    specs_dir = Path(getattr(args, "specs_dir", None) or (ap_path / "widget_contract" / "specs"))
    candidates = sorted(specs_dir.glob("*.yaml")) if specs_dir.exists() else []

    confirmed = bool(getattr(args, "confirm", False))
    if not confirmed:
        for p in candidates:
            print(f"Would remove: {p}")
        print("Not removed -- re-run with --confirm to delete all specs.")
        return ResultEnvelope(status="succeeded", artifacts=[],
                              evidence=[{"would_remove": [str(p) for p in candidates], "confirmed": False}])

    removed = []
    for spec_file in candidates:
        spec_file.unlink()
        removed.append(str(spec_file))
    return ResultEnvelope(status="succeeded", artifacts=[f"removed:{p}" for p in removed],
                          evidence=[{"removed_count": len(removed), "confirmed": True}])


def _run_widget_compose(args: argparse.Namespace) -> ResultEnvelope:
    """Validate, load, execute, and compose multiple widget specs into a dashboard.

    Dashboard composition path (issue #327): loads referenced child widgets
    from --widgets-dir (<widget_id>-<version>.yaml), validates the composition
    via load_composition (exact versions, closed schema, acyclic typed
    connections, exact capability match, layout primitives), executes declared
    reads (github, store), renders child trees, merges them under the
    composition layout primitive, and writes the composed artifact atomically.
    Fails closed with stable error categories before any artifact is written.
    """
    try:
        ap_path = _get_agent_platform_path()
        if str(ap_path) not in sys.path:
            sys.path.insert(0, str(ap_path))
        from widget_contract.loader import ContractError, _parse, load_composition, load_widget_file
        from widget_contract.renderer import render

        spec_path = Path(args.spec)
        if not spec_path.is_file():
            return ResultEnvelope(status="failed", error={"category": "load_error",
                                                          "message": f"composition spec not found: {spec_path}"})
        raw_doc = _parse(spec_path.read_bytes())
        if not isinstance(raw_doc, dict) or "widgets" not in raw_doc or not isinstance(raw_doc["widgets"], list):
            load_composition(raw_doc, {})
            return ResultEnvelope(status="failed", error={"category": "contract_error", "message": "invalid composition document"})

        widgets_dir = Path(args.widgets_dir)
        widgets_map: dict[tuple[str, str], Any] = {}
        cleaned_widgets = []
        for ref in raw_doc.get("widgets", []):
            if not isinstance(ref, dict):
                cleaned_widgets.append(ref)
                continue
            widget_id = ref.get("widget_id")
            version = ref.get("version")
            explicit_path = ref.get("path")
            candidate = None
            if explicit_path and (widgets_dir / explicit_path).is_file():
                candidate = widgets_dir / explicit_path
            elif widget_id and version:
                for name in (f"{widget_id}-{version}.yaml", f"{widget_id}-{version}.yml", f"{widget_id}.yaml", f"{widget_id}.yml"):
                    p = widgets_dir / name
                    if p.is_file():
                        candidate = p
                        break
            if candidate is not None:
                try:
                    w = load_widget_file(candidate)
                    widgets_map[(w.id, w.version)] = w
                except ContractError:
                    raise
                except Exception as exc:
                    return ResultEnvelope(status="failed", error={"category": "load_error",
                                                                  "message": f"failed to load widget {candidate}: {exc}"})
            ref_copy = dict(ref)
            ref_copy.pop("path", None)
            cleaned_widgets.append(ref_copy)

        cleaned_doc = dict(raw_doc)
        cleaned_doc["widgets"] = cleaned_widgets
        composition = load_composition(cleaned_doc, widgets_map)

        repo = getattr(args, "repo", None)
        rendered_by_ns: dict[str, dict] = {}
        for ref in composition.widgets:
            ns = ref["namespace"]
            widget = widgets_map[(ref["widget_id"], ref["version"])]
            child_data: dict[str, Any] = {}
            child_read_states: dict[str, str] = {}
            for read in widget.reads:
                if read.source == "github":
                    if read.operation == "issues.all_open.list.v1":
                        if not repo:
                            return ResultEnvelope(status="failed", error={"category": "input_error",
                                                                          "message": "--repo is required for github reads"})
                        from widget_contract.adapters.github_ports import list_all_open_issues
                        child_data[read.id] = list_all_open_issues(repo)
                    elif read.operation == "candidates.view.v1":
                        if not repo:
                            return ResultEnvelope(status="failed", error={"category": "input_error",
                                                                          "message": "--repo is required for github reads"})
                        from widget_contract.adapters.github_ports import read_candidates_view
                        action_descriptors = [{"id": a.id, "operation": a.operation, "port": a.port,
                                               "effect_class": a.confirm["effect_class"],
                                               "authorization": dict(a.authorization), "confirm": dict(a.confirm)}
                                              for a in widget.actions]
                        child_data[read.id] = read_candidates_view(repo, actions=action_descriptors)
                    else:
                        return ResultEnvelope(status="failed", error={"category": "input_error",
                                                                      "message": f"unsupported emitted github read {read.operation}"})
                    child_read_states[read.id] = "fresh"
                elif read.source == "store":
                    if read.operation == "sessions.snapshot.v2":
                        from widget_contract.adapters.store_reads import read_snapshot_v2
                        snapshot_input = getattr(args, "snapshot_input", None) or (ap_path / "widget" / "snapshot.json")
                        if not Path(snapshot_input).is_file():
                            return ResultEnvelope(status="failed", error={"category": "load_error",
                                                                          "message": f"snapshot input not found: {snapshot_input}"})
                        child_data[read.id] = read_snapshot_v2(json.loads(Path(snapshot_input).read_text(encoding="utf-8")))
                    elif read.operation == "execution-map.plan.v1":
                        plan_input = getattr(args, "plan_input", None)
                        if not plan_input or not Path(plan_input).is_file():
                            return ResultEnvelope(status="failed", error={"category": "input_error",
                                                                          "message": "--plan-input is required for execution-map"})
                        from widget_contract.adapters.store_reads import read_execution_map_v1
                        store = json.loads(Path(plan_input).read_text(encoding="utf-8"))
                        scripts = ap_path.parent / "scripts"
                        if str(scripts) not in sys.path:
                            sys.path.insert(0, str(scripts))
                        from execution_map import plan_from_json
                        child_data[read.id] = read_execution_map_v1(plan_from_json, store)
                    elif read.operation == "docker.status.v1":
                        from widget_contract.adapters.store_reads import read_docker_status_v1
                        docker_input = getattr(args, "docker_input", None)
                        if docker_input and Path(docker_input).is_file():
                            raw_data = json.loads(Path(docker_input).read_text(encoding="utf-8"))
                            child_data[read.id] = read_docker_status_v1(raw_data)
                        else:
                            reader = getattr(args, "docker_reader", None) or _default_docker_reader
                            child_data[read.id] = read_docker_status_v1(reader())
                    elif read.operation == "webhooks.status.v1":
                        from widget_contract.adapters.store_reads import read_webhooks_status_v1
                        webhooks_input = getattr(args, "webhooks_input", None) or (ap_path / "widget" / "webhooks.json")
                        if Path(webhooks_input).is_file():
                            child_data[read.id] = read_webhooks_status_v1(json.loads(Path(webhooks_input).read_text(encoding="utf-8")))
                        else:
                            child_data[read.id] = {"schema_version": 1, "repo": "", "total": 0, "active": 0, "hooks": []}
                    elif read.operation == "pages.deploys.v1":
                        from widget_contract.adapters.store_reads import read_pages_deploys_v1
                        pages_input = getattr(args, "pages_input", None) or (ap_path / "widget" / "pages-deploys.json")
                        if Path(pages_input).is_file():
                            child_data[read.id] = read_pages_deploys_v1(json.loads(Path(pages_input).read_text(encoding="utf-8")))
                        else:
                            child_data[read.id] = {"schema_version": 1, "project": "cortxt", "account": "c7c04f119f81234dc3d851bf6ff2adfe",
                                                   "latest": {"id": "none", "environment": "none", "created_on": "none", "stage": "none", "status": "none"},
                                                   "deployments": []}
                    elif read.operation == "usage-cost.v1":
                        from widget_contract.adapters.store_reads import read_usage_cost_v1
                        usage_input = getattr(args, "usage_input", None)
                        if usage_input and Path(usage_input).is_file():
                            raw_data = json.loads(Path(usage_input).read_text(encoding="utf-8"))
                            child_data[read.id] = read_usage_cost_v1(raw_data)
                        else:
                            reader = getattr(args, "usage_reader", None) or _default_usage_reader
                            child_data[read.id] = read_usage_cost_v1(reader())
                    elif read.operation == "session-agents.v1":
                        from widget_contract.adapters.store_reads import read_session_agents_v1
                        agents_input = getattr(args, "agents_input", None) or (ap_path / "widget" / "session-agents.json")
                        if Path(agents_input).is_file():
                            child_data[read.id] = read_session_agents_v1(json.loads(Path(agents_input).read_text(encoding="utf-8")))
                        else:
                            reader = getattr(args, "agents_reader", None) or _default_session_agents_reader
                            child_data[read.id] = read_session_agents_v1(reader())
                    else:
                        return ResultEnvelope(status="failed", error={"category": "input_error",
                                                                      "message": f"unsupported emitted store read {read.operation}"})
                    child_read_states[read.id] = "fresh"
                else:
                    return ResultEnvelope(status="failed", error={"category": "input_error",
                                                                  "message": f"unsupported emitted source {read.source}"})
            rendered_by_ns[ns] = render(widget, child_data, child_read_states)

        def _expand_layout(node: dict) -> dict:
            if "widget" in node:
                return rendered_by_ns[node["widget"]]["render"]
            return {
                "primitive": node["primitive"],
                "props": node.get("props", {}),
                "children": [_expand_layout(c) for c in node.get("children", [])],
                "state": "ready",
            }

        layout_tree = _expand_layout(composition.layout)
        output_path = getattr(args, "snapshot", None) or (ap_path / "widget" / "composed.json")
        composed_artifact = {
            "contract_version": composition.contract_version,
            "widget": {
                "id": composition.id,
                "version": composition.version,
            },
            "composed": True,
            "render": layout_tree,
        }
        _write_widget_artifact(composed_artifact, output_path)
        print(json.dumps(layout_tree, indent=2))
        return ResultEnvelope(
            status="succeeded",
            artifacts=[f"{composition.id}:{output_path}"],
            evidence=[{"composition": composed_artifact}],
        )
    except Exception as exc:
        if exc.__class__.__name__ == "ContractError":
            return ResultEnvelope(status="failed", error={"category": "contract_error", "message": str(exc)})
        return ResultEnvelope(status="failed", error={"category": "load_error", "message": str(exc)})


def _default_docker_reader() -> dict[str, Any]:
    """Capture local Docker state into a safe content-free projection dictionary."""
    import shutil
    import subprocess
    try:
        from subprocess_windows import no_window_kwargs
        extra_kwargs = no_window_kwargs()
    except ImportError:
        extra_kwargs = {}

    docker_bin = shutil.which("docker")
    if not docker_bin:
        raise OSError("docker executable not found in PATH")

    try:
        info_proc = subprocess.run(
            [docker_bin, "info", "--format", "{{json .}}"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
            **extra_kwargs,
        )
    except subprocess.TimeoutExpired as exc:
        raise OSError("docker info timed out") from exc

    if info_proc.returncode != 0:
        error_msg = info_proc.stderr.strip() or f"docker info exited with code {info_proc.returncode}"
        raise OSError(f"docker info failed: {error_msg}")

    engine_info: dict[str, Any] = {}
    try:
        raw_info = json.loads(info_proc.stdout)
        if isinstance(raw_info, dict):
            engine_info = {
                "server_version": str(raw_info.get("ServerVersion", "unknown")),
                "os": str(raw_info.get("OperatingSystem", raw_info.get("OSType", "unknown"))),
                "architecture": str(raw_info.get("Architecture", "unknown")),
                "status": "running",
            }
    except Exception:
        engine_info = {"status": "running"}

    try:
        ps_proc = subprocess.run(
            [docker_bin, "ps", "-a", "--format", "{{json .}}"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
            **extra_kwargs,
        )
    except subprocess.TimeoutExpired as exc:
        raise OSError("docker ps timed out") from exc

    if ps_proc.returncode != 0:
        error_msg = ps_proc.stderr.strip() or f"docker ps exited with code {ps_proc.returncode}"
        raise OSError(f"docker ps failed: {error_msg}")

    containers: list[dict[str, str]] = []
    running_count = 0
    stdout_ps = ps_proc.stdout.strip()
    if stdout_ps:
        lines: list[Any] = []
        if stdout_ps.startswith("["):
            try:
                parsed = json.loads(stdout_ps)
                if isinstance(parsed, list):
                    lines = parsed
            except Exception:
                pass
        if not lines:
            for line in stdout_ps.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    lines.append(json.loads(line))
                except Exception:
                    continue

        for item in lines:
            if not isinstance(item, dict):
                continue
            c_id = str(item.get("ID") or item.get("Id") or item.get("ContainerID") or "")
            c_name = str(item.get("Names") or item.get("Name") or "")
            if c_name.startswith("/"):
                c_name = c_name[1:]
            c_image = str(item.get("Image") or "")
            c_status = str(item.get("Status") or item.get("State") or "")
            state_str = str(item.get("State") or "").lower()
            if state_str == "running" or c_status.lower().startswith("up"):
                running_count += 1
            containers.append({
                "id": c_id,
                "name": c_name,
                "image": c_image,
                "status": c_status,
            })

    try:
        img_proc = subprocess.run(
            [docker_bin, "images", "--format", "{{json .}}"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
            **extra_kwargs,
        )
    except subprocess.TimeoutExpired as exc:
        raise OSError("docker images timed out") from exc

    images: list[str] = []
    if img_proc.returncode == 0 and img_proc.stdout.strip():
        stdout_img = img_proc.stdout.strip()
        img_lines: list[Any] = []
        if stdout_img.startswith("["):
            try:
                parsed = json.loads(stdout_img)
                if isinstance(parsed, list):
                    img_lines = parsed
            except Exception:
                pass
        if not img_lines:
            for line in stdout_img.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    img_lines.append(json.loads(line))
                except Exception:
                    continue

        for item in img_lines:
            if not isinstance(item, dict):
                continue
            repo = item.get("Repository")
            tag = item.get("Tag")
            img_id = item.get("ID") or item.get("Id") or ""
            if repo and repo != "<none>" and tag and tag != "<none>":
                images.append(f"{repo}:{tag}")
            elif repo and repo != "<none>":
                images.append(str(repo))
            elif img_id:
                images.append(str(img_id))

    return {
        "schema_version": 1,
        "engine": engine_info,
        "containers": containers,
        "images": images,
        "total_containers": len(containers),
        "running_containers": running_count,
    }


def _default_usage_reader() -> dict[str, Any]:
    """Capture local usage and cost metrics into a safe projection dictionary."""
    ap_path = _get_agent_platform_path()
    usage_file = ap_path / "widget" / "fixtures" / "usage_data.json"
    if usage_file.is_file():
        try:
            data = json.loads(usage_file.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                if "usage" in data and isinstance(data["usage"], dict):
                    return data["usage"]
                if "states" in data and isinstance(data["states"], list) and data["states"]:
                    last = data["states"][-1]
                    if isinstance(last, dict):
                        return last.get("usage", last)
                if "runtimes" in data and "history" in data:
                    return data
        except Exception:
            pass

    return {
        "schema_version": 1,
        "period": "current",
        "total_cost_usd": 0.42,
        "total_tokens": 24800,
        "runtimes": [
            {"id": "hermes", "name": "Hermes", "tokens_in": 8000, "tokens_out": 4000, "cost_usd": 0.12, "model": "hermes-3-70b"},
            {"id": "codex", "name": "Codex", "tokens_in": 6000, "tokens_out": 2500, "cost_usd": 0.15, "model": "gpt-4o"},
            {"id": "claude", "name": "Claude", "tokens_in": 2000, "tokens_out": 1200, "cost_usd": 0.10, "model": "claude-3-7-sonnet"},
            {"id": "dsh", "name": "DSH", "tokens_in": 800, "tokens_out": 300, "cost_usd": 0.05, "model": "deepseek-v3"},
        ],
        "history": [
            {"at": "10:00", "tokens": 3000, "cost_usd": 0.05},
            {"at": "10:15", "tokens": 7500, "cost_usd": 0.12},
            {"at": "10:30", "tokens": 14000, "cost_usd": 0.22},
            {"at": "10:45", "tokens": 19500, "cost_usd": 0.31},
            {"at": "11:00", "tokens": 24800, "cost_usd": 0.42},
        ],
    }


def _default_session_agents_reader() -> dict[str, Any]:
    """Capture local session/agent state into a safe projection dictionary."""
    ap_path = _get_agent_platform_path()
    snapshot_path = ap_path / "widget" / "snapshot.json"
    if snapshot_path.is_file():
        try:
            data = json.loads(snapshot_path.read_text(encoding="utf-8"))
            sessions = data.get("sessions", [])
            if isinstance(sessions, list) and sessions:
                agents = []
                for s in sessions:
                    if not isinstance(s, dict):
                        continue
                    s_id = str(s.get("session_id") or s.get("id") or "agent-1")
                    role = str(s.get("worker_role") or s.get("role") or s.get("name") or "Agent")
                    runtime = str(s.get("runtime") or "hermes")
                    raw_status = str(s.get("status") or s.get("state") or "running").lower()
                    status = raw_status if raw_status in ("running", "blocked", "done", "queued") else ("running" if "run" in raw_status else "done")
                    curr_task = str(s.get("current_task") or s.get("task_id") or "Session task")
                    tasks_raw = s.get("tasks")
                    if not isinstance(tasks_raw, list) or not tasks_raw:
                        tasks = [{
                            "id": f"{s_id}-t1",
                            "title": curr_task,
                            "state": status,
                            "progress": 100 if status == "done" else (50 if status == "running" else 0),
                        }]
                    else:
                        safe_tasks = []
                        for idx, t in enumerate(tasks_raw):
                            if isinstance(t, dict):
                                safe_tasks.append({
                                    "id": str(t.get("id") or f"{s_id}-t{idx+1}"),
                                    "title": str(t.get("title") or f"Task {idx+1}"),
                                    "state": str(t.get("state") or "running"),
                                    "progress": int(t.get("progress") or (100 if t.get("state") == "done" else 50)),
                                })
                        tasks = safe_tasks
                    agents.append({
                        "id": s_id,
                        "name": role,
                        "runtime": runtime,
                        "status": status,
                        "current_task": curr_task,
                        "tasks": tasks,
                    })
                if agents:
                    return {"schema_version": 1, "agents": agents}
        except Exception:
            pass
    return {
        "schema_version": 1,
        "agents": [
            {
                "id": "agent-hermes",
                "name": "Hermes",
                "runtime": "hermes",
                "status": "running",
                "current_task": "Execute session plan",
                "tasks": [
                    {"id": "t1", "title": "Load context", "state": "done", "progress": 100},
                    {"id": "t2", "title": "Execute session plan", "state": "running", "progress": 65},
                    {"id": "t3", "title": "Verification", "state": "queued", "progress": 0},
                ],
            },
            {
                "id": "agent-pi",
                "name": "Pi",
                "runtime": "pi",
                "status": "running",
                "current_task": "Analyze codebase invariants",
                "tasks": [
                    {"id": "t4", "title": "Inspect AST", "state": "done", "progress": 100},
                    {"id": "t5", "title": "Analyze codebase invariants", "state": "running", "progress": 40},
                ],
            },
            {
                "id": "agent-codex",
                "name": "Codex",
                "runtime": "codex",
                "status": "done",
                "current_task": None,
                "tasks": [
                    {"id": "t6", "title": "Contract validation", "state": "done", "progress": 100},
                ],
            },
        ],
    }


def _run_widget(args: argparse.Namespace, docker_reader: Any = None, usage_reader: Any = None,
                agents_reader: Any = None, workstream_reader: Any = None,
                evidence_reader: Any = None, decision_reader: Any = None,
                attention_queue_reader: Any = None) -> ResultEnvelope:
    """Serve the sessions widget or execute a registered widget action.

    `cortxt widget` without a subcommand serves the sessions widget
    (loopback-only static server, widget/serve.py) and blocks until
    interrupted. `--view candidates` renders the candidates view through the
    widget-contract renderer. `--view session-pulse` renders the
    orchestrator/session snapshot through the contract. `--view execution-map`
    renders the execution-map plan. `--view docker-status` renders local
    docker status. `--view usage-cost` renders token usage and cost metrics.
    `--view session-agents` renders multi-agent session swimlanes.
    `cortxt widget action <id>` dispatches a registered authorized action
    through ActionExecutor with the operator gate.
    """
    try:
        is_tui = getattr(args, "tui", False) or getattr(args, "format", None) == "tui"
        force_ansi = True if getattr(args, "tui", False) else (None if getattr(args, "format", None) == "tui" else False)
        truecolor = bool(getattr(args, "tui_truecolor", False))
        view = getattr(args, "view", None)
        if view == "session-pulse":
            ap_path = _get_agent_platform_path()
            if str(ap_path) not in sys.path:
                sys.path.insert(0, str(ap_path))
            from widget_contract.adapters.store_reads import read_snapshot_v2
            from widget_contract.loader import load_widget_file
            from widget_contract.renderer import render
            widget = load_widget_file(ap_path / "widget_contract" / "specs" / "session-pulse-0.1.yaml")
            snapshot_path = getattr(args, "snapshot_input", None) or (ap_path / "widget" / "snapshot.json")
            try:
                snapshot = json.loads(Path(snapshot_path).read_text(encoding="utf-8"))
                projection = read_snapshot_v2(snapshot)
                source_status = "fresh"
                error = None
            except (OSError, ValueError) as exc:
                projection = {}
                source_status = "error"
                error = {"kind": "snapshot_read", "message": str(exc)}
            if error is None:
                tree = render(widget, {"snapshot": projection}, {"snapshot": source_status})
            else:
                from widget_contract.primitives import render_primitive
                tree = {"contract_version": widget.contract_version,
                        "widget": {"id": widget.id, "version": widget.version},
                        "render": render_primitive("error-state",
                                                   {"message": f"Snapshot read failed: {error['message']}"},
                                                   [], "error")}
            output_path = getattr(args, "snapshot", None) or (ap_path / "widget" / "session-pulse.json")
            artifact = {**tree, "repo": None, "error": error}
            _write_widget_artifact(artifact, output_path)
            if is_tui:
                from widget_contract.tui import render_tui
                print(render_tui(tree, force_ansi=force_ansi, truecolor=truecolor))
            else:
                stdout_tree = {**tree["render"], "children": [node for node in tree["render"].get("children", [])
                                                               if node["primitive"] == "table"]}
                print(json.dumps(stdout_tree, indent=2))
            return ResultEnvelope(status="succeeded", artifacts=[f"session-pulse:{output_path}"],
                                  evidence=[{"session_pulse": tree}])
        if view == "execution-map":
            ap_path = _get_agent_platform_path()
            if str(ap_path) not in sys.path:
                sys.path.insert(0, str(ap_path))
            from widget_contract.adapters.store_reads import read_execution_map_v1
            from widget_contract.loader import load_widget_file
            from widget_contract.renderer import render
            widget = load_widget_file(ap_path / "widget_contract" / "specs" / "execution-map-0.1.yaml")
            plan_input = getattr(args, "plan_input", None)
            if not plan_input:
                return ResultEnvelope(status="failed", error={"category": "input_error",
                                                              "message": "--plan-input is required for execution-map"})
            try:
                store = json.loads(Path(plan_input).read_text(encoding="utf-8"))
                scripts = ap_path.parent / "scripts"
                if str(scripts) not in sys.path:
                    sys.path.insert(0, str(scripts))
                from execution_map import plan_from_json
                projection = read_execution_map_v1(plan_from_json, store)
                source_status = "fresh"
                error = None
            except (OSError, ValueError) as exc:
                projection = {}
                source_status = "error"
                error = {"kind": "plan_read", "message": str(exc)}
            if error is None:
                tree = render(widget, {"plan": projection}, {"plan": source_status})
            else:
                from widget_contract.primitives import render_primitive
                tree = {"contract_version": widget.contract_version,
                        "widget": {"id": widget.id, "version": widget.version},
                        "render": render_primitive("error-state",
                                                   {"message": f"Plan read failed: {error['message']}"},
                                                   [], "error")}
            output_path = getattr(args, "snapshot", None) or (ap_path / "widget" / "execution-map.json")
            artifact = {**tree, "repo": None, "error": error}
            _write_widget_artifact(artifact, output_path)
            if is_tui:
                from widget_contract.tui import render_tui
                print(render_tui(tree, force_ansi=force_ansi, truecolor=truecolor))
            else:
                stdout_tree = {**tree["render"], "children": [node for node in tree["render"].get("children", [])
                                                               if node["primitive"] in ("table", "list")]}
                print(json.dumps(stdout_tree, indent=2))
            return ResultEnvelope(status="succeeded", artifacts=[f"execution-map:{output_path}"],
                                  evidence=[{"execution_map": tree}])
        if view == "docker-status":
            ap_path = _get_agent_platform_path()
            if str(ap_path) not in sys.path:
                sys.path.insert(0, str(ap_path))
            from widget_contract.adapters.store_reads import read_docker_status_v1
            from widget_contract.loader import load_widget_file
            from widget_contract.renderer import render
            widget = load_widget_file(ap_path / "widget_contract" / "specs" / "docker-status-0.1.yaml")
            reader = docker_reader or getattr(args, "docker_reader", None) or _default_docker_reader
            try:
                raw_data = reader()
                projection = read_docker_status_v1(raw_data)
                source_status = "fresh"
                error = None
            except (OSError, ValueError, Exception) as exc:
                projection = {}
                source_status = "error"
                error = {"kind": "docker_read", "message": str(exc)}
            if error is None:
                tree = render(widget, {"docker": projection}, {"docker": source_status})
            else:
                from widget_contract.primitives import render_primitive
                tree = {"contract_version": widget.contract_version,
                        "widget": {"id": widget.id, "version": widget.version},
                        "render": render_primitive("error-state",
                                                   {"message": f"Docker read failed: {error['message']}"},
                                                   [], "error")}
            output_path = getattr(args, "snapshot", None) or (ap_path / "widget" / "docker-status.json")
            artifact = {**tree, "repo": None, "error": error}
            _write_widget_artifact(artifact, output_path)
            if is_tui:
                from widget_contract.tui import render_tui
                print(render_tui(tree, force_ansi=force_ansi, truecolor=truecolor))
            else:
                stdout_tree = {**tree["render"], "children": [node for node in tree["render"].get("children", [])
                                                               if node["primitive"] in ("table", "list", "key-value", "metric")]}
                print(json.dumps(stdout_tree, indent=2))
            return ResultEnvelope(status="succeeded", artifacts=[f"docker-status:{output_path}"],
                                  evidence=[{"docker_status": tree}])
        if view == "webhooks":
            ap_path = _get_agent_platform_path()
            if str(ap_path) not in sys.path:
                sys.path.insert(0, str(ap_path))
            from widget_contract.adapters.store_reads import read_pages_deploys_v1, read_webhooks_status_v1, redact_hook
            from widget_contract.loader import load_widget_file
            from widget_contract.renderer import render
            repo = getattr(args, "repo", None)
            if not repo:
                return ResultEnvelope(status="failed", error={"category": "input_error",
                                                              "message": "--repo is required for webhooks"})
            widget = load_widget_file(ap_path / "widget_contract" / "specs" / "webhooks-0.1.yaml")
            try:
                hooks_raw = _gh_webhooks_reader(repo)
                safe_hooks = [redact_hook(h) for h in hooks_raw]
                webhooks_proj = read_webhooks_status_v1({
                    "schema_version": 1,
                    "repo": repo,
                    "total": len(safe_hooks),
                    "active": sum(1 for h in safe_hooks if h.get("active")),
                    "hooks": safe_hooks,
                })
                source_status = "fresh"
                error = None
            except Exception as exc:
                webhooks_proj = None
                source_status = "error"
                import re
                sanitized_msg = re.sub(r"(?:cfat|ghp|github_pat)_[a-zA-Z0-9_.-]+", "[REDACTED]", str(exc))
                error = {"kind": "webhooks_read", "message": sanitized_msg}

            try:
                pages_raw = _pages_deploys_reader()
                pages_proj = read_pages_deploys_v1(pages_raw)
                pages_status = "fresh"
            except Exception:
                pages_proj = {
                    "schema_version": 1,
                    "project": "cortxt",
                    "account": "c7c04f119f81234dc3d851bf6ff2adfe",
                    "latest": {"id": "none", "environment": "none", "created_on": "none", "stage": "none", "status": "none"},
                    "deployments": [],
                }
                pages_status = "stale"

            if error is None:
                tree = render(widget, {"webhooks": webhooks_proj, "pages": pages_proj},
                              {"webhooks": source_status, "pages": pages_status})
            else:
                from widget_contract.primitives import render_primitive
                tree = {
                    "contract_version": widget.contract_version,
                    "widget": {"id": widget.id, "version": widget.version},
                    "render": render_primitive("error-state",
                                               {"message": f"Webhooks read failed: {error['message']}"},
                                               [], "error"),
                }
            output_path = getattr(args, "snapshot", None) or (ap_path / "widget" / "webhooks.json")
            artifact = {**tree, "repo": repo, "error": error}
            _write_widget_artifact(artifact, output_path)
            if is_tui:
                from widget_contract.tui import render_tui
                print(render_tui(tree, force_ansi=force_ansi, truecolor=truecolor))
            else:
                stdout_tree = {**tree["render"], "children": [node for node in tree["render"].get("children", [])
                                                               if node["primitive"] in ("table", "metric", "key-value")]}
                print(json.dumps(stdout_tree, indent=2))
            return ResultEnvelope(status="succeeded", artifacts=[f"webhooks:{output_path}"],
                                  evidence=[{"webhooks": tree}])
        if view == "pages-deploys":
            ap_path = _get_agent_platform_path()
            if str(ap_path) not in sys.path:
                sys.path.insert(0, str(ap_path))
            from widget_contract.adapters.store_reads import read_pages_deploys_v1
            from widget_contract.loader import load_widget_file
            from widget_contract.renderer import render
            widget = load_widget_file(ap_path / "widget_contract" / "specs" / "webhooks-0.1.yaml")
            try:
                pages_raw = _pages_deploys_reader()
                pages_proj = read_pages_deploys_v1(pages_raw)
                pages_status = "fresh"
                error = None
            except Exception as exc:
                pages_proj = None
                pages_status = "error"
                import re
                sanitized_msg = re.sub(r"(?:cfat|ghp|github_pat)_[a-zA-Z0-9_.-]+", "[REDACTED]", str(exc))
                error = {"kind": "pages_read", "message": sanitized_msg}

            if error is None:
                webhooks_empty = {"schema_version": 1, "repo": "", "total": 0, "active": 0, "hooks": []}
                tree = render(widget, {"webhooks": webhooks_empty, "pages": pages_proj},
                              {"webhooks": "stale", "pages": pages_status})
            else:
                from widget_contract.primitives import render_primitive
                tree = {
                    "contract_version": widget.contract_version,
                    "widget": {"id": widget.id, "version": widget.version},
                    "render": render_primitive("error-state",
                                               {"message": f"Pages read failed: {error['message']}"},
                                               [], "error"),
                }
            output_path = getattr(args, "snapshot", None) or (ap_path / "widget" / "pages-deploys.json")
            artifact = {**tree, "repo": None, "error": error}
            _write_widget_artifact(artifact, output_path)
            if is_tui:
                from widget_contract.tui import render_tui
                print(render_tui(tree, force_ansi=force_ansi, truecolor=truecolor))
            else:
                stdout_tree = {**tree["render"], "children": [node for node in tree["render"].get("children", [])
                                                               if node["primitive"] in ("table", "key-value")]}
                print(json.dumps(stdout_tree, indent=2))
            return ResultEnvelope(status="succeeded", artifacts=[f"pages-deploys:{output_path}"],
                                  evidence=[{"pages_deploys": tree}])
        if view == "usage-cost":
            ap_path = _get_agent_platform_path()
            if str(ap_path) not in sys.path:
                sys.path.insert(0, str(ap_path))
            from widget_contract.adapters.store_reads import read_usage_cost_v1
            from widget_contract.loader import load_widget_file
            from widget_contract.renderer import render
            widget = load_widget_file(ap_path / "widget_contract" / "specs" / "usage-cost-0.1.yaml")
            reader = usage_reader or getattr(args, "usage_reader", None) or _default_usage_reader
            try:
                raw_data = reader() if callable(reader) else reader
                projection = read_usage_cost_v1(raw_data)
                source_status = "fresh"
                error = None
            except (OSError, ValueError, Exception) as exc:
                projection = {}
                source_status = "error"
                error = {"kind": "usage_cost_read", "message": str(exc)}
            if error is None:
                tree = render(widget, {"usage": projection}, {"usage": source_status})
            else:
                from widget_contract.primitives import render_primitive
                tree = {"contract_version": widget.contract_version,
                        "widget": {"id": widget.id, "version": widget.version},
                        "render": render_primitive("error-state",
                                                   {"message": f"Usage cost read failed: {error['message']}"},
                                                   [], "error")}
            output_path = getattr(args, "snapshot", None) or (ap_path / "widget" / "usage-cost.json")
            artifact = {**tree, "repo": None, "error": error}
            _write_widget_artifact(artifact, output_path)
            if is_tui:
                from widget_contract.tui import render_tui
                print(render_tui(tree, force_ansi=force_ansi, truecolor=truecolor))
            else:
                stdout_tree = {**tree["render"], "children": [node for node in tree["render"].get("children", [])
                                                               if node["primitive"] in ("metric", "bar", "line", "table", "list", "key-value")]}
                print(json.dumps(stdout_tree, indent=2))
            return ResultEnvelope(status="succeeded", artifacts=[f"usage-cost:{output_path}"],
                                  evidence=[{"usage_cost": tree}])
        if view == "session-agents":
            ap_path = _get_agent_platform_path()
            if str(ap_path) not in sys.path:
                sys.path.insert(0, str(ap_path))
            from widget_contract.adapters.store_reads import read_session_agents_v1
            from widget_contract.loader import load_widget_file
            from widget_contract.renderer import render
            widget = load_widget_file(ap_path / "widget_contract" / "specs" / "session-agents-0.1.yaml")
            reader = agents_reader or getattr(args, "agents_reader", None) or _default_session_agents_reader
            try:
                raw_data = reader() if callable(reader) else reader
                projection = read_session_agents_v1(raw_data)
                source_status = "fresh"
                error = None
            except (OSError, ValueError, Exception) as exc:
                projection = {}
                source_status = "error"
                error = {"kind": "session_agents_read", "message": str(exc)}
            if error is None:
                tree = render(widget, {"agents": projection}, {"agents": source_status})
            else:
                from widget_contract.primitives import render_primitive
                tree = {"contract_version": widget.contract_version,
                        "widget": {"id": widget.id, "version": widget.version},
                        "render": render_primitive("error-state",
                                                   {"message": f"Session agents read failed: {error['message']}"},
                                                   [], "error")}
            output_path = getattr(args, "snapshot", None) or (ap_path / "widget" / "session-agents.json")
            artifact = {**tree, "repo": None, "error": error}
            _write_widget_artifact(artifact, output_path)
            if is_tui:
                from widget_contract.tui import render_tui
                print(render_tui(tree, force_ansi=force_ansi, truecolor=truecolor))
            else:
                stdout_tree = {**tree["render"], "children": [node for node in tree["render"].get("children", [])
                                                               if node["primitive"] in ("table", "list", "key-value", "metric", "swimlane")]}
                print(json.dumps(stdout_tree, indent=2))
            return ResultEnvelope(status="succeeded", artifacts=[f"session-agents:{output_path}"],
                                  evidence=[{"session_agents": tree}])
        if view == "attention-queue":
            ap_path = _get_agent_platform_path()
            if str(ap_path) not in sys.path:
                sys.path.insert(0, str(ap_path))
            from widget_contract.adapters.store_reads import read_attention_queue_v1
            from widget_contract.loader import load_widget_file
            from widget_contract.renderer import render
            widget = load_widget_file(ap_path / "widget_contract" / "specs" / "attention-queue-0.1.yaml")
            reader = attention_queue_reader or getattr(args, "attention_queue_reader", None)
            if reader is None:
                return ResultEnvelope(status="failed", error={"category": "input_error",
                                                              "message": "attention-queue view requires an attention_queue_reader"})
            try:
                raw_data = reader() if callable(reader) else reader
                projection = read_attention_queue_v1(raw_data)
                source_status = "fresh"
                error = None
            except (OSError, ValueError) as exc:
                projection = {}
                source_status = "error"
                error = {"kind": "attention_queue_read", "message": str(exc)}
            if error is None:
                tree = render(widget, {"queue": projection}, {"queue": source_status})
            else:
                from widget_contract.primitives import render_primitive
                tree = {"contract_version": widget.contract_version,
                        "widget": {"id": widget.id, "version": widget.version},
                        "render": render_primitive("error-state",
                                                   {"message": f"Attention queue read failed: {error['message']}"},
                                                   [], "error")}
            output_path = getattr(args, "snapshot", None) or (ap_path / "widget" / "attention-queue.json")
            artifact = {**tree, "repo": None, "error": error}
            _write_widget_artifact(artifact, output_path)
            if is_tui:
                from widget_contract.tui import render_tui
                print(render_tui(tree, force_ansi=force_ansi, truecolor=truecolor))
            else:
                stdout_tree = {**tree["render"], "children": [node for node in tree["render"].get("children", [])
                                                               if node["primitive"] in ("heading", "text", "badge", "metric", "key-value", "list", "table")]}
                print(json.dumps(stdout_tree, indent=2))
            return ResultEnvelope(status="succeeded", artifacts=[f"attention-queue:{output_path}"],
                                  evidence=[{"attention_queue": tree}])
        if view == "work-console":
            ap_path = _get_agent_platform_path()
            if str(ap_path) not in sys.path:
                sys.path.insert(0, str(ap_path))
            from widget_contract.adapters.store_reads import read_workstream_summary_v1
            from widget_contract.loader import load_widget_file
            from widget_contract.renderer import render
            widget = load_widget_file(ap_path / "widget_contract" / "specs" / "work-console-0.1.yaml")
            reader = workstream_reader or getattr(args, "workstream_reader", None)
            if reader is None:
                return ResultEnvelope(status="failed", error={"category": "input_error",
                                                              "message": "work-console view requires a workstream_reader"})
            try:
                raw_data = reader() if callable(reader) else reader
                projection = read_workstream_summary_v1(raw_data)
                source_status = "fresh"
                error = None
            except (OSError, ValueError) as exc:
                projection = {}
                source_status = "error"
                error = {"kind": "workstream_summary_read", "message": str(exc)}
            if error is None:
                tree = render(widget, {"summary": projection}, {"summary": source_status})
            else:
                from widget_contract.primitives import render_primitive
                tree = {"contract_version": widget.contract_version,
                        "widget": {"id": widget.id, "version": widget.version},
                        "render": render_primitive("error-state",
                                                   {"message": f"Workstream summary read failed: {error['message']}"},
                                                   [], "error")}
            output_path = getattr(args, "snapshot", None) or (ap_path / "widget" / "work-console.json")
            artifact = {**tree, "repo": None, "error": error}
            _write_widget_artifact(artifact, output_path)
            if is_tui:
                from widget_contract.tui import render_tui
                print(render_tui(tree, force_ansi=force_ansi, truecolor=truecolor))
            else:
                stdout_tree = {**tree["render"], "children": [node for node in tree["render"].get("children", [])
                                                               if node["primitive"] in ("heading", "text", "badge", "metric", "key-value", "list", "table")]}
                print(json.dumps(stdout_tree, indent=2))
            return ResultEnvelope(status="succeeded", artifacts=[f"work-console:{output_path}"],
                                  evidence=[{"work_console": tree}])
        if view == "evidence":
            ap_path = _get_agent_platform_path()
            if str(ap_path) not in sys.path:
                sys.path.insert(0, str(ap_path))
            from widget_contract.adapters.store_reads import read_evidence_comparison_v1
            from widget_contract.loader import load_widget_file
            from widget_contract.renderer import render
            widget = load_widget_file(ap_path / "widget_contract" / "specs" / "evidence-0.1.yaml")
            reader = evidence_reader or getattr(args, "evidence_reader", None)
            if reader is None:
                return ResultEnvelope(status="failed", error={"category": "input_error",
                                                              "message": "evidence view requires an evidence_reader"})
            try:
                raw_data = reader() if callable(reader) else reader
                projection = read_evidence_comparison_v1(raw_data)
                source_status = "fresh"
                error = None
            except (OSError, ValueError) as exc:
                projection = {}
                source_status = "error"
                error = {"kind": "evidence_comparison_read", "message": str(exc)}
            if error is None:
                tree = render(widget, {"comparison": projection}, {"comparison": source_status})
            else:
                from widget_contract.primitives import render_primitive
                tree = {"contract_version": widget.contract_version,
                        "widget": {"id": widget.id, "version": widget.version},
                        "render": render_primitive("error-state",
                                                   {"message": f"Evidence comparison read failed: {error['message']}"},
                                                   [], "error")}
            output_path = getattr(args, "snapshot", None) or (ap_path / "widget" / "evidence.json")
            artifact = {**tree, "repo": None, "error": error}
            _write_widget_artifact(artifact, output_path)
            if is_tui:
                from widget_contract.tui import render_tui
                print(render_tui(tree, force_ansi=force_ansi, truecolor=truecolor))
            else:
                stdout_tree = {**tree["render"], "children": [node for node in tree["render"].get("children", [])
                                                               if node["primitive"] in ("table", "text", "badge", "key-value")]}
                print(json.dumps(stdout_tree, indent=2))
            return ResultEnvelope(status="succeeded", artifacts=[f"evidence:{output_path}"],
                                  evidence=[{"evidence": tree}])
        if view == "decisions":
            ap_path = _get_agent_platform_path()
            if str(ap_path) not in sys.path:
                sys.path.insert(0, str(ap_path))
            from widget_contract.adapters.store_reads import read_decision_pending_v1
            from widget_contract.loader import load_widget_file
            from widget_contract.renderer import render
            widget = load_widget_file(ap_path / "widget_contract" / "specs" / "decisions-0.1.yaml")
            reader = decision_reader or getattr(args, "decision_reader", None)
            if reader is None:
                return ResultEnvelope(status="failed", error={"category": "input_error",
                                                              "message": "decisions view requires a decision_reader"})
            try:
                raw_data = reader() if callable(reader) else reader
                projection = read_decision_pending_v1(raw_data)
                source_status = "fresh"
                error = None
            except (OSError, ValueError) as exc:
                projection = {}
                source_status = "error"
                error = {"kind": "decision_pending_read", "message": str(exc)}
            if error is None:
                tree = render(widget, {"pending": projection}, {"pending": source_status})
            else:
                from widget_contract.primitives import render_primitive
                tree = {"contract_version": widget.contract_version,
                        "widget": {"id": widget.id, "version": widget.version},
                        "render": render_primitive("error-state",
                                                   {"message": f"Decision pending read failed: {error['message']}"},
                                                   [], "error")}
            output_path = getattr(args, "snapshot", None) or (ap_path / "widget" / "decisions.json")
            artifact = {**tree, "repo": None, "error": error}
            _write_widget_artifact(artifact, output_path)
            if is_tui:
                from widget_contract.tui import render_tui
                print(render_tui(tree, force_ansi=force_ansi, truecolor=truecolor))
            else:
                stdout_tree = {**tree["render"], "children": [node for node in tree["render"].get("children", [])
                                                               if node["primitive"] in ("text", "badge")]}
                print(json.dumps(stdout_tree, indent=2))
            return ResultEnvelope(status="succeeded", artifacts=[f"decisions:{output_path}"],
                                  evidence=[{"decisions": tree}])
        candidate_mode = getattr(args, "widget_command", None) == "candidates" or view == "candidates"
        if candidate_mode:
            ap_path = _get_agent_platform_path()
            if str(ap_path) not in sys.path:
                sys.path.insert(0, str(ap_path))
            from widget_contract.adapters.github_ports import read_candidates_view
            from widget_contract.loader import load_widget_file
            from widget_contract.renderer import render
            repo = getattr(args, "repo", None)
            if not repo:
                return ResultEnvelope(status="failed", error={"category": "input_error", "message": "--repo is required for candidates"})
            widget = load_widget_file(ap_path / "widget_contract" / "specs" / "candidates-0.1.yaml")
            action_descriptors = [{"id": a.id, "operation": a.operation, "port": a.port,
                                   "effect_class": a.confirm["effect_class"],
                                   "authorization": dict(a.authorization), "confirm": dict(a.confirm)}
                                  for a in widget.actions]
            model = read_candidates_view(repo, actions=action_descriptors)
            source_status = model["source"]["status"]
            tree = render(widget, {"candidates": model}, {"candidates": source_status})
            output_path = getattr(args, "snapshot", None) or (ap_path / "widget" / "candidates.json")
            artifact = {**tree, "handoffs": model["handoffs"], "repo": repo}
            _write_widget_artifact(artifact, output_path)
            if is_tui:
                from widget_contract.tui import render_tui
                print(render_tui(tree, force_ansi=force_ansi, truecolor=truecolor))
            elif getattr(args, "widget_command", None) is None:
                stdout_tree = {**tree["render"], "children": [node for node in tree["render"]["children"]
                                                               if node["primitive"] == "table"]}
                print(json.dumps(stdout_tree, indent=2))
            elif getattr(args, "format", None) == "json":
                print(json.dumps(model, indent=2))
            else:
                for group in model["groups"]:
                    print(f"{group['id']} ({group['count']})")
                    for row in group["rows"]:
                        area = f" | {row['area']}" if row["area"] else ""
                        milestone = f" | {row['milestone']}" if row["milestone"] else ""
                        print(f"  #{row['number']} {row['title']} | {row['workflow']}{area}{milestone} | blockers:{row['open_blocker_count']}")
            artifacts = [f"candidates:{output_path}"] if getattr(args, "widget_command", None) is None else []
            return ResultEnvelope(status="succeeded", artifacts=artifacts, evidence=[{"candidates": model}])
        if getattr(args, "widget_command", None) == "action":
            return _run_widget_action(args)
        if getattr(args, "widget_command", None) == "export":
            return _run_widget_export(args)
        if getattr(args, "widget_command", None) == "load":
            return _run_widget_load(args)
        if getattr(args, "widget_command", None) == "compose":
            return _run_widget_compose(args)
        if getattr(args, "widget_command", None) == "generate":
            return _run_widget_generate(args)
        if getattr(args, "widget_command", None) == "edit":
            return _run_widget_edit(args)
        if getattr(args, "widget_command", None) == "remove":
            return _run_widget_remove(args)
        if getattr(args, "widget_command", None) == "reset":
            return _run_widget_reset(args)
        ap_path = _get_agent_platform_path()
        if str(ap_path) not in sys.path:
            sys.path.insert(0, str(ap_path))
        if getattr(args, "enable_actions", False):
            # ADR-038 host boundary: the operator-gated mutation endpoint lives in
            # action_host.py, not the read-only serve.py surface.
            from widget import action_host
            # --require-commit is opt-in (default None): ordinary local
            # `cortxt widget --enable-actions` usage is unaffected. Proof/
            # gated-launch tooling passes it explicitly to fail closed
            # against a stale checkout or wrong worktree/commit (S7b dogfood
            # defect: an installed cortxt.exe silently ran stale code) --
            # this is a proof-tooling-set flag, not a blanket requirement on
            # every widget start.
            action_host.main(require_commit=getattr(args, "require_commit", None),
                             require_clean=getattr(args, "require_clean", False))
        else:
            from widget import serve as widget_serve
            widget_serve.main()
        return ResultEnvelope(status="succeeded", artifacts=["widget:stopped"])
    except Exception as e:
        return ResultEnvelope(status="failed", error={"category": "runtime_error", "message": str(e)})


def _gh_issue_workflow_labels(issue_id: str) -> list[str]:
    """Read an issue's workflow labels via gh (shared default, injectable for tests)."""
    from widget_contract.adapters.github_ports import gh_issue_workflow_labels
    return gh_issue_workflow_labels(issue_id)


def _gh_inbox_to_ready(issue_id: str) -> dict:
    """Perform exactly the inbox -> ready label swap via gh (shared default, injectable for tests)."""
    from widget_contract.adapters.github_ports import gh_inbox_to_ready
    return gh_inbox_to_ready(issue_id)


def _gh_review_to_done(issue_id: str) -> dict:
    """Perform exactly the review -> done label swap via gh (shared default, injectable for tests)."""
    from widget_contract.adapters.github_ports import gh_review_to_done
    return gh_review_to_done(issue_id)


def _claim_run_resume(issue_id: str, *, registry: Path, approval_ref: str | None = None) -> dict:
    """Resume a ready issue through the execution-map-gated launcher (shared default, injectable for tests).

    `approval_ref` is the operator-provided approval reference; the launcher
    binds it to the issue-derived dispatch-request approval reference (AC8).
    """
    from widget_contract.adapters.cli_ports import gh_claim_run_resume
    return gh_claim_run_resume(issue_id, registry=registry,
                               scripts_dir=_get_agent_platform_path().parent / "scripts",
                               approval_ref=approval_ref)


def _gh_webhooks_reader(repo: str) -> list[dict]:
    """Read repo webhooks via gh api (shared default, injectable for tests)."""
    import subprocess
    cmd = ["gh", "api", f"repos/{repo}/hooks", "--paginate"]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if proc.returncode != 0:
        raise RuntimeError(f"gh api repos/{repo}/hooks failed: {proc.stderr.strip()}")
    data = json.loads(proc.stdout)
    if not isinstance(data, list):
        raise ValueError("expected list of hooks from gh api")
    return data


def _pages_deploys_reader(account: str = "c7c04f119f81234dc3d851bf6ff2adfe",
                          project: str = "cortxt") -> dict:
    """Read Cloudflare Pages deployment state (shared default, injectable for tests)."""
    import os
    import subprocess
    import urllib.error
    import urllib.request

    store_dir = os.path.expandvars(r"%USERPROFILE%\.cortxt\credentials")
    proc = subprocess.run(
        ["cortxt", "credentials", "inject", "--id", "cloudflare",
         "--store-dir", store_dir, "--runtime", "coordinator", "--purpose", "widget-pages-status"],
        capture_output=True, text=True, timeout=60,
    )
    token = next((line.strip() for line in (proc.stdout or "").splitlines()
                  if line.startswith("cfat_")), "")
    if not token:
        raise RuntimeError("Cloudflare credential unavailable (no cfat_ token)")

    url = f"https://api.cloudflare.com/client/v4/accounts/{account}/pages/projects/{project}/deployments"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Cloudflare API HTTP {exc.code}") from exc
    except Exception as exc:
        raise RuntimeError(f"Cloudflare request failed: {exc}") from exc

    if not body.get("success"):
        errors = body.get("errors") or [{}]
        err_msg = errors[0].get("message", "Cloudflare API returned success=false")
        raise RuntimeError(f"Cloudflare API error: {err_msg}")

    raw_deployments = body.get("result") or []
    safe_deployments = []
    for dep in raw_deployments:
        if isinstance(dep, dict):
            stage = ""
            if "latest_stage" in dep and isinstance(dep["latest_stage"], dict):
                stage = dep["latest_stage"].get("name") or dep["latest_stage"].get("status") or ""
            if not stage:
                stage = str(dep.get("stage") or "deploy")
            safe_deployments.append({
                "id": str(dep.get("id") or ""),
                "environment": str(dep.get("environment") or ""),
                "created_on": str(dep.get("created_on") or ""),
                "stage": stage,
            })

    latest_obj = {"id": "none", "environment": "none", "created_on": "none", "stage": "none", "status": "none"}
    if safe_deployments:
        first_raw = raw_deployments[0] if isinstance(raw_deployments[0], dict) else {}
        first_stage = safe_deployments[0]["stage"]
        first_status = ""
        if "latest_stage" in first_raw and isinstance(first_raw["latest_stage"], dict):
            first_status = first_raw["latest_stage"].get("status") or ""
        if not first_status:
            first_status = str(first_raw.get("status") or "success")
        latest_obj = {
            "id": safe_deployments[0]["id"],
            "environment": safe_deployments[0]["environment"],
            "created_on": safe_deployments[0]["created_on"],
            "stage": first_stage,
            "status": first_status,
        }

    return {
        "schema_version": 1,
        "project": project,
        "account": account,
        "latest": latest_obj,
        "deployments": safe_deployments,
    }


def _run_widget_action(args: argparse.Namespace) -> ResultEnvelope:
    """Execute a registered widget action through ActionExecutor with the operator gate.

    Loads the candidates spec, builds the Action from the declared action and
    CLI input, and dispatches through ActionExecutor with the registered
    github-transition and cli adapters. The authorize callback enforces the
    operator approval reference plus the declared confirm requirement; the
    execution-map gate (claim-run) reports its stable codes on rejection.
    """
    try:
        ap_path = _get_agent_platform_path()
        if str(ap_path) not in sys.path:
            sys.path.insert(0, str(ap_path))
        from widget_contract.action_executor import AuthorizationDenied
        from widget_contract.action_ports import build_action, build_executor
        from widget_contract.adapters.cli_ports import ClaimRunDenied
        from widget_contract.adapters.github_ports import TransitionDenied
        from widget_contract.loader import load_widget_file

        widget = load_widget_file(ap_path / "widget_contract" / "specs" / "candidates-0.1.yaml")
        declared = next((a for a in widget.actions if a.id == args.action_id), None)
        if declared is None:
            return ResultEnvelope(status="failed", error={"category": "input_error",
                                                          "message": f"unknown action {args.action_id}"})
        issue_id = f"{args.repo}#{args.issue}"
        registry = getattr(args, "registry", None) or (ap_path / ".dispatch" / "runs.json")
        action = build_action(widget, args.action_id, issue_id, args.approval_ref, args.confirm)
        executor, context = build_executor(
            widget, action_id=args.action_id, approval_ref=args.approval_ref, confirm=args.confirm,
            labels_reader=_gh_issue_workflow_labels, transition_writer=_gh_inbox_to_ready,
            review_transition_writer=_gh_review_to_done,
            resume=lambda issue_id: _claim_run_resume(issue_id, registry=registry,
                                                      approval_ref=args.approval_ref))
        result = executor.execute(action, context)
        print(json.dumps(result, indent=2))
        return ResultEnvelope(status="succeeded", issue_id=issue_id, evidence=[{"action": result}])
    except AuthorizationDenied as exc:
        return ResultEnvelope(status="failed", error={"category": "authorization_denied", "message": str(exc)})
    except (TransitionDenied, ClaimRunDenied) as exc:
        return ResultEnvelope(status="failed", error={"category": "action_denied", "message": str(exc)})
    except Exception as exc:
        if exc.__class__.__name__ == "ExecutionGateError" and hasattr(exc, "code"):
            return ResultEnvelope(status="failed", error={"category": "execution_map_gate",
                                                           "code": exc.code, "message": exc.code})
        return ResultEnvelope(status="failed", error={"category": "action_error", "message": str(exc)})


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
    a hardcoded if/elif on engine_id. The verified engine id is `claude`,
    backed by the live-verified headless `claude -p` ClaudeAdapter
    (2026-08-20). Any engine_id with no registered adapter is recorded as
    "blocked" -- never silently dispatched to whatever IS registered.

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
            # The profile string is a Hermes concept. Forward it only to the
            # Hermes-family adapters; claude/dsh take no profile, so passing
            # "builder" would reach ClaudeAdapter's --agent mapping and emit a
            # bogus `claude --agent builder`.
            profile = hermes_profile if choice.engine_id in ("hermes", "hermes-free") else None
            result = broker.invoke(
                profile, args.prompt, timeout_seconds=args.timeout,
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


class _InspectNonceStore:
    """In-memory nonce store for `cortxt mandate inspect`: accepts every
    nonce exactly once within one process, never touches the durable
    nonce store, so inspection is read-only and deterministic."""

    def __init__(self) -> None:
        self._seen: set[str] = set()

    def check_and_consume(self, nonce: str) -> bool:
        if nonce in self._seen:
            return False
        self._seen.add(nonce)
        return True


class _InspectBudgetStore:
    """In-memory budget store for `cortxt mandate inspect`: accepts every
    debit within the envelope's own cap, never touches the durable budget
    store."""

    def record_and_check(self, mandate_id: str | None, cost: float, cap: float) -> bool:
        return bool(cap >= 0 and cost <= cap)


class _InspectRevocationStore:
    """Permissive revocation store for `cortxt mandate inspect`: never
    revokes (a read-only inspection must not be affected by durable
    revocation state)."""

    def is_revoked(self, granted_by: str, kid: str, at) -> bool:  # noqa: ARG002
        return False


def _run_mandate(args: argparse.Namespace) -> ResultEnvelope:
    """`cortxt mandate` -- operator-side issuance and inspection of
    ADR-032 mandate envelopes.

    `issue` builds and signs one v1 envelope via
    `cortxt_mcp.mandate.issue_mandate`, persisting the signing private key
    in the credential broker (ADR-029) on first use (`--confirm`); the
    private key is never printed -- the envelope JSON and the public key
    hex (for `CORTXT_MCP_MANDATE_PUBLIC_KEYS`) are the output.

    `inspect` validates an envelope's schema and signature against a
    supplied public key, plus its internal consistency (issue_ref, data
    class, scope fingerprint, expiry) -- deterministic, read-only, with no
    durable nonce/budget/revocation state touched.
    """
    try:
        ap_path = _get_agent_platform_path()
        if str(ap_path) not in sys.path:
            sys.path.insert(0, str(ap_path))
        from cortxt_mcp.mandate import (
            CallContext,
            MandateVerifier,
            issue_mandate,
            load_signing_key_from_broker,
            public_key_hex_from_private_key,
            store_signing_key_in_broker,
        )
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from security.credential_broker import CredentialBroker, CredentialNotFoundError

        if args.mandate_command == "issue":
            store_dir = getattr(args, "store_dir", None) or (ap_path / ".credentials")
            broker = CredentialBroker.with_dpapi(store_dir)
            allowed_tools = [t.strip() for t in args.allowed_tools.split(",") if t.strip()]
            if not allowed_tools:
                return ResultEnvelope(status="failed", error={
                    "category": "invalid_args",
                    "message": "allowed_tools must be a non-empty comma-separated list"})
            if args.budget_usd_max <= 0:
                return ResultEnvelope(status="failed", error={
                    "category": "invalid_args", "message": "budget_usd_max must be positive"})
            if args.max_runtime_seconds <= 0:
                return ResultEnvelope(status="failed", error={
                    "category": "invalid_args", "message": "max_runtime_seconds must be positive"})

            # Load the existing signing key for (granted_by, kid) if one was
            # persisted before (idempotent re-issue); otherwise generate a
            # fresh keypair. Persisting a *new* key requires --confirm (the
            # broker's operator-confirmed write gate, ADR-029).
            try:
                private_key = load_signing_key_from_broker(
                    granted_by=args.granted_by, kid=args.kid, broker=broker,
                    purpose="issue_mandate",
                )
                key_persisted = True
            except CredentialNotFoundError:
                if not args.confirm:
                    return ResultEnvelope(status="failed", error={
                        "category": "not_confirmed",
                        "message": "no signing key exists for this granted_by/kid; "
                                   "pass --confirm to generate and persist a fresh keypair"})
                private_key = Ed25519PrivateKey.generate()
                pem = private_key.private_bytes(
                    encoding=serialization.Encoding.PEM,
                    format=serialization.PrivateFormat.PKCS8,
                    encryption_algorithm=serialization.NoEncryption(),
                )
                store_signing_key_in_broker(pem, granted_by=args.granted_by, kid=args.kid, broker=broker)
                key_persisted = True

            public_key_hex = public_key_hex_from_private_key(private_key)
            issued = issue_mandate(
                granted_by=args.granted_by,
                kid=args.kid,
                public_keys={args.granted_by: {args.kid: public_key_hex}},
                issue_ref=args.issue_ref,
                allowed_tools=allowed_tools,
                data_class_max=args.data_class_max,
                budget_usd_max=args.budget_usd_max,
                max_runtime_seconds=args.max_runtime_seconds,
                expires_at=args.expires_at,
                scope_text=args.scope_text,
                private_key=private_key,
                max_envelope_ttl_seconds=args.max_envelope_ttl_seconds,
            )
            envelope = issued.envelope
            print(json.dumps(envelope, indent=2, sort_keys=True))
            return ResultEnvelope(
                status="succeeded",
                artifacts=[f"mandate:{envelope['mandate_id']}"],
                evidence=[{
                    "granted_by": args.granted_by, "kid": args.kid,
                    "public_key_hex": public_key_hex,
                    "mandate_id": envelope["mandate_id"],
                    "key_persisted": key_persisted,
                }],
            )

        if args.mandate_command == "inspect":
            envelope = json.loads(args.envelope.read_text(encoding="utf-8"))
            if not isinstance(envelope, dict):
                return ResultEnvelope(status="failed", error={
                    "category": "invalid_args", "message": "envelope must be a JSON object"})
            granted_by = envelope.get("granted_by")
            kid = envelope.get("kid")
            if not isinstance(granted_by, str) or not isinstance(kid, str):
                return ResultEnvelope(status="failed", error={
                    "category": "invalid_args", "message": "envelope missing granted_by/kid"})
            tool = envelope.get("allowed_tools", [])[0] if envelope.get("allowed_tools") else None
            verifier = MandateVerifier(
                public_keys={granted_by: {kid: args.public_key}},
                nonce_store=_InspectNonceStore(),
                budget_store=_InspectBudgetStore(),
                revocation_store=_InspectRevocationStore(),
            )
            decision = verifier.verify(
                envelope,
                tool=tool or "inspect",
                tier=1,
                call_context=CallContext(
                    issue_ref=envelope.get("issue_ref", ""),
                    data_class=envelope.get("data_class_max", "L0"),
                    expected_scope_fingerprint=envelope.get("scope_fingerprint"),
                ),
            )
            verdict = {
                "accepted": decision.accepted,
                "reason": decision.reason,
                "mandate_id": decision.mandate_id,
                "tool": tool,
            }
            print(json.dumps(verdict, indent=2, sort_keys=True))
            return ResultEnvelope(status="succeeded", evidence=[{"verdict": verdict}])

        return ResultEnvelope(status="failed", error={
            "category": "invalid_args", "message": f"unknown mandate_command: {args.mandate_command}"})
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
        # Worktrees are created from and workers are bound to the repository
        # containing this CLI, never the process cwd (#419).
        repo_path = _get_agent_platform_path().parent
        launcher = default_launcher(registry, repo_path=repo_path)
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
        if exc.__class__.__name__ == "ExecutionGateError" and hasattr(exc, "code"):
            return ResultEnvelope(status="failed", error={"category": "execution_map_gate",
                                                           "code": exc.code,
                                                           "message": exc.code})
        if exc.__class__.__name__ == "NestedDispatchForbidden":
            return ResultEnvelope(status="failed", error={"category": "nested_dispatch_forbidden",
                                                           "code": "nested_dispatch_forbidden",
                                                           "message": "refusing to dispatch a nested Run from inside a bounded worker"})
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

    # theme subcommand (issue #375)
    theme_parser = sub.add_parser("theme", help="List, inspect, preview, and select visual theme presets")
    theme_sub = theme_parser.add_subparsers(dest="theme_command", required=True)
    theme_list = theme_sub.add_parser("list", help="Show the available presets with id, name, and a short description")
    theme_list.add_argument("--path", type=Path, help="Preference file override (default: ~/.cortxt/theme.json)")
    theme_list.set_defaults(func=_run_theme)
    theme_inspect = theme_sub.add_parser("inspect", help="Print resolved token values (colors, typography) for a preset")
    theme_inspect.add_argument("preset", nargs="?", help="Preset id (default: the currently resolved theme)")
    theme_inspect.add_argument("--path", type=Path, help="Preference file override (default: ~/.cortxt/theme.json)")
    theme_inspect.set_defaults(func=_run_theme)
    theme_preview = theme_sub.add_parser("preview", help="Render an ANSI/truecolor sample using a preset (does not change the persisted selection)")
    theme_preview.add_argument("preset", nargs="?", help="Preset id (default: the currently resolved theme)")
    theme_preview.add_argument("--path", type=Path, help="Preference file override (default: ~/.cortxt/theme.json)")
    theme_preview.add_argument("--truecolor", action="store_true", help="Derive 24-bit ANSI colors directly from the preset's hex values")
    theme_preview.add_argument("--force-ansi", action="store_true", help="Force ANSI output even when stdout is not a TTY")
    theme_preview.add_argument(
        "--no-ansi",
        action="store_true",
        help="Force plain text output (no ANSI escape codes); takes precedence over --force-ansi if both are given",
    )
    theme_preview.set_defaults(func=_run_theme)
    theme_use = theme_sub.add_parser("use", help="Persist the theme preference for this user")
    theme_use.add_argument("preset", help="Preset id to persist")
    theme_use.add_argument("--path", type=Path, help="Preference file override (default: ~/.cortxt/theme.json)")
    theme_use.set_defaults(func=_run_theme)

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
    widget_parser.add_argument("--view", choices=["candidates", "session-pulse", "execution-map", "docker-status", "webhooks", "pages-deploys", "usage-cost", "session-agents", "work-console", "evidence", "decisions", "attention-queue"], help="Render a named read-only widget view")
    widget_parser.add_argument("--repo", help="GitHub owner/repo for a named view")
    widget_parser.add_argument("--snapshot", type=Path, help="Widget render output path")
    widget_parser.add_argument("--snapshot-input", type=Path, help="Snapshot input path for the session-pulse view")
    widget_parser.add_argument("--plan-input", type=Path, help="Execution-map plan input JSON for the execution-map view")
    widget_parser.add_argument("--enable-actions", action="store_true",
                               help="Mount the operator-gated mutation endpoint (POST /api/action) on the loopback host (ADR-038 host boundary); default remains read-only")
    widget_parser.add_argument("--require-commit", default=None,
                               help="With --enable-actions: fail closed at startup unless the running git commit "
                                    "matches exactly (opt-in source-integrity check for proof/gated-launch "
                                    "tooling; ordinary local widget use omits this and is unaffected)")
    widget_parser.add_argument("--require-clean", action="store_true",
                               help="With --enable-actions: fail closed at startup unless the worktree has no "
                                    "uncommitted changes (opt-in, pairs with --require-commit for proof/gated-"
                                    "launch tooling; ordinary local widget use omits this and is unaffected)")
    widget_parser.add_argument("--tui", action="store_true", help="Render token-styled TUI output (forces ANSI even if piped)")
    widget_parser.add_argument("--tui-truecolor", action="store_true",
                               help="With --tui: derive 24-bit ANSI colors directly from tokens.json hex values (requires a 24-bit-capable terminal)")
    widget_parser.add_argument("--format", choices=["table", "json", "tui"], default=None,
                               help="Output format for view output (default: table / json backward compatible)")
    widget_sub = widget_parser.add_subparsers(dest="widget_command")
    widget_candidates = widget_sub.add_parser("candidates", help="List the canonical actionable frontier and all open issues")
    widget_candidates.add_argument("--repo", required=True, help="GitHub owner/repo")
    widget_candidates.add_argument("--format", choices=["table", "json", "tui"], default="table")
    widget_candidates.add_argument("--tui", action="store_true", help="Render token-styled TUI output (forces ANSI even if piped)")
    widget_candidates.add_argument("--tui-truecolor", action="store_true",
                                   help="With --tui: derive 24-bit ANSI colors directly from tokens.json hex values")
    widget_action = widget_sub.add_parser("action", help="Execute a registered authorized widget action")
    widget_action.add_argument("action_id", choices=["mark-ready", "claim-run"], help="Registered action id")
    widget_action.add_argument("--repo", required=True, help="GitHub owner/repo")
    widget_action.add_argument("--issue", type=int, required=True, help="Target issue number")
    widget_action.add_argument("--approval-ref", required=True, help="Operator approval reference")
    widget_action.add_argument("--confirm", action="store_true", help="Confirm the declared effect")
    widget_action.add_argument("--registry", type=Path, help="Dispatcher run registry path (claim-run)")
    widget_export = widget_sub.add_parser("export", help="Export a widget as a self-contained package (.cw)")
    widget_export.add_argument("widget_id", help="Widget ID to export (e.g. candidates, pulse, map, docker, webhooks)")
    widget_export.add_argument("--out", required=True, type=Path, help="Output package path (.cw or .json)")
    widget_export.add_argument("--tokens", type=Path, help="Optional tokens JSON path (default: agent-platform/widget/tokens.json)")
    widget_load = widget_sub.add_parser("load", help="Load and render a machine-emitted widget spec (dogfood) or install a package")
    widget_load.add_argument("--spec", type=Path, help="Widget spec file to load")
    widget_load.add_argument("--package", type=Path, help="Widget package (.cw) file to load and install")
    widget_load.add_argument("--dir", type=Path, help="Target widget directory for installation (default: agent-platform/widget)")
    widget_load.add_argument("--view", help="Artifact view name (default: widget id)")
    widget_load.add_argument("--repo", help="GitHub owner/repo for github reads")
    widget_load.add_argument("--snapshot-input", type=Path, help="Snapshot input for store reads")
    widget_load.add_argument("--snapshot", type=Path, help="Artifact output path")
    widget_compose = widget_sub.add_parser("compose", help="Compose and render multiple widgets into a dashboard")
    widget_compose.add_argument("--spec", required=True, type=Path, help="Composition spec file to load (YAML/JSON)")
    widget_compose.add_argument("--widgets-dir", required=True, type=Path,
                                help="Directory containing child widget specs (<widget_id>-<version>.yaml)")
    widget_compose.add_argument("--snapshot", type=Path,
                                help="Composed artifact output path (default: agent-platform/widget/composed.json)")
    widget_compose.add_argument("--repo", help="GitHub owner/repo for github reads in child widgets")
    widget_compose.add_argument("--snapshot-input", type=Path, help="Snapshot input for store reads")
    widget_compose.add_argument("--plan-input", type=Path, help="Plan input for execution-map store reads")
    widget_generate = widget_sub.add_parser("generate", help="Generate a widget spec by prompt (ADR-038 SS5)")
    widget_generate.add_argument("prompt", help="Natural-language description of the widget to generate")
    widget_generate.add_argument("--confirm", action="store_true", help="Install the generated spec (default: preview only)")
    widget_generate.add_argument("--specs-dir", type=Path, help="Target specs directory (default: agent-platform/widget_contract/specs)")
    widget_edit = widget_sub.add_parser("edit", help="Edit an installed widget spec by prompt")
    widget_edit.add_argument("widget_id", help="Widget id to edit")
    widget_edit.add_argument("widget_version", help="Widget version to edit")
    widget_edit.add_argument("prompt", help="Natural-language description of the edit")
    widget_edit.add_argument("--confirm", action="store_true", help="Install the edited spec (default: preview only)")
    widget_edit.add_argument("--specs-dir", type=Path, help="Target specs directory (default: agent-platform/widget_contract/specs)")
    widget_remove = widget_sub.add_parser("remove", help="Remove an installed widget spec")
    widget_remove.add_argument("widget_id", help="Widget id to remove")
    widget_remove.add_argument("widget_version", help="Widget version to remove")
    widget_remove.add_argument("--specs-dir", type=Path, help="Target specs directory")
    widget_remove.add_argument("--confirm", action="store_true", help="Actually delete the spec (default: preview only)")
    widget_reset = widget_sub.add_parser("reset", help="Remove all installed widget specs")
    widget_reset.add_argument("--specs-dir", type=Path, help="Target specs directory")
    widget_reset.add_argument("--confirm", action="store_true", help="Actually delete all specs (default: preview only)")
    widget_parser.set_defaults(func=_run_widget)

    # mcp subcommand
    mcp_parser = sub.add_parser("mcp", help="MCP server (stdio transport) exposing routing/admin tools")
    mcp_sub = mcp_parser.add_subparsers(dest="mcp_command", required=True)
    mcp_serve_parser = mcp_sub.add_parser("serve", help="Start the MCP stdio server (blocks until the client disconnects)")
    mcp_serve_parser.add_argument(
        "--allow-dispatch", action="store_true",
        help="Unlock tier 1 dispatch tools",
    )
    mcp_serve_parser.add_argument(
        "--allow-credentials", action="store_true",
        help="Unlock tier 2 tools (scaffolding -- no credential tools exist yet)",
    )
    mcp_serve_parser.add_argument(
        "--store", type=Path, help="Session store path for audit logging (default: agent-platform/.sessions)",
    )
    mcp_serve_parser.set_defaults(func=_run_mcp)

    # mandate subcommand (ADR-032 operator issuance + inspection)
    mandate_parser = sub.add_parser(
        "mandate", help="Issue and inspect signed, nonce-bound mandate envelopes (ADR-032)"
    )
    mandate_sub = mandate_parser.add_subparsers(dest="mandate_command", required=True)
    mandate_issue = mandate_sub.add_parser("issue", help="Build and sign one mandate envelope (operator-side)")
    mandate_issue.add_argument("--granted-by", required=True, help="Human approver identity")
    mandate_issue.add_argument("--kid", required=True, help="Key id under granted_by")
    mandate_issue.add_argument("--issue-ref", required=True, help="Durable scope reference, e.g. owner/repo#123")
    mandate_issue.add_argument("--allowed-tools", required=True, help="Comma-separated allowed MCP tools")
    mandate_issue.add_argument("--data-class-max", default="L0", help="Max data class per ADR-016 (default L0)")
    mandate_issue.add_argument("--budget-usd-max", type=float, required=True, help="Budget ceiling in USD")
    mandate_issue.add_argument("--max-runtime-seconds", type=int, required=True, help="Hard runtime bound")
    mandate_issue.add_argument("--expires-at", required=True, help="ISO-8601 UTC expiry, e.g. 2026-08-23T12:00:00Z")
    mandate_issue.add_argument("--scope-text", required=True, help="Approved scope text (fingerprinted into the envelope)")
    mandate_issue.add_argument("--max-envelope-ttl-seconds", type=float, default=None,
                               help="Maximum envelope TTL in seconds (default: env CORTXT_MCP_MANDATE_MAX_TTL_SECONDS or 86400)")
    mandate_issue.add_argument("--store-dir", type=Path, help="Credential store dir (default: agent-platform/.credentials)")
    mandate_issue.add_argument("--confirm", action="store_true", help="Persist a fresh signing keypair in the credential broker")
    mandate_issue.set_defaults(func=_run_mandate)
    mandate_inspect = mandate_sub.add_parser("inspect", help="Validate an envelope's schema and signature (read-only)")
    mandate_inspect.add_argument("--envelope", type=Path, required=True, help="Path to the envelope JSON file")
    mandate_inspect.add_argument("--public-key", required=True, help="Hex-encoded Ed25519 public key to verify against")
    mandate_inspect.set_defaults(func=_run_mandate)

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
