#!/usr/bin/env python3
"""Network-free check-style tests for ADR-039 execution map core."""
import json
import subprocess
import sys
import tempfile
import threading
from dataclasses import asdict, replace
from pathlib import Path

import execution_map as em

fail = []


def check(name, condition):
    print(f"  {'ok' if condition else 'FAIL':4} {name}")
    if not condition:
        fail.append(name)


def raises(fn, kind):
    try:
        fn()
    except kind:
        return True
    return False


def issue(number, **changes):
    data = {"issue_id": f"owner/repo#{number}", "state": "open",
            "labels": ["workflow:ready"], "area": "core", "milestone": "m1", "body": ""}
    data.update(changes)
    return data


def claim(number, run_id, now=100.0, **changes):
    data = dict(claim_version=1, claim_id=f"claim-{run_id}", issue_id=f"owner/repo#{number}",
                workflow="build", run_id=run_id, branch_ref=f"work/{run_id}",
                worktree_path=f".worktrees/{run_id}", store_session_id=f"store-{run_id}",
                engine_id="engine", engine_session_id=f"engine-{run_id}", driver_id="driver",
                state="active", acquired_at=now, heartbeat_at=now, lease_expires_at=now + 30,
                released_at=None, release_reason=None, expected_workflow_label="workflow:ready",
                claim_generation=0)
    data.update(changes)
    return em.ClaimRecord(**data)


def test_graph_and_plan():
    fixtures = [
        issue(2, body="Part of: #1\nBlocked by: #3\nDepends on: #3", native_parent="#1",
              native_prerequisites=("#3",)),
        issue(1), issue(3, state="closed", labels=()), issue(10), issue(4, body="Part of: #4"),
        issue(5, body="Blocked by: #6"), issue(6, body="Blocked by: #5"),
        issue(7, body="Part of: #1\nPart of: #10", native_parent="#1"),
        issue(8, body="Blocked by: other/repo#2"), issue(9, area=None),
    ]
    graph = em.derive_graph(fixtures)
    edge = next(x for x in graph.prerequisites if x.source == "owner/repo#3")
    check("native/text prerequisite dedup retains evidence", edge.evidence == ("native", "text"))
    codes = {x.code for x in graph.drift}
    check("required graph drift codes are derived", {"duplicate_edge", "self_edge", "prerequisite_cycle",
          "multiple_parents", "native_text_parent_mismatch", "cross_repo_target",
          "missing_area_or_milestone"}.issubset(codes))
    cycle = next(x.witness for x in graph.drift if x.code == "prerequisite_cycle")
    check("cycle witness starts at lowest canonical id", cycle == ("owner/repo#5", "owner/repo#6", "owner/repo#5"))
    check("drift is stable sorted", list(graph.drift) == sorted(graph.drift, key=em.Drift.sort_key))
    graph2 = em.derive_graph([issue(10), issue(2, body="Blocked by: #1\nPart of: #10"), issue(1)])
    check("Kahn waves use canonical numeric tie-break", em.topological_waves(graph2) ==
          (("owner/repo#1", "owner/repo#10"), ("owner/repo#2",)))
    done = em.derive_graph([issue(1, labels=["workflow:done"]), issue(2, body="Blocked by: #1")])
    ready = em.derive_graph([issue(1), issue(2, body="Blocked by: #1")])
    check("done blocker is satisfied", em.topological_waves(done)[0] == ("owner/repo#1", "owner/repo#2"))
    check("ready blocker remains prerequisite", em.topological_waves(ready)[1] == ("owner/repo#2",))
    check("containment does not create prerequisite authority", em.topological_waves(graph2)[0][1] == "owner/repo#10")
    check("fatal drift propagates non-launchability", "owner/repo#5" in graph.non_launchable)
    all_drift = em.derive_graph([issue(1, body="Part of: #2"), issue(2, body="Part of: #1"),
        issue(3, body="Blocked by: #99"), issue(4, labels=[]), issue(5, body="Part of: #5")])
    check("remaining deterministic drift codes are covered", {"containment_cycle", "missing_target",
          "workflow_label_cardinality", "self_edge"}.issubset({x.code for x in all_drift.drift}))


