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
complete()/heartbeat()/sweep_expired(), not just claim(): once a worker can
complete asynchronously from a background thread (see
scripts/worker_adapters.py), the main thread may legitimately call
heartbeat()/sweep_expired() while that thread's complete() is in flight, and
without this lock both racing writers hit RunRegistry's unsynchronized
file rewrite. complete() also refuses a second call on an already-terminal
run_id, so a losing racer fails loudly instead of double-posting a result.
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
        swept = []
        with self._lock:
            for run in list(self.registry._runs.values()):
                if run.status == "in_progress" and run.is_expired():
                    self.complete(
                        run.run_id,
                        "timed_out",
                        {"error": f"lease expired after {run.lease_seconds}s with no completion"},
                    )
                    swept.append(run.run_id)
        return swept

    def complete(self, run_id: str, status: str, result_envelope: dict) -> Run:
        """Record a terminal result and, for a top-level run, move the issue's label.

        `cancelled` is an operator-initiated abort, not a failure: it returns
        the issue to workflow:ready so it can be redispatched with a fresh
        run_id, rather than workflow:blocked (reserved for structured,
        non-recoverable results per dispatch-contract.md).
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
                repo, num = run.issue_id.split("#")
                if status == "cancelled":
                    target = LABEL_READY
                elif status in FAILING_STATUSES:
                    target = LABEL_BLOCKED
                else:
                    target = LABEL_REVIEW
                self.gh.swap_label(repo, num, LABEL_IN_PROGRESS, target)
                self.gh.comment(repo, num, self._result_comment(run_id, status, result_envelope))
            return self.registry.get(run_id)

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
