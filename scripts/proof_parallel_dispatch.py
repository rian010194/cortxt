#!/usr/bin/env python3
"""Live multi-process proof of the ADR-039 claim gate.

Spawns two real OS processes that concurrently acquire a durable claim through
the real `SqliteClaimStore` (SQLite WAL, BEGIN IMMEDIATE) and asserts:

- disjoint issues  -> both processes acquire (parallel launch is allowed);
- the same issue    -> exactly one winner, the other gets `resource_collision`,
  and the store records exactly one active claim for that issue.

No GitHub label mutation and no agent runtime is spawned. The claim store is a
fresh temporary file removed at exit. Run:

    python scripts/proof_parallel_dispatch.py

Exits 0 on success, non-zero on any failed assertion.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

SCRIPT_DIR = str(Path(__file__).resolve().parent)


def _attempt(store_path: str, issue_id: str, run_id: str, go_path: str) -> str:
    """Acquire one claim through the real gate; returns 'won' or a collision code."""
    from execution_map import (Issue, SqliteClaimStore, collision_keys,
                               derive_graph, preflight_validate)

    deadline = time.time() + 15
    while time.time() < deadline and not os.path.exists(go_path):
        time.sleep(0.01)

    store = SqliteClaimStore(store_path)
    try:
        issue = Issue(issue_id=issue_id, body="", state="open",
                      labels=("workflow:ready",), area="dispatch", milestone="dispatch")
        graph = derive_graph([issue])
        worktree = f".worktrees/{run_id}"
        result = preflight_validate(
            issue=issue, graph=graph, run_id=run_id, worktree=worktree,
            store_session_id=f"sess-{run_id}", engine_id="proof",
            engine_session_id=f"eng-{run_id}", driver_id="proof-driver",
            workflow="proof/v1", store=store, inventories={}, now=100.0)
        if result.decision == "allow":
            return "won"
        return result.collision_codes[0] if result.collision_codes else "rejected"
    finally:
        store.close()


def _spawn(store_path: str, issue_id: str, run_id: str, go_path: str):
    code = (
        "import sys; sys.path.insert(0, %r); "
        "import proof_parallel_dispatch as p; "
        "print(p._attempt(%r, %r, %r, %r))"
    ) % (SCRIPT_DIR, store_path, issue_id, run_id, go_path)
    return subprocess.Popen([sys.executable, "-c", code],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def _run_pair(store_path: str, go_path: str, first: tuple[str, str], second: tuple[str, str]):
    if os.path.exists(go_path):
        os.unlink(go_path)
    proc_a = _spawn(store_path, first[0], first[1], go_path)
    proc_b = _spawn(store_path, second[0], second[1], go_path)
    time.sleep(0.1)
    Path(go_path).touch()  # release both processes together
    out_a = proc_a.communicate(timeout=30)[0].strip()
    out_b = proc_b.communicate(timeout=30)[0].strip()
    return proc_a.returncode, proc_b.returncode, out_a, out_b


def main() -> int:
    results: list[str] = []
    with tempfile.TemporaryDirectory(prefix="proof-parallel-dispatch-") as tmp:
        store_path = str(Path(tmp) / "claims.sqlite3")
        go_path = str(Path(tmp) / "go")

        rc_a, rc_b, out_a, out_b = _run_pair(
            store_path, go_path,
            ("acme/repo#1", "run-1a"), ("acme/repo#2", "run-1b"))
        ok_disjoint = (rc_a == 0 and rc_b == 0 and sorted([out_a, out_b]) == ["won", "won"])
        results.append(f"disjoint: {'ok' if ok_disjoint else f'FAIL ({out_a}, {out_b})'}")
        print(f"disjoint: {out_a}, {out_b} -> {'ok' if ok_disjoint else 'FAIL'}")

        rc_c, rc_d, out_c, out_d = _run_pair(
            store_path, go_path,
            ("acme/repo#3", "run-3a"), ("acme/repo#3", "run-3b"))
        outcomes = sorted([out_c, out_d])
        ok_overlap = (rc_c == 0 and rc_d == 0 and outcomes == ["resource_collision", "won"])
        results.append(f"overlap: {'ok' if ok_overlap else f'FAIL ({out_c}, {out_d})'}")
        print(f"overlap: {out_c}, {out_d} -> {'ok' if ok_overlap else 'FAIL'}")

        # Exactly one active claim must exist for the overlapping issue.
        from execution_map import SqliteClaimStore
        store = SqliteClaimStore(store_path)
        try:
            active = [c for c in store.active_claims(now=101.0) if c.issue_id == "acme/repo#3"]
        finally:
            store.close()
        ok_single = len(active) == 1
        results.append(f"single-claim: {'ok' if ok_single else f'FAIL ({len(active)} claims)'}")
        print(f"single-claim: {len(active)} active claim(s) for acme/repo#3 -> {'ok' if ok_single else 'FAIL'}")

    if all(x.endswith("ok") or x.startswith(("disjoint: ok", "overlap: ok", "single-claim: ok")) for x in results):
        print("proof_parallel_dispatch: PASS")
        return 0
    print("proof_parallel_dispatch: FAIL")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
