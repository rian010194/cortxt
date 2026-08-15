#!/usr/bin/env python3
"""Claim/run-identity for the minimal end-to-end dispatcher (#122).

Implements the "Claim and run identity" section of
docs/architecture/dispatch-contract.md, using the workflow:* label carrier
designated by docs/adr/018-workflow-state-carrier.md (ADR-018).

Atomicity model: this is a single-process dispatcher. max_parallel_workers=2
is enforced in-process (a lock + an active-claim count), not via a
distributed compare-and-swap on GitHub. Two dispatcher processes racing the
same repo is the concurrent-claim risk flagged in ADR-018 and is out of
scope for this minimal adapter.

Within one process, `Dispatcher._lock` (an RLock) also guards
complete()/heartbeat()/sweep_expired()/spawn_child(), not just claim(): once
a worker can complete asynchronously from a background thread (see
scripts/worker_adapters.py), the main thread may legitimately call
heartbeat()/sweep_expired()/spawn_child() while that thread's complete() is
in flight, and without this lock every one of those writers hits
RunRegistry's unsynchronized file rewrite. complete() also refuses a second
call on an already-terminal run_id, so a losing racer fails loudly instead
of double-posting a result.

The lock's scope is deliberately narrow: it protects only the in-memory/
file registry mutation, never the blocking GitHub API calls in complete().
complete() takes the lock just long enough to atomically check-and-claim the
terminal transition, releases it, then does the (possibly slow) GitHub label
swap and comment unlocked -- so one run's network latency cannot stall
heartbeat()/sweep_expired() for other runs. sweep_expired() follows the same
pattern: it snapshots expired run_ids under the lock, then calls complete()
for each one individually, outside any lock it itself holds.

Completing a run's *registry* transition and syncing its *GitHub* label/
comment are two separate steps for exactly this reason, and complete() is
not the only caller of the second step -- resync_pending() (below) is a
second entry point into the same GitHub calls, so complete()'s terminal-
status guard alone does not prevent a double-post between the two. That
guard is enforced separately, inside _sync_github() itself, via a claim
lease on `Run.gh_sync_claimed_at`: whichever caller (complete() or
resync_pending()) claims an unclaimed-or-stale run first is the only one
that reaches the GitHub calls; a concurrent second caller sees the fresh
claim and skips. The lease (not a one-shot flag) means a caller that claims
and then dies mid-network-call doesn't strand the run unsynced forever --
resync_pending() can reclaim once the lease goes stale.

If the unlocked GitHub calls fail partway (network error, etc.), the
registry's internal state is already correctly terminal, but the issue's
`workflow:*` label may not have moved off `workflow:in-progress` -- a
GitHub-visible split from the registry's own view. Run.gh_synced records
whether the label/comment step actually completed; Dispatcher.resync_pending()
retries just that step for terminal runs where it didn't, giving that split
an actual recovery path instead of only a stderr print from the caller.
"""
import json
import subprocess
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

MAX_PARALLEL_WORKERS = 2
DELEGATION_DEPTH = 1
GH_SYNC_CLAIM_LEASE_SECONDS = 30  # generous headroom over a real swap_label+comment round trip

LABEL_READY = "workflow:ready"
LABEL_IN_PROGRESS = "workflow:in-progress"
LABEL_REVIEW = "workflow:review"
LABEL_BLOCKED = "workflow:blocked"

FAILING_STATUSES = ("failed", "timed_out", "budget_exceeded", "blocked")


class GitHubError(RuntimeError):
    pass


