#!/usr/bin/env python3
"""CLI to log trace events from any profile/runtime.

Usage:
  python scripts/trace_log.py start   --run-id RUN123 --profile coordinator --phase plan --model nemotron
  python scripts/trace_log.py end     --run-id RUN123 --profile coordinator --phase plan --status success --tokens-in 1200 --tokens-out 800 --cost 0.0012
  python scripts/trace_log.py tail    --run-id RUN123
  python scripts/trace_log.py swimlane --run-id RUN123
"""

from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from schemas.trace_envelope import (  # noqa: E402
    Profile,
    PhaseStatus,
    TRACE_FILE,
    log_phase_start,
    log_phase_end,
)


def cmd_start(args: argparse.Namespace) -> int:
    try:
        profile = Profile(args.profile)
    except ValueError:
        print(f"Invalid profile: {args.profile}. Valid: {[p.value for p in Profile]}")
        return 1
    log_phase_start(args.run_id, profile, args.phase, args.model)
    print(f"Logged START: {args.run_id} {args.profile} {args.phase}")
    return 0


def cmd_end(args: argparse.Namespace) -> int:
    try:
        profile = Profile(args.profile)
        status = PhaseStatus(args.status)
    except ValueError as e:
        print(f"Invalid value: {e}")
        return 1
    log_phase_end(
        run_id=args.run_id,
        profile=profile,
        phase=args.phase,
        status=status,
        model=args.model,
        tokens_in=args.tokens_in,
        tokens_out=args.tokens_out,
        cost_usd=args.cost,
        artifacts=args.artifacts.split(",") if args.artifacts else None,
        gates_passed=args.gates.split(",") if args.gates else None,
        error=args.error,
    )
    print(f"Logged {args.status.upper()}: {args.run_id} {args.profile} {args.phase}")
    return 0


def cmd_tail(args: argparse.Namespace) -> int:
    if not TRACE_FILE.exists():
        print("No trace file yet.")
        return 0
    with TRACE_FILE.open("r", encoding="utf-8") as f:
        lines = f.readlines()
    if args.run_id:
        lines = [l for l in lines if f'"run_id":"{args.run_id}"' in l or f'"run_id": "{args.run_id}"' in l]
    for line in lines[-args.lines:]:
        try:
            print(json.dumps(json.loads(line), indent=2, ensure_ascii=False))
        except json.JSONDecodeError:
            print(line.strip())
    return 0


def cmd_swimlane(args: argparse.Namespace) -> int:
    """Render a simple swimlane view for a run_id."""
    if not TRACE_FILE.exists():
        print("No trace file yet.")
        return 0

    events = []
    with TRACE_FILE.open("r", encoding="utf-8") as f:
        for line in f:
            try:
                ev = json.loads(line)
                if ev.get("run_id") == args.run_id:
                    events.append(ev)
            except json.JSONDecodeError:
                continue

    if not events:
        print(f"No events for run_id: {args.run_id}")
        return 0

    # Group by profile
    from collections import defaultdict
    by_profile = defaultdict(list)
    for ev in events:
        by_profile[ev["profile"]].append(ev)

    print(f"\n=== Swimlane: {args.run_id} ===\n")
    for profile in [Profile.COORDINATOR, Profile.RESEARCHER, Profile.BUILDER, Profile.CODEX, Profile.PI]:
        evs = by_profile.get(profile.value, [])
        if not evs:
            continue
        print(f"[{profile.value.upper()}]")
        for ev in evs:
            ts = ev["ts"][:19].replace("T", " ")
            status = ev["status"]
            phase = ev["phase"]
            model = f" ({ev['model']})" if ev.get("model") else ""
            cost = f" ${ev['cost_usd']:.4f}" if ev.get("cost_usd") else ""
            tokens = f" [{ev['tokens_in']}+{ev['tokens_out']}]" if ev.get("tokens_in") or ev.get("tokens_out") else ""
            mark = {"start": "▶", "success": "✓", "fail": "✗", "retry": "↻"}.get(status, "?")
            print(f"  {mark} {ts}  {phase:<20} {status}{model}{tokens}{cost}")
            if ev.get("artifacts"):
                print(f"      artifacts: {', '.join(ev['artifacts'])}")
            if ev.get("gates_passed"):
                print(f"      gates: {', '.join(ev['gates_passed'])}")
            if ev.get("error"):
                print(f"      ERROR: {ev['error']}")
        print()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Trace logger for AI workspace")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_start = sub.add_parser("start", help="Log phase start")
    p_start.add_argument("--run-id", required=True)
    p_start.add_argument("--profile", required=True, choices=[p.value for p in Profile])
    p_start.add_argument("--phase", required=True)
    p_start.add_argument("--model", default="")
    p_start.set_defaults(func=cmd_start)

    p_end = sub.add_parser("end", help="Log phase end")
    p_end.add_argument("--run-id", required=True)
    p_end.add_argument("--profile", required=True, choices=[p.value for p in Profile])
    p_end.add_argument("--phase", required=True)
    p_end.add_argument("--status", required=True, choices=[s.value for s in PhaseStatus])
    p_end.add_argument("--model", default="")
    p_end.add_argument("--tokens-in", type=int, default=0)
    p_end.add_argument("--tokens-out", type=int, default=0)
    p_end.add_argument("--cost", type=float, default=0.0)
    p_end.add_argument("--artifacts", default="", help="Comma-separated")
    p_end.add_argument("--gates", default="", help="Comma-separated")
    p_end.add_argument("--error", default="")
    p_end.set_defaults(func=cmd_end)

    p_tail = sub.add_parser("tail", help="Show recent trace lines")
    p_tail.add_argument("--run-id", default="")
    p_tail.add_argument("--lines", type=int, default=50)
    p_tail.set_defaults(func=cmd_tail)

    p_swim = sub.add_parser("swimlane", help="Render swimlane view for a run")
    p_swim.add_argument("--run-id", required=True)
    p_swim.set_defaults(func=cmd_swimlane)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())