def test_collision_and_preflight(root=None):
    if root is None:
        root = Path(tempfile.mkdtemp(prefix="execution-map-test-"))
    keys = em.collision_keys(issue_id="Owner/Repo#2", run_id="run-1", worktree=root / "x" / ".." / "wt",
                             workflow_label="workflow:ready", store_session_id="same",
                             engine_session_id="same")
    check("canonical issue and branch collision keys", "issue:owner/repo#2" in keys and "branch:work/run-1" in keys)
    check("worktree is normalized", f"worktree:{em.normalize_worktree(root / 'wt')}" in keys)
    check("run/store/engine identities do not alias", len({"run:run-1", "store_session:same",
          "engine_session:same"}.intersection(keys)) == 3)
    store = em.SqliteClaimStore(root / "preflight.db")
    graph = em.derive_graph([issue(1)])
    inventory = {"dispatcher": [{"owner": "old", "run_id": "run-1", "stale": True}],
                 "daemon": ["bad"], "git": [{"resources": ["branch:work/run-1"]}],
                 "lifecycle": [{"owner": "x", "store_session_id": "store-run-1"}]}
    before = json.dumps(inventory, sort_keys=True)
    result = em.preflight_validate(issue=graph.issues[0], graph=graph, run_id="run-1",
        worktree=root / "wt", store_session_id="store-run-1", engine_id="e",
        engine_session_id="engine-run-1", driver_id="driver", workflow="build", store=store,
        inventories=inventory, writers=[{"domain": "state", "owner": "other"}], now=100)
    check("preflight rejects all injected collision classes", {"resource_collision", "stale_unreconciled",
          "malformed_daemon", "missing_owner", "shared_store_writer_conflict"}.issubset(result.collision_codes))
    check("failed validation has no side effects", store.generation() == 0 and before == json.dumps(inventory, sort_keys=True))
    store.close()


def test_store_and_receipt(root=None):
    if root is None:
        root = Path(tempfile.mkdtemp(prefix="execution-map-test-"))
    path = root / "claims.db"
    first, second = em.SqliteClaimStore(path), em.SqliteClaimStore(path)
    barrier = threading.Barrier(2); outcomes = []
    def acquire(store, run_id):
        record = claim(1, run_id)
        resources = em.collision_keys(issue_id=record.issue_id, run_id=run_id,
            worktree=record.worktree_path, workflow_label="workflow:ready",
            store_session_id=record.store_session_id, engine_session_id=record.engine_session_id)
        barrier.wait()
        try:
            store.acquire(record, resources, 0); outcomes.append("won")
        except em.ClaimConflict:
            outcomes.append("lost")
    threads = [threading.Thread(target=acquire, args=(first, "r1")),
               threading.Thread(target=acquire, args=(second, "r2"))]
    for thread in threads: thread.start()
    for thread in threads: thread.join()
    check("two SQLite connections yield exactly one overlap winner", sorted(outcomes) == ["lost", "won"])
    generation = first.generation()
    disjoint = claim(2, "r3")
    disjoint_keys = em.collision_keys(issue_id=disjoint.issue_id, run_id=disjoint.run_id,
        worktree=disjoint.worktree_path, workflow_label="workflow:ready",
        store_session_id=disjoint.store_session_id, engine_session_id=disjoint.engine_session_id)
    held = first.acquire(disjoint, disjoint_keys, generation)
    check("disjoint claim is permitted", held.state == "active")
    first.close(); second.close()
    reopened = em.SqliteClaimStore(path)
    check("claims persist across close and reopen", len(reopened.active_claims(now=101)) == 2)
    expired = reopened.expire_leases(now=1000)
    check("expiry enters pending reconciliation without freeing", all(x.state == "expired_pending_reconciliation" for x in expired))
    check("expired resources remain exclusive", raises(lambda: reopened.acquire(claim(1, "r4", now=1000),
          em.collision_keys(issue_id="owner/repo#1", run_id="r4", worktree=".worktrees/r4",
          workflow_label="workflow:ready", store_session_id="s4", engine_session_id="e4"),
          reopened.generation()), em.ClaimConflict))
    check("expiry history is immutable and retained", all(reopened.history(x.claim_id)[-1]["event"] == "lease_expired"
          for x in expired))
    reopened.close()

    receipt_store = em.SqliteClaimStore(root / "receipt.db")
    graph = em.derive_graph([issue(1)])
    result = em.preflight_validate(issue=graph.issues[0], graph=graph, run_id="receipt-run",
        worktree=root / "receipt-wt", store_session_id="store-r", engine_id="e",
        engine_session_id="engine-r", driver_id="driver", workflow="build", store=receipt_store,
        inventories={}, now=200, ttl_seconds=20)
    receipt = result.receipt; active = receipt_store.active_claims(now=201)[0]
    snapshot = {"issue": asdict(graph.issues[0]), "graph_drift": [asdict(x) for x in graph.drift],
                "inventories": {}, "writers": (), "generation": 0}
    check("successful preflight returns content-free receipt", result.decision == "allow" and receipt is not None)
    check("receipt validates once with all bindings", em.validate_receipt(receipt, snapshot=snapshot,
          claim=active, resources=receipt.resources, run_id="receipt-run", store=receipt_store, now=201))
    check("receipt is single use", not em.validate_receipt(receipt, snapshot=snapshot, claim=active,
          resources=receipt.resources, run_id="receipt-run", store=receipt_store, now=201))
    renewed = receipt_store.heartbeat(active.claim_id, active.run_id, active.driver_id,
                                      active.claim_generation, 230, now=205)
    released = receipt_store.release(renewed.claim_id, renewed.run_id, renewed.driver_id,
                                     renewed.claim_generation, "terminal durable", now=206)
    check("heartbeat and reasoned release advance immutable history", released.state == "released" and
          [x["event"] for x in receipt_store.history(active.claim_id)] == ["acquired", "heartbeat", "released"])
    result2 = em.preflight_validate(issue=graph.issues[0], graph=graph, run_id="receipt-run-2",
        worktree=root / "receipt-wt-2", store_session_id="store-r2", engine_id="e",
        engine_session_id="engine-r2", driver_id="driver", workflow="build", store=receipt_store,
        inventories={}, now=202, ttl_seconds=20)
    # Same issue is intentionally held, so use a fresh store to test changed snapshot invalidation.
    fresh = em.SqliteClaimStore(root / "receipt2.db")
    result2 = em.preflight_validate(issue=graph.issues[0], graph=graph, run_id="receipt-run-2",
        worktree=root / "receipt-wt-2", store_session_id="store-r2", engine_id="e",
        engine_session_id="engine-r2", driver_id="driver", workflow="build", store=fresh,
        inventories={}, now=202, ttl_seconds=20)
    changed = dict(snapshot); changed["changed"] = True
    check("changed snapshot invalidates receipt", not em.validate_receipt(result2.receipt, snapshot=changed,
          claim=fresh.active_claims(now=203)[0], resources=result2.receipt.resources,
          run_id="receipt-run-2", store=fresh, now=203))
    receipt_store.close(); fresh.close()


