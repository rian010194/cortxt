#!/usr/bin/env python3
"""CI/live proof runner for issue #204 AC 2: a real end-to-end dispatch.

Proves the complete mechanical dispatch loop with a real landed commit in an
isolated worktree, against the live (private) repository through `gh`:

  workflow:ready -> claim() -> workflow:in-progress -> dispatch_async()
  -> deterministic worker writes a marker file and commits it in a unique
     isolated worktree -> Dispatcher.complete() -> Evidence Gate correlates
     the landed commit to the run's registered branch -> durable
     run.review_submitted -> review-sync -> workflow:review
  -> result comment posted -> harness verifies -> fixture reset.

Since #490 and #493 this fixture also proves the safety chain live, not just
the mechanical loop: the run is registered mutating with its real isolated
branch, so `Dispatcher.complete()` runs the production Evidence Gate against a
real commit, and the label is asserted to be still `workflow:in-progress`
immediately after completion. Only `sync_review_submissions()` moves it, and a
replay of that pass is asserted to be a no-op.

This is the implementation of the design in lab/ci-dispatch-proof-design.md
(workspace-local). It deliberately does NOT call a model: AC 1 (provider-
neutral model route, PR #205) is already proven; AC 2 is the missing
mechanical loop. The worker is deterministic (pure Python + git), so no API
key, prompt, or model reasoning is involved, and the proof is reproducible.

The routed engine's registry entry is replaced (after asserting the real
manifest routes `background-task` deterministically to whichever engine
wins the cost/tie-break at proof time -- `dsh` before the free-tier
hermes-free entry (#244) joined the manifest, `hermes-free` today), so
claim/run identity and the result envelope flow through the production
registry path without hard-coding one engine.

Rules honored: no secrets/prompts/model reasoning in GitHub; the worker never
approves/merges/closes; reset is a separate harness cleanup step after the
AC 2 pass point; evidence is content-free (hashes, relative paths, no raw
logs).

Run: python scripts/ci_dispatch_proof.py
       --repo rian010194/cortxt --issue <n> --checkout <path> --temp-root <path>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
AGENT_PLATFORM_DIR = REPO_ROOT / "agent-platform"

# The proof issue must carry exactly these three labels.
FIXTURE_LABELS = frozenset({"workflow:ready", "background-task", "ci:dispatch-proof"})
WORKFLOW_LABELS = frozenset(
    {"workflow:inbox", "workflow:ready", "workflow:in-progress",
     "workflow:review", "workflow:blocked", "workflow:done"}
)
TASK_SHAPE_LABELS = frozenset({"background-task", "research", "parallel-dispatch"})

MARKER_DIR = ".cortxt-ci-proof"
COMMIT_IDENTITY = ("Cortxt Dispatch Proof", "cortxt-dispatch-proof@users.noreply.github.com")
GH_TIMEOUT_SECONDS = 30


class ProofError(RuntimeError):
    """Structured failure that the runner knows how to report."""


def log(msg: str) -> None:
    print(f"[ci_dispatch_proof] {msg}", flush=True)


def run_cmd(argv: list[str], *, cwd: Path | None = None, timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(
        argv, capture_output=True, text=True, timeout=timeout, cwd=str(cwd) if cwd else None,
    )


def gh(args: list[str], *, repo: str, timeout: int = GH_TIMEOUT_SECONDS) -> dict:
    """Run `gh <args> --repo <repo>` and return parsed JSON (stdout)."""
    result = run_cmd(["gh", *args, "--repo", repo], timeout=timeout)
    if result.returncode != 0:
        raise ProofError(f"gh {' '.join(args)} failed: {result.stderr.strip()}")
    return json.loads(result.stdout) if result.stdout.strip() else {}


def gh_labels(repo: str, issue_num: str) -> set[str]:
    data = gh(["issue", "view", str(issue_num), "--json", "labels"], repo=repo)
    return {label["name"] for label in data.get("labels", [])}


def gh_comment(repo: str, issue_num: str, body: str) -> None:
    result = run_cmd(["gh", "issue", "comment", str(issue_num), "--repo", repo, "--body", body])
    if result.returncode != 0:
        raise ProofError(f"gh issue comment failed: {result.stderr.strip()}")


def gh_swap_label(repo: str, issue_num: str, remove: str, add: str) -> None:
    result = run_cmd(
        ["gh", "issue", "edit", str(issue_num), "--repo", repo,
         "--remove-label", remove, "--add-label", add]
    )
    if result.returncode != 0:
        raise ProofError(f"gh issue edit labels failed: {result.stderr.strip()}")


def observe_labels(repo: str, issue_num: str, *, expect: set[str], step: str) -> None:
    """Poll until GitHub's label API reflects the expected set; assert exactly
    one workflow:* label present at every observation."""
    deadline = time.time() + 15
    labels: set[str] = set()
    while time.time() < deadline:
        labels = gh_labels(repo, str(issue_num))
        if labels == expect:
            break
        time.sleep(1.0)
    if labels != expect:
        raise ProofError(
            f"{step}: expected labels {sorted(expect)} but observed {sorted(labels)}"
        )
    wf = labels & WORKFLOW_LABELS
    if len(wf) != 1:
        raise ProofError(f"{step}: expected exactly one workflow:* label, got {sorted(wf)}")
    log(f"observed labels {sorted(labels)} ({step})")


# --- Deterministic worker ---------------------------------------------------

class DeterministicCommitAdapter:
    """WorkerAdapter-protocol implementation (scripts/worker_adapters.py) that
    writes one content-free marker file in a pre-created isolated worktree and
    commits it locally. Replaces the routed engine's registry entry for the
    proof only.

    The adapter is invoked from a background thread by dispatch_async(); its
    worktree path, expected run metadata, and the routed engine_id it stands
    in for are fixed at construction.
    """

    def __init__(self, worktree: Path, issue_id: str, log_dir: Path, engine_id: str,
                 request_id: str | None = None) -> None:
        self.worktree = worktree
        self.issue_id = issue_id
        # The approved request this run executes. The Evidence Gate requires a
        # mutating result to state run_id, issue_id AND request_id, and to have
        # all three match the durable Run record exactly (#490).
        self.request_id = request_id
        self.log_dir = log_dir
        self.engine_id = engine_id
        self.runtime = f"ci-deterministic/{engine_id}-route-v1"
        self.invocation_count = 0

    # -- git helpers (all against the isolated worktree) ---------------------

    def _git(self, *args: str) -> subprocess.CompletedProcess:
        return run_cmd(["git", "-C", str(self.worktree), *args], timeout=30)

    def _head(self) -> str:
        result = self._git("rev-parse", "HEAD")
        if result.returncode != 0:
            raise ProofError(f"git rev-parse HEAD failed in worktree: {result.stderr.strip()}")
        return result.stdout.strip()

    def _assert_linked_worktree(self) -> None:
        # A linked worktree's .git is a FILE (pointer to the gitdir), unlike a
        # normal checkout where .git is a directory. This is the simplest robust
        # check that the configured path is genuinely an isolated linked worktree.
        if not (self.worktree / ".git").is_file():
            raise ProofError(f"configured path is not a linked worktree: {self.worktree}")

    def _assert_clean(self) -> None:
        result = self._git("status", "--porcelain")
        if result.returncode != 0 or result.stdout.strip():
            raise ProofError(f"worktree not clean before write:\n{result.stdout.strip() or result.stderr.strip()}")

    # -- WorkerAdapter protocol ----------------------------------------------

    def invoke(self, run, task_prompt: str, timeout_seconds: int) -> dict:
        self.invocation_count += 1
        started = time.time()
        head_before = self._head()
        try:
            self._assert_linked_worktree()
            self._assert_clean()

            marker_rel = f"{MARKER_DIR}/{run.run_id}.txt"
            marker = self.worktree / marker_rel
            marker.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "schema_version": 1,
                "run_id": run.run_id,
                "issue_id": run.issue_id,
                "ci_run": os.environ.get("GITHUB_RUN_ID", "local"),
                "ci_attempt": os.environ.get("GITHUB_RUN_ATTEMPT", "1"),
            }
            marker.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            stage = self._git("add", "--", marker_rel)
            if stage.returncode != 0:
                raise ProofError(f"git add failed: {stage.stderr.strip()}")
            staged = self._git("diff", "--cached", "--name-only")
            if staged.stdout.strip() != marker_rel:
                raise ProofError(f"unexpected staged paths: {staged.stdout.strip()!r}")
            # `-s`: the Evidence Gate (#490) requires a DCO trailer on every
            # commit it accepts as a mutating run's evidence, and this fixture
            # proves that gate live. The commit is local to the runner's
            # worktree and is never pushed.
            commit = self._git(
                "commit", "-s", "-m", f"test(dispatch): proof {run.run_id}",
                "--author", f"{COMMIT_IDENTITY[0]} <{COMMIT_IDENTITY[1]}>",
            )
            if commit.returncode != 0:
                raise ProofError(f"git commit failed: {commit.stderr.strip()}")

            head_after = self._head()
            changed = self._git("diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD")
            if changed.returncode != 0:
                raise ProofError(f"git diff-tree failed: {changed.stderr.strip()}")
            changed_paths = changed.stdout.splitlines()
            if changed_paths != [marker_rel]:
                raise ProofError(f"commit changed unexpected paths: {changed_paths!r}")
            if head_after == head_before:
                raise ProofError("head_after == head_before: no commit landed")

            marker_hash = hashlib.sha256(marker.read_bytes()).hexdigest()
            elapsed = time.time() - started
            envelope = {
                "issue_id": run.issue_id,
                "run_id": run.run_id,
                # The commit-correlation Evidence Gate (#490) reads this field.
                # A mutating run that omits it is blocked, not succeeded.
                "commit": head_after,
                "request_id": self.request_id,
                "runtime": self.runtime,
                "worker_role": run.worker_role,
                "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(started)),
                "finished_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time())),
                "model": "none (deterministic local script)",
                "usage": {"input_tokens": "not-applicable", "output_tokens": "not-applicable"},
                "cost": {"amount_usd": 0.0, "status": "not-applicable",
                         "confidence": "exact", "reason": "no inference call"},
                "artifacts": [
                    f"marker:{marker_rel}",
                    f"commit:{head_after}",
                    f"sha256:{marker_hash}",
                ],
                "evidence": [
                    {"kind": "route", "engine_id": self.engine_id, "matched_tag": "background-task",
                     "worker": self.runtime},
                    {"kind": "isolated_worktree", "path_is_worktree": True,
                     "commit_landed": True, "head_before": head_before,
                     "head_after": head_after, "changed_path": marker_rel},
                ],
                "error": None,
                "_status": "succeeded",
                "_elapsed_seconds": elapsed,
            }
            log(f"worker committed {head_after[:12]} with marker {marker_rel}")
            return envelope
        except Exception as error:  # noqa: BLE001 - envelope discipline: never raise
            self._write_run_log(run, str(error))
            return {
                "_status": "failed",
                "issue_id": run.issue_id,
                "run_id": run.run_id,
                "runtime": self.runtime,
                "worker_role": run.worker_role,
                "model": "none",
                "usage": "unknown (worker failed before completion)",
                "cost": {"amount_usd": 0.0, "status": "not-applicable",
                         "confidence": "exact", "reason": "no inference call"},
                "artifacts": [],
                "evidence": [{"kind": "worker_error", "detail": type(error).__name__}],
                "error": {"category": "worker_failed", "recovery": str(error)},
                "_elapsed_seconds": time.time() - started,
            }

    def _write_run_log(self, run, detail: str) -> None:
        try:
            self.log_dir.mkdir(parents=True, exist_ok=True)
            (self.log_dir / f"{run.run_id}.log").write_text(
                f"=== failure detail ===\n{detail}\n", encoding="utf-8", errors="replace"
            )
        except OSError:
            pass


# --- Orchestration ----------------------------------------------------------

def ensure_imports() -> None:
    """Make scripts/ and agent-platform/ importable, mirroring how the repo's
    own tooling wires the two trees together."""
    for p in (SCRIPTS_DIR, AGENT_PLATFORM_DIR):
        if str(p) not in sys.path:
            sys.path.insert(0, str(p))


# Worktrees created by this process, for guaranteed cleanup in main()'s
# finally block (both success and failure paths). (checkout, worktree).
_CREATED_WORKTREES: list[tuple[Path, Path]] = []


def proof_branch(issue_num: str, run_id: str) -> str:
    """The run's isolated branch name.

    Factored out because the Evidence Gate (#490) correlates the landed commit
    against the branch recorded on the durable Run, so the proof must register
    exactly the branch it created -- not a name reconstructed later.
    """
    return f"ci/dispatch-proof/{issue_num}/{run_id.replace(':', '-')}"


def create_worktree(checkout: Path, temp_root: Path, issue_num: str, run_id: str) -> Path:
    """Create a unique isolated worktree (sibling dirs under temp_root),
    following the daemon's worktree pattern but unique per run."""
    safe_id = f"issue-{issue_num}"
    run_part = run_id.replace(":", "-")
    worktree = temp_root / f"{checkout.name}-worktrees" / safe_id / run_part
    worktree.parent.mkdir(parents=True, exist_ok=True)
    branch = proof_branch(issue_num, run_id)
    result = run_cmd(
        ["git", "-C", str(checkout), "worktree", "add", "-b", branch, str(worktree), "HEAD"],
        timeout=60,
    )
    if result.returncode != 0:
        raise ProofError(f"git worktree add failed: {result.stderr.strip()}")
    _CREATED_WORKTREES.append((checkout, worktree))
    log(f"created worktree {worktree} on branch {branch}")
    return worktree


def remove_worktree(checkout: Path, worktree: Path) -> None:
    """Best-effort cleanup of the runner-local worktree (never durable evidence)."""
    try:
        run_cmd(["git", "-C", str(checkout), "worktree", "remove", "--force", str(worktree)], timeout=30)
        log(f"removed worktree {worktree}")
    except Exception as error:  # noqa: BLE001
        log(f"worktree removal failed (non-fatal): {error}")


def verify_commit_independent(checkout: Path, worktree: Path, head_before: str, run_id: str) -> dict:
    """Re-run the git assertions outside the adapter thread: a green job must
    not rely on worker self-report alone."""
    def gitc(*args: str) -> subprocess.CompletedProcess:
        return run_cmd(["git", "-C", str(worktree), *args], timeout=30)

    head_after = gitc("rev-parse", "HEAD").stdout.strip()
    parent = gitc("rev-parse", "HEAD^").stdout.strip()
    changed = gitc("diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD").stdout.splitlines()
    clean = gitc("status", "--porcelain").stdout.strip()
    primary_head = run_cmd(["git", "-C", str(checkout), "rev-parse", "HEAD"], timeout=30).stdout.strip()

    checks = {
        "head_before": head_before,
        "head_after": head_after,
        "head_changed": head_after != head_before and head_before != "",
        "parent_is_head_before": parent == head_before,
        "exactly_one_changed_path": changed == [f"{MARKER_DIR}/{run_id}.txt"],
        "worktree_clean_after": clean == "",
        "primary_checkout_unchanged": primary_head == head_before,
    }
    if not all(checks.values()):
        raise ProofError(f"independent commit verification failed: {json.dumps(checks, indent=2)}")
    marker = worktree / MARKER_DIR / f"{run_id}.txt"
    marker_hash = hashlib.sha256(marker.read_bytes()).hexdigest() if marker.exists() else None
    checks["marker_sha256"] = marker_hash
    log(f"independent verification passed: commit_landed=true ({head_after[:12]})")
    return checks


def run_proof(args: argparse.Namespace) -> dict:
    ensure_imports()

    from commit_evidence import make_commit_gate  # scripts/
    from dispatcher import Dispatcher, GitHubOps, RunRegistry  # scripts/
    from daemon.review_submission import make_review_submitter  # agent-platform
    from daemon.review_sync import sync_review_submissions
    from routing.engine_manifest import DEFAULT_MANIFESTS, route  # agent-platform
    from runtime.default_engine_context import build_default_engine_context
    from worker_adapters import ADAPTER_REGISTRY, dispatch_async, register_adapter

    repo = args.repo
    issue_num = str(args.issue)
    issue_id = f"{repo}#{issue_num}"
    checkout = Path(args.checkout).resolve()
    temp_root = Path(args.temp_root).resolve()
    temp_root.mkdir(parents=True, exist_ok=True)

    evidence: dict = {
        "repo": repo, "issue_id": issue_id, "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "ci_run": os.environ.get("GITHUB_RUN_ID", "local"),
        "ci_attempt": os.environ.get("GITHUB_RUN_ATTEMPT", "local"),
        "observations": [],
    }

    # 1. Preconditions: issue open with the exact fixture label set.
    issue = gh(["issue", "view", issue_num, "--json", "number,state,title,body,labels"], repo=repo)
    if issue.get("state") != "OPEN":
        raise ProofError(f"proof issue {issue_id} is not open (state={issue.get('state')})")
    labels = {label["name"] for label in issue.get("labels", [])}
    if labels != FIXTURE_LABELS:
        raise ProofError(
            f"proof issue labels must be exactly {sorted(FIXTURE_LABELS)}, got {sorted(labels)}"
        )
    body = issue.get("body") or ""
    required_body_markers = ["Scope", "Acceptance criteria", "Worker role", "Maximum runtime",
                             "Maximum cost", "Maximum parallel workers", "Delegation depth",
                             "Artifact policy", "Approval reference", "Reset policy"]
    missing = [m for m in required_body_markers if m not in body]
    if missing:
        raise ProofError(f"proof issue body missing required sections: {missing}")
    evidence["preconditions"] = {"labels": sorted(labels), "body_sections_ok": True}

    # 2. Deterministic routing assertion: background-task must resolve to a
    #    concrete engine, and that engine must be the one we replace. The
    #    winner is the cheapest cost_class with a deterministic engine_id
    #    tie-break (routing/engine_manifest.py) -- `dsh` until the free-tier
    #    hermes-free entry (#244) joined the manifest for background-task,
    #    `hermes-free` today. We assert the production route rather than a
    #    hard-coded engine so the proof tracks manifest reality.
    choice = route(["background-task"], DEFAULT_MANIFESTS)
    if choice.matched_tag != "background-task":
        raise ProofError(
            f"expected matched_tag background-task, got matched_tag={choice.matched_tag!r}"
        )
    engine_id = choice.engine_id
    manifests = {m.engine_id: m for m in DEFAULT_MANIFESTS}
    if engine_id not in manifests or "background-task" not in manifests[engine_id].task_shapes:
        raise ProofError(
            f"routed engine {engine_id!r} missing from manifests or does not declare background-task"
        )
    if not build_default_engine_context().get(engine_id).has_provider:
        raise ProofError(
            f"default engine context has no provider registered for routed engine {engine_id!r}"
        )
    evidence["route"] = {"matched_tag": choice.matched_tag, "engine_id": engine_id}
    log(f"route asserted: background-task -> {engine_id}")

    # 3. Dispatcher + registry, with the proof issue as the target.
    state_dir = temp_root / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    registry = RunRegistry(state_dir / "runs.json")
    # S7 (#490, #493): the proof runs the production gate and the production
    # review path, not a relaxed variant. The gate reads git in the primary
    # checkout, whose ref store the linked worktree shares; the review
    # submitter writes to a runner-local session store that review-sync then
    # reads. Both are the same objects `default_launcher` wires.
    sessions_dir = state_dir / "sessions"
    dispatcher = Dispatcher(
        registry, GitHubOps(),
        commit_gate=make_commit_gate(checkout),
        review_submitter=make_review_submitter(sessions_dir),
    )
    run_log_dir = checkout / ".hermes" / "dispatch" / "runs"

    # 4. Claim (label ready -> in-progress + claim comment).
    run = dispatcher.claim(
        issue_id, workflow="wedge-b", worker_role="builder",
        runtime=choice.engine_id, lease_seconds=120,
    )
    evidence["claim"] = {"run_id": run.run_id, "runtime": run.runtime, "worker_role": run.worker_role}
    observe_labels(repo, issue_num, expect=frozenset({"workflow:in-progress", "background-task", "ci:dispatch-proof"}), step="after claim")

    # 5. Isolated worktree, registered on the durable Run.
    worktree = create_worktree(checkout, temp_root, issue_num, run.run_id)
    # #490: the gate correlates the landed commit against the branch the Run
    # record registers, and applies at all only to a Run the launcher marked
    # mutating. This proof creates its own worktree rather than going through
    # WorkLauncher, so it records the same three fields the launcher would --
    # otherwise the fixture would exercise a weaker path than production.
    # The approved scope is persisted before dispatch and is the same data the
    # gate enforces: one marker path under MARKER_DIR, plus the request the run
    # executes. The worker supplies none of it.
    approved_paths = [MARKER_DIR]
    request_id = "sha256:" + hashlib.sha256(
        f"{issue_id}|{run.run_id}|{MARKER_DIR}".encode("utf-8")).hexdigest()
    registry.update(run.run_id, mutating=True, isolation="worktree",
                    branch=proof_branch(issue_num, run.run_id),
                    # The launcher records the worktree too (#514); a fixture
                    # that omits it reproduces exactly the null-worktree state
                    # that issue exists to close, and would prove a weaker path.
                    worktree=str(Path(worktree).resolve()),
                    artifact_paths=approved_paths, request_id=request_id)
    run = registry.get(run.run_id)
    evidence["approved_scope"] = {"artifact_paths": approved_paths, "request_id": request_id}
    if not run.worktree:
        raise ProofError("run record carries no worktree; the fixture must record what "
                         "the launcher records (#514)")
    head_before = run_cmd(["git", "-C", str(worktree), "rev-parse", "HEAD"], timeout=30).stdout.strip()
    if not head_before:
        raise ProofError("could not read head_before from worktree")

    # 6. Replace only the routed engine's registry entry with the
    #    deterministic worker.
    adapter = DeterministicCommitAdapter(worktree, issue_id, run_log_dir, engine_id,
                                        request_id=request_id)
    register_adapter(engine_id, adapter)
    assert ADAPTER_REGISTRY[engine_id] is adapter

    # 7. Invoke through the production path (dispatch_async -> adapter -> complete).
    thread = dispatch_async(dispatcher, run, task_prompt="[ci fixture] see proof issue body")
    thread.join(timeout=150)
    if thread.is_alive():
        raise ProofError("worker thread did not terminate within lease + margin")
    if adapter.invocation_count != 1:
        raise ProofError(f"worker invoked {adapter.invocation_count} times, expected exactly 1")

    # 8. Independent commit verification (never self-report only).
    evidence["commit"] = verify_commit_independent(checkout, worktree, head_before, run.run_id)

    # 9. Registry: terminal succeeded with a complete, correlated envelope.
    result = dispatcher.query(run.run_id)
    if result is None or result.get("status") != "succeeded":
        raise ProofError(f"run did not reach terminal succeeded: {json.dumps(result, default=str)[:500]}")
    if result.get("gh_synced") is not True:
        raise ProofError("run not gh_synced: result comment/label step did not complete")
    envelope = result.get("result") or {}
    required_fields = ["issue_id", "run_id", "runtime", "worker_role", "model", "usage",
                       "cost", "artifacts", "evidence", "error"]
    missing_fields = [f for f in required_fields if f not in envelope]
    if missing_fields:
        raise ProofError(f"result envelope missing fields: {missing_fields}")
    if envelope["issue_id"] != issue_id or envelope["run_id"] != run.run_id:
        raise ProofError("envelope correlation mismatch (issue_id/run_id)")
    evidence["result"] = {"status": result["status"], "gh_synced": True, "fields": required_fields}

    # 9b. Evidence Gate (#490): the run is succeeded because a real commit was
    #     verified and correlated, not because the worker said so.
    gate_evidence = result.get("commit_evidence") or {}
    if envelope.get("evidence_gate") != "commit_correlated":
        raise ProofError(f"result envelope not gate-verified: {envelope.get('evidence_gate')!r}")
    if gate_evidence.get("commit") != evidence["commit"]["head_after"]:
        raise ProofError("gate evidence commit does not match the independently verified commit")
    if gate_evidence.get("branch") != proof_branch(issue_num, run.run_id):
        raise ProofError(f"gate evidence branch mismatch: {gate_evidence.get('branch')!r}")
    if gate_evidence.get("run_id") != run.run_id or gate_evidence.get("issue_id") != issue_id:
        raise ProofError("gate evidence does not correlate to this run/issue")
    if gate_evidence.get("policy_paths") != approved_paths:
        raise ProofError(
            f"gate enforced {gate_evidence.get('policy_paths')!r}, not the approved "
            f"artifact paths {approved_paths!r}")
    if gate_evidence.get("request_id") != request_id:
        raise ProofError("gate evidence does not carry the approved request_id")
    outside = [f for f in gate_evidence.get("files", [])
               if not f.replace(chr(92), "/").startswith(MARKER_DIR + "/")]
    if outside:
        raise ProofError(f"commit touched paths outside the approved scope: {outside}")
    evidence["evidence_gate"] = {
        "verdict": "commit_correlated",
        "commit": gate_evidence["commit"],
        "branch": gate_evidence["branch"],
        "files": gate_evidence.get("files", []),
        "policy_paths": gate_evidence.get("policy_paths", []),
        "request_id": gate_evidence.get("request_id"),
    }
    log(f"evidence gate: commit correlated on {gate_evidence['branch']}")

    # 10. Review is earned, not asserted (#493). The dispatcher must NOT have
    #     moved the label; a durable review submission must exist; and only
    #     review-sync performs in-progress -> review.
    observe_labels(repo, issue_num, expect=frozenset({"workflow:in-progress", "background-task", "ci:dispatch-proof"}), step="after complete, before review-sync")
    submission_id = result.get("review_submission_id")
    if not submission_id:
        raise ProofError("no durable review submission recorded on the run")
    report = sync_review_submissions(sessions_dir, state_dir)
    if report["synced"] != [submission_id]:
        raise ProofError(f"review-sync did not apply exactly this submission: {report}")
    observe_labels(repo, issue_num, expect=frozenset({"workflow:review", "background-task", "ci:dispatch-proof"}), step="after review-sync")
    # Replay: a second pass is a no-op, not a second edit.
    replay = sync_review_submissions(sessions_dir, state_dir)
    if replay["synced"] or not replay["skipped"]:
        raise ProofError(f"review-sync replay was not idempotent: {replay}")
    evidence["review_sync"] = {"review_submission_id": submission_id,
                               "label_moved_by": "review-sync",
                               "replay_skipped": replay["skipped"][0]["reason"]}
    log(f"review-sync applied {submission_id}; replay skipped as {replay['skipped'][0]['reason']}")

    # 11. Result comment validation (parse conservatively; comment is markdown).
    #     The claim comment also contains the run_id, so require the result
    #     comment's own marker ("Run result") to distinguish the two.
    comments = gh(["issue", "view", issue_num, "--json", "comments"], repo=repo).get("comments", [])
    result_comments = [
        c for c in comments
        if run.run_id in c.get("body", "") and "Run result" in c.get("body", "")
    ]
    if len(result_comments) != 1:
        raise ProofError(f"expected exactly 1 result comment for run_id, found {len(result_comments)}")
    rc_body = result_comments[0]["body"]
    if "succeeded" not in rc_body or "commit_landed" not in rc_body:
        raise ProofError("result comment missing status/commit_landed markers")
    evidence["result_comment"] = {"found": True, "run_id_in_comment": True}

    # 12. Fixture reset (harness cleanup, after the AC 2 pass point; never
    #     touches workflow:done, never closes, never removes other labels).
    gh_swap_label(repo, issue_num, "workflow:review", "workflow:ready")
    gh_comment(
        repo, issue_num,
        f"**CI fixture reset.** Run `{run.run_id}` verified (workflow:ready -> "
        f"workflow:in-progress -> workflow:review, commit_landed=true, "
        f"{evidence['commit']['head_after'][:12]}). Fixture returned to workflow:ready. "
        f"Actions run: {os.environ.get('GITHUB_SERVER_URL', 'local')}/{os.environ.get('GITHUB_REPOSITORY', repo)}/actions/runs/{os.environ.get('GITHUB_RUN_ID', 'local')}",
    )
    observe_labels(repo, issue_num, expect=FIXTURE_LABELS, step="after reset")
    evidence["reset"] = {"fixture_back_to_ready": True}

    # 13. Optional: post a concise evidence summary to the originating issue
    #     #204 for the inaugural/proof-changing runs (per the proof design).
    #     Controlled by the workflow input post_summary_to_issue_204 -> env.
    if os.environ.get("CORTXT_POST_SUMMARY_TO_204", "false") == "true":
        server = os.environ.get("GITHUB_SERVER_URL", "")
        run_env = os.environ.get("GITHUB_RUN_ID", "local")
        commit = evidence["commit"]
        summary = (
            f"**AC 2 Linux CI proof passed** (run `{run.run_id}`).\n\n"
            f"- Proof issue: {repo}#{issue_num}\n"
            f"- Commit landed in isolated worktree: `{commit['head_after'][:12]}` "
            f"(before `{commit['head_before'][:12]}`)\n"
            f"- Label sequence observed: `workflow:ready -> workflow:in-progress -> "
            f"workflow:review` (fixture reset to ready)\n"
            f"- Independent verification: `commit_landed=true`, exactly one changed path, "
            f"clean tree, primary checkout unchanged\n"
            f"- Workflow run: {server}/{repo}/actions/runs/{run_env}"
        )
        gh_comment(repo, "204", summary)
        evidence["posted_to_204"] = True

    evidence["label_sequence"] = ["workflow:ready", "workflow:in-progress", "workflow:review", "workflow:ready (reset)"]
    evidence["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    evidence["success"] = True
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser(description="Issue #204 AC 2 dispatch proof")
    parser.add_argument("--repo", required=True)
    parser.add_argument("--issue", required=True, type=int)
    parser.add_argument("--checkout", required=True)
    parser.add_argument("--temp-root", required=True)
    args = parser.parse_args()

    evidence: dict = {}
    try:
        evidence = run_proof(args)
    except ProofError as error:
        log(f"PROOF FAILED: {error}")
        try:
            ensure_imports()
            from dispatcher import Dispatcher, GitHubOps, RunRegistry
            repo = args.repo
            issue_num = str(args.issue)
            state_dir = Path(args.temp_root).resolve() / "state"
            registry = RunRegistry(state_dir / "runs.json")
            dispatcher = Dispatcher(registry, GitHubOps())
            for run_id, run in list(registry._runs.items()):
                if run.status == "in_progress":
                    dispatcher.complete(run_id, "failed", {
                        "issue_id": run.issue_id, "run_id": run_id,
                        "runtime": run.runtime, "worker_role": run.worker_role,
                        "model": "none", "usage": "unknown", "cost": "unknown",
                        "artifacts": [], "evidence": [{"kind": "proof_failed"}],
                        "error": {"category": "proof_failed", "recovery": str(error)},
                    })
                    log(f"marked {run_id} failed -> workflow:blocked")
        except Exception as reset_error:  # noqa: BLE001
            log(f"failure-path reset error (non-fatal): {reset_error}")
        # Normalize whichever workflow:* label is present back to workflow:ready
        # (never touches workflow:done, never closes, never removes other labels).
        try:
            labels = gh_labels(repo, issue_num)
            movable = labels & {"workflow:in-progress", "workflow:review", "workflow:blocked"}
            if movable:
                for lbl in movable:
                    run_cmd(
                        ["gh", "issue", "edit", issue_num, "--repo", repo,
                         "--remove-label", lbl, "--add-label", "workflow:ready"],
                        timeout=30,
                    )
                log(f"fixture normalized {sorted(movable)} -> workflow:ready")
        except Exception as norm_error:  # noqa: BLE001
            log(f"failure-path label normalization error (non-fatal): {norm_error}")
        evidence = {"success": False, "error": str(error)}
        print(json.dumps(evidence, indent=2, default=str))
        return 1

    if evidence.get("success"):
        print(json.dumps(evidence, indent=2, default=str))
        _cleanup_worktrees()
        return 0
    print(json.dumps(evidence, indent=2, default=str))
    _cleanup_worktrees()
    return 1


def _cleanup_worktrees() -> None:
    """Remove every worktree this process created (runner-local only; durable
    GitHub evidence lives on the issue). Best-effort: never masks a proof
    result."""
    for checkout, worktree in list(_CREATED_WORKTREES):
        remove_worktree(checkout, worktree)
    _CREATED_WORKTREES.clear()


if __name__ == "__main__":
    sys.exit(main())