class GitHubOps:
    """Thin wrapper around the gh CLI calls the dispatcher needs.

    Kept as a small object (not free functions) so tests can substitute a
    fake without touching the real GitHub API.
    """

    def _gh(self, *args: str) -> str:
        result = subprocess.run(["gh", *args], capture_output=True, text=True)
        if result.returncode != 0:
            raise GitHubError(result.stderr.strip())
        return result.stdout

    def get_labels(self, repo: str, issue_num: str) -> list[str]:
        out = self._gh("issue", "view", issue_num, "-R", repo, "--json", "labels")
        return [l["name"] for l in json.loads(out)["labels"]]

    def swap_label(self, repo: str, issue_num: str, remove: str, add: str) -> None:
        self._gh("issue", "edit", issue_num, "-R", repo, "--remove-label", remove, "--add-label", add)

    def comment(self, repo: str, issue_num: str, body: str) -> None:
        self._gh("issue", "comment", issue_num, "-R", repo, "--body", body)


@dataclass
class Run:
    run_id: str
    issue_id: str  # "owner/repo#N"
    workflow: str
    worker_role: str
    runtime: str
    claimed_at: float
    lease_seconds: int
    status: str = "in_progress"
    parent_run_id: Optional[str] = None
    heartbeat_at: float = field(default=0.0)
    finished_at: Optional[float] = None
    result: Optional[dict] = None
    gh_synced: bool = False  # set True once complete()'s GitHub label/comment step actually succeeds
    gh_sync_claimed_at: Optional[float] = None  # set while a _sync_github() call owns this run's GitHub step

    def gh_sync_claim_stale(self, now: Optional[float] = None) -> bool:
        """A claim older than GH_SYNC_CLAIM_LEASE_SECONDS is treated as
        abandoned (the claiming call presumably crashed or is stuck), so a
        later resync_pending() may re-claim and retry rather than skip this
        run forever."""
        if self.gh_sync_claimed_at is None:
            return True
        now = time.time() if now is None else now
        return now - self.gh_sync_claimed_at > GH_SYNC_CLAIM_LEASE_SECONDS

    def is_expired(self, now: Optional[float] = None) -> bool:
        now = time.time() if now is None else now
        return now - self.claimed_at > self.lease_seconds


class RunRegistry:
    """Content-free JSON store of runs: identifiers and timestamps only.

    Backs the query-by-run_id requirement in dispatch-contract.md: a run's
    status/timestamps/result must be queryable, not just delivered as an
    unsolicited completion message.
    """

    def __init__(self, path: Path):
        self.path = path
        self._runs: dict[str, Run] = {}
        if path.exists():
            data = json.loads(path.read_text())
            self._runs = {rid: Run(**r) for rid, r in data.items()}

    def _flush(self) -> None:
        self.path.write_text(json.dumps({rid: asdict(r) for rid, r in self._runs.items()}, indent=2))

    def add(self, run: Run) -> None:
        self._runs[run.run_id] = run
        self._flush()

    def get(self, run_id: str) -> Optional[Run]:
        return self._runs.get(run_id)

    def update(self, run_id: str, **fields) -> Run:
        run = self._runs[run_id]
        for k, v in fields.items():
            setattr(run, k, v)
        self._flush()
        return run

    def active_issue_ids(self) -> set[str]:
        return {r.issue_id for r in self._runs.values() if r.status == "in_progress"}