def test_projection():
    graph = em.derive_graph([issue(2, body="Blocked by: #1"), issue(1)])
    projection = em.read_projection(graph, collision_codes=["resource_collision"], role="observer")
    text = json.dumps(projection, sort_keys=True)
    check("plan is stable and content-free", projection == em.read_projection(graph,
          collision_codes=["resource_collision"], role="observer") and "body" not in text and "title" not in text)
    check("plan reports ids waves blockers drift claims lease collisions role", all(x in projection for x in
          ("role", "issues", "waves", "claims", "collision_codes")) and projection["issues"][1]["blockers"])


def test_cli(root=None):
    if root is None:
        root = Path(tempfile.mkdtemp(prefix="execution-map-test-"))
    source = root / "plan.json"
    source.write_text(json.dumps({"issues": [issue(1)], "role": "observer"}), encoding="utf-8")
    cli = Path(__file__).resolve().parents[1] / "agent-platform" / "cli" / "unified_cli.py"
    proc = subprocess.run([sys.executable, str(cli), "work", "plan", "--input", str(source)],
                          capture_output=True, text=True, timeout=20)
    check("cortxt work plan reads projection without launching", proc.returncode == 0 and
          '"role": "observer"' in proc.stdout and '"waves"' in proc.stdout)


if __name__ == "__main__":
    root = Path(tempfile.mkdtemp(prefix="execution-map-test-"))
    test_graph_and_plan()
    test_collision_and_preflight(root)
    test_store_and_receipt(root)
    test_projection()
    test_cli(root)
    print("")
    if fail:
        print(f"FAILED: {len(fail)}: {fail}")
        raise SystemExit(1)
    print("ALL EXECUTION MAP TESTS PASSED")