class Dispatcher:
    def __init__(self, registry: RunRegistry, gh: Optional[GitHubOps] = None):
        self.registry = registry
        self.gh = gh or GitHubOps()
        # RLock, not Lock: sweep_expired() holds the lock while calling
        # complete() on the same thread, and complete()/heartbeat() must
        # themselves be lock-protected once a caller other than claim() can
        # run concurrently (see worker_adapters.dispatch_async — the first
        # caller that completes a run from a background thread while the
        # main thread may be heartbeating/sweeping another run).
        self._lock = threading.RLock()

    def claim(self, issue_id: str, workflow: str, worker_role: str, runtime: str, lease_seconds: int) -> Run:
        repo, num = issue_id.split("#")
        with self._lock:
            active = self.registry.active_issue_ids()
            if issue_id in active:
                raise RuntimeError(f"{issue_id} already has an active claim")
            if len(active) >= MAX_PARALLEL_WORKERS:
                raise RuntimeError(f"max_parallel_workers={MAX_PARALLEL_WORKERS} reached")

            labels = self.gh.get_labels(repo, num)
            if LABEL_READY not in labels:
                raise RuntimeError(f"{issue_id} is not {LABEL_READY} (labels={labels})")

            run_id = f"{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}_{uuid.uuid4().hex[:8]}"
            run = Run(
                run_id=run_id,
                issue_id=issue_id,
                workflow=workflow,
                worker_role=worker_role,
                runtime=runtime,
                claimed_at=time.time(),
                lease_seconds=lease_seconds,
                heartbeat_at=time.time(),
            )
            self.registry.add(run)
            self.gh.swap_label(repo, num, LABEL_READY, LABEL_IN_PROGRESS)
            self.gh.comment(repo, num, self._claim_comment(run))
            return run

    def spawn_child(self, parent_run_id: str, n: int) -> Run:
        """delegation_depth=1: exactly one level of children, same issue_id."""
        with self._lock:
            parent = self.registry.get(parent_run_id)
            if parent is None:
                raise RuntimeError(f"unknown parent run_id {parent_run_id}")
            if parent.parent_run_id is not None:
                raise RuntimeError("delegation_depth=1 exceeded: parent is itself a child run")
            child = Run(
                run_id=f"{parent_run_id}.{n}",
                issue_id=parent.issue_id,
                workflow=parent.workflow,
                worker_role=parent.worker_role,
                runtime=parent.runtime,
                claimed_at=time.time(),
                lease_seconds=parent.lease_seconds,
                parent_run_id=parent_run_id,
                heartbeat_at=time.time(),
            )
            self.registry.add(child)
            return child

    def heartbeat(self, run_id: str) -> None:
        with self._lock:
            self.registry.update(run_id, heartbeat_at=time.time())

    def query(self, run_id: str) -> Optional[dict]:
        run = self.registry.get(run_id)
        if run is None:
            return None
        d = asdict(run)
        d["elapsed_seconds"] = time.time() - run.claimed_at
        return d

    def sweep_expired(self) -> list[str]:
        """Move expired in_progress claims (top-level or child) to timed_out.

        Only a top-level run's expiry moves the issue's label (see complete());
        a child run's expiry is recorded in the registry but leaves the label
        alone, since the parent still owns the issue's workflow state.
        """
        with self._lock:
            expired = [
                (run.run_id, run.lease_seconds)
                for run in self.registry._runs.values()
                if run.status == "in_progress" and run.is_expired()
            ]
        swept = []
        for run_id, lease_seconds in expired:
            try:
                self.complete(
                    run_id,
                    "timed_out",
                    {"error": f"lease expired after {lease_seconds}s with no completion"},
                )
                swept.append(run_id)
            except RuntimeError:
                # Someone else (e.g. the run's own worker) completed it
                # between the snapshot above and this call -- not a bug,
                # just lost the race to a legitimate completion.
                pass
        return swept

    def complete(self, run_id: str, status: str, result_envelope: dict) -> Run:
        """Record a terminal result and, for a top-level run, move the issue's label.

        `cancelled` is an operator-initiated abort, not a failure: it returns
        the issue to workflow:ready so it can be redispatched with a fresh
        run_id, rather than workflow:blocked (reserved for structured,
        non-recoverable results per dispatch-contract.md).

        The registry transition (the only part that must be race-free) is
        atomic under `self._lock`; the GitHub label swap/comment happen
        afterward, unlocked, so a slow network call here cannot stall other
        runs' heartbeat()/sweep_expired(). If that unlocked GitHub step
        fails, the run is still correctly terminal internally
        (`Run.gh_synced` stays False and the exception propagates) --
        `resync_pending()` is the recovery path for that split, not a
        silent retry loop here.
        """
        with self._lock:
            run = self.registry.get(run_id)
            if run is None:
                raise RuntimeError(f"unknown run_id {run_id}")
            if run.status != "in_progress":
                raise RuntimeError(
                    f"run {run_id} already terminal (status={run.status!r}); "
                    "refusing a second complete() to avoid a double label/comment"
                )
            self.registry.update(run_id, status=status, finished_at=time.time(), result=result_envelope)

        if run.parent_run_id is None:
            self._sync_github(run_id, run.issue_id, status, result_envelope)
        return self.registry.get(run_id)

    def _sync_github(self, run_id: str, issue_id: str, status: str, result_envelope: dict) -> bool:
        """Post the label swap + result comment for a just-completed top-level
        run. Separated from complete() so resync_pending() can retry just
        this step without re-running the (already-done, must-stay-atomic)
        registry transition.

        Race-guarded independently of complete()'s own terminal-status check:
        this is the second entry point into the same GitHub calls (the first
        being complete() itself), so it needs its own atomic claim rather
        than relying on a guard that only covers complete() vs. complete().
        The claim is a lease (`Run.gh_sync_claimed_at`), not a one-shot flag,
        so a caller that claims and then dies mid-network-call doesn't strand
        the run unsynced forever -- a later call can reclaim once the lease
        goes stale. Returns True if this call actually performed the sync,
        False if it was skipped (already synced, or another call currently
        holds an unexpired claim).
        """
        with self._lock:
            run = self.registry.get(run_id)
            if run is None or run.gh_synced:
                return False
            if not run.gh_sync_claim_stale():
                return False  # another call is actively syncing this run right now
            self.registry.update(run_id, gh_sync_claimed_at=time.time())

        repo, num = issue_id.split("#")
        if status == "cancelled":
            target = LABEL_READY
        elif status in FAILING_STATUSES:
            target = LABEL_BLOCKED
        else:
            target = LABEL_REVIEW
        self.gh.swap_label(repo, num, LABEL_IN_PROGRESS, target)
        self.gh.comment(repo, num, self._result_comment(run_id, status, result_envelope))
        with self._lock:
            self.registry.update(run_id, gh_synced=True)
        return True

    def resync_pending(self) -> list[str]:
        """Retry the GitHub label/comment step for terminal top-level runs
        where it didn't complete (Run.gh_synced is False) -- e.g. because
        complete()'s unlocked GitHub call raised (network error) after the
        registry was already correctly marked terminal, or because a claim
        lease expired mid-call. Safe to call concurrently with an in-flight
        complete()/_sync_github() or with another resync_pending() call:
        _sync_github()'s own claim lease is what prevents a double sync, not
        this method's snapshot. Returns the run_ids actually synced by this
        call (a run skipped because someone else currently holds the claim
        is not an error -- it isn't stuck, just handled elsewhere)."""
        with self._lock:
            pending = [
                (run.run_id, run.issue_id, run.status, run.result)
                for run in self.registry._runs.values()
                if run.parent_run_id is None and run.status != "in_progress" and not run.gh_synced
            ]
        synced = []
        for run_id, issue_id, status, result in pending:
            try:
                if self._sync_github(run_id, issue_id, status, result or {}):
                    synced.append(run_id)
            except GitHubError:
                # Still failing (e.g. GitHub still unreachable) -- the claim
                # lease will go stale and a later resync_pending() call can
                # retry; don't let one stuck run block the rest of this pass.
                continue
        return synced

    @staticmethod
    def _claim_comment(run: Run) -> str:
        return (
            "Claimed by dispatcher.\n"
            f"run_id: `{run.run_id}`\n"
            f"runtime: {run.runtime}\n"
            f"worker_role: {run.worker_role}\n"
            f"claimed_at: {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(run.claimed_at))}\n"
            f"lease_seconds: {run.lease_seconds}\n"
            "status: workflow:ready -> workflow:in-progress (dispatch-contract.md)."
        )

    @staticmethod
    def _result_comment(run_id: str, status: str, envelope: dict) -> str:
        rows = "\n".join(f"| {k} | {v} |" for k, v in envelope.items())
        return f"## Run result: `{run_id}`\n\n| Field | Value |\n|---|---|\n| status | {status} |\n{rows}\n"
