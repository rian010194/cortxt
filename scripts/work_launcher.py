#!/usr/bin/env python3
"""Operator-facing parallel work launcher built on the dispatch contract."""
from __future__ import annotations

import inspect
import json
import re
import subprocess
import sys
import time
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from dispatcher import Dispatcher, RunRegistry
from execution_map import (ClaimConflict, ClaimRecord, ClaimStore, Issue,
                           SqliteClaimStore, collision_keys, derive_graph,
                           preflight_validate, validate_receipt)
from launcher_inventory import (InventoryUnavailable, daemon_claims_reader,
                                dispatcher_registry_reader, git_resources_reader,
                                lifecycle_sessions_reader, make_graph_reader,
                                writer_domain_reader)
from worker_adapters import (UnknownRuntimeError, dispatch_async,
                             runtime_launch_config_ok)

FORBIDDEN = re.compile(r"[\u00e5\u00e4\u00f6\u00c5\u00c4\u00d6]")
DEFAULT_ARTIFACT_POLICY = (
    "Commit only English project artifacts on a feature branch. Do not push, merge, "
    "close issues, expose secrets, copy full prompts, or record model reasoning."
)


class ExecutionGateError(RuntimeError):
    """Stable, content-free launcher rejection."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class LauncherDispatchError(RuntimeError):
    """Stable adapter-start failure surfaced through the launcher boundary.

    Covers "engine routed but no adapter registered" (unavailable engine) and
    worktree-creation failure at launch time, so the action host can render a
    stable category plus recovery guidance instead of a generic 500.
    """

    category = "adapter_start_failed"

    def __init__(self, code: str, recovery: str | None = None):
        self.code = code
        self.recovery = recovery or "Inspect the launcher/worker log and retry with a fresh run."
        super().__init__(code)


class LauncherGitHub:
    """Small injectable GitHub port used by the launcher."""

    def _gh(self, *args: str) -> str:
        proc = subprocess.run(["gh", *args], capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=20)
        if proc.returncode:
            raise RuntimeError(proc.stderr.strip())
        return proc.stdout

    def create_issue(self, repo: str, title: str, body: str) -> str:
        out = self._gh("issue", "create", "-R", repo, "--title", title, "--body", body,
                       "--label", "workflow:inbox")
        return f"{repo}#{out.strip().rstrip('/').split('/')[-1]}"

    def approve(self, issue_id: str) -> None:
        repo, number = issue_id.split("#", 1)
        self._gh("issue", "edit", number, "-R", repo, "--remove-label", "workflow:inbox",
                 "--add-label", "workflow:ready")

    def get_issue(self, issue_id: str) -> Mapping[str, Any]:
        repo, number = issue_id.split("#", 1)
        value = json.loads(self._gh("issue", "view", number, "-R", repo, "--json",
                                    "body,state,labels,milestone"))
        return {"issue_id": issue_id, "body": value.get("body", ""),
                "state": value.get("state", "open").lower(), "labels": value.get("labels", ()),
                "area": "dispatch", "milestone": (value.get("milestone") or {}).get("title") or "dispatch"}


def generate_worker_prompt(scope: str, acceptance_criteria: list[str], limits: dict,
                           artifact_policy: str = DEFAULT_ARTIFACT_POLICY) -> str:
    values = [scope, artifact_policy, *acceptance_criteria]
    if any(FORBIDDEN.search(value or "") for value in values):
        raise ValueError("scope content must contain only English ASCII letters")
    if not scope.strip() or not acceptance_criteria:
        raise ValueError("scope and acceptance criteria are required")
    limit_lines = "\n".join(f"- {key}: {value}" for key, value in sorted(limits.items()))
    ac_lines = "\n".join(f"- {item}" for item in acceptance_criteria)
    return ("You are a bounded worker.\n\nScope\n-----\n" + scope.strip() +
            "\n\nAcceptance criteria\n-------------------\n" + ac_lines +
            "\n\nLimits\n------\n" + limit_lines +
            "\n\nArtifact policy\n---------------\n" + artifact_policy + "\n")


def parse_scope_file(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    if FORBIDDEN.search(text):
        raise ValueError("scope file contains forbidden diacritics")
    title = next((line[2:].strip() for line in text.splitlines() if line.startswith("# ")), path.stem)
    before, sep, after = text.partition("## Acceptance criteria")
    criteria = [line[2:].strip() for line in after.splitlines() if line.startswith("- ")] if sep else []
    return {"title": title, "scope": before.replace(f"# {title}", "", 1).strip(),
            "acceptance_criteria": criteria}


class WorkLauncher:
    INVENTORY_NAMES = ("active_claims", "dispatcher_registry", "daemon_claims",
                       "git_resources", "lifecycle_sessions")

    def __init__(self, dispatcher: Dispatcher, github: LauncherGitHub,
                 dispatch: Callable = dispatch_async, worktree_root: Path | None = None,
                 run_worktree: Callable[..., object] = subprocess.run, *,
                 claim_store: ClaimStore | None = None,
                 issue_reader: Callable[[str], Mapping[str, Any] | Issue] | None = None,
                 graph_reader: Callable[[str], Sequence[Mapping[str, Any] | Issue]] | None = None,
                 inventory_readers: Mapping[str, Callable[[], Sequence[Mapping[str, Any]]]] | None = None,
                 writer_reader: Callable[[], Sequence[Mapping[str, Any]]] | None = None,
                 clock: Callable[[], float] = time.time,
                 id_generator: Callable[[], str] | None = None,
                 driver_id: str = "cortxt-work", store_session_id: str | None = None,
                 engine_session_id: str | None = None,
                 repo_path: Path | None = None):
        self.dispatcher, self.github, self.dispatch = dispatcher, github, dispatch
        self.worktree_root = worktree_root or Path(".worktrees")
        self.run_worktree, self.claim_store = run_worktree, claim_store
        self.issue_reader = issue_reader or getattr(github, "get_issue", self._missing_issue_reader)
        self.graph_reader = graph_reader
        self.inventory_readers = dict(inventory_readers or {})
        self.writer_reader, self.clock = writer_reader or (lambda: ()), clock
        self.id_generator = id_generator or (lambda: f"run-{uuid.uuid4().hex}")
        self.driver_id, self.store_session_id = driver_id, store_session_id
        self.engine_session_id = engine_session_id
        # The repository the launcher operates on. Worktrees are created from
        # this directory (never the CLI's cwd) and each worker subprocess runs
        # inside its own created worktree (#419).
        self.repo_path = repo_path or Path.cwd()
        self._claims_by_run: dict[str, ClaimRecord] = {}

    @staticmethod
    def _missing_issue_reader(issue_id: str) -> Mapping[str, Any]:
        raise ExecutionGateError("issue_reader_required")

    def _snapshot(self) -> tuple[dict[str, Sequence[Mapping[str, Any]]], Sequence[Mapping[str, Any]], list[tuple[str, str]]]:
        inventories: dict[str, Sequence[Mapping[str, Any]]] = {}
        unavailable: list[tuple[str, str]] = []
        for name in self.INVENTORY_NAMES:
            reader = self.inventory_readers.get(name)
            if reader is None:
                inventories[name] = ()
                continue
            try:
                inventories[name] = tuple(reader())
            except InventoryUnavailable as exc:
                inventories[name] = ()
                unavailable.append((name, str(exc)))
        return inventories, tuple(self.writer_reader()), unavailable

    def _gate(self, issue_id: str, workflow: str, runtime: str, lease: int,
              run_id: str, worktree: Path) -> tuple[ClaimRecord, object]:
        if self.claim_store is None:
            raise ExecutionGateError("execution_map_store_required")
        first = self.issue_reader(issue_id)
        issue = first if isinstance(first, Issue) else Issue.from_dict(first)
        graph_values = self.graph_reader(issue_id) if self.graph_reader else (issue,)
        graph = derive_graph(graph_values)
        inventories, writers, unavailable = self._snapshot()
        if unavailable:
            raise ExecutionGateError("inventory_unavailable")
        # A disjoint concurrent acquire may advance the store generation between
        # read and conditional insert. Re-snapshot boundedly; a real overlap is
        # then observed as an occupied resource and remains a stable rejection.
        for _ in range(3):
            result = preflight_validate(issue=issue, graph=graph, run_id=run_id, worktree=worktree,
                store_session_id=self.store_session_id, engine_id=runtime,
                engine_session_id=self.engine_session_id, driver_id=self.driver_id, workflow=workflow,
                store=self.claim_store, inventories=inventories, writers=writers,
                now=self.clock(), ttl_seconds=lease, acquire=True)
            if result.collision_codes != ("resource_collision",):
                break
        if result.decision != "allow" or result.receipt is None:
            raise ExecutionGateError(result.collision_codes[0] if result.collision_codes else "gate_rejected")
        claim = next((x for x in self.claim_store.active_claims(self.clock())
                      if x.claim_id == result.receipt.claim_id), None)
        if claim is None:
            raise ExecutionGateError("claim_not_active")
        reread = self.issue_reader(issue_id)
        fresh = reread if isinstance(reread, Issue) else Issue.from_dict(reread)
        if fresh.labels != issue.labels or fresh.state != issue.state:
            self._release(claim, "stale_receipt")
            raise ExecutionGateError("stale_issue_generation")
        snapshot = {"issue": asdict(issue), "graph_drift": [asdict(x) for x in graph.drift],
                    "inventories": inventories, "writers": writers,
                    "generation": result.receipt.claim_generation - 1}
        resources = collision_keys(issue_id=issue.issue_id, run_id=run_id, worktree=worktree,
            workflow_label="workflow:ready", store_session_id=self.store_session_id,
            engine_session_id=self.engine_session_id)
        if not isinstance(self.claim_store, SqliteClaimStore) or not validate_receipt(
                result.receipt, snapshot=snapshot, claim=claim, resources=resources,
                run_id=run_id, store=self.claim_store, now=self.clock()):
            self._release(claim, "stale_receipt")
            raise ExecutionGateError("stale_receipt")
        return claim, result.receipt

    def _on_worker_terminal(self, run_id: str, status: str) -> None:
        """Release run_id's execution-map claim once its Run goes terminal.

        Wired as dispatch_async's `on_terminal` hook so every terminal
        status the background worker thread produces -- succeeded, failed,
        or timed_out -- releases the claim, not just the ones that happen to
        flow back through `submit()`. Never raises: a release failure here
        must not crash the worker thread or hide the Run's real completion;
        it is printed to stderr, matching the launcher's other best-effort
        terminal bookkeeping (see `_fail_launch`).
        """
        if self.claim_store is None:
            return
        claim = self._claims_by_run.pop(run_id, None)
        if claim is None:
            claim = next((x for x in self.claim_store.active_claims(self.clock())
                         if x.run_id == run_id), None)
        if claim is None:
            return
        try:
            self._release(claim, f"terminal:{status}")
        except ExecutionGateError as exc:
            print(f"[work_launcher] failed to release claim for {run_id}: {exc}", file=sys.stderr)

    def sweep_expired(self) -> list[str]:
        """Sweep expired in-progress runs to timed_out and release their
        execution-map claims.

        `Dispatcher.sweep_expired()` alone only moves the Run registry to
        timed_out (a stuck worker thread that never itself completes, e.g. a
        crashed subprocess whose adapter never returned); it has no
        knowledge of the execution-map claim, so a caller that only ever
        calls `dispatcher.sweep_expired()` directly leaves those claims held
        forever. This wrapper is the sanctioned path for both.
        """
        swept = self.dispatcher.sweep_expired()
        for run_id in swept:
            self._on_worker_terminal(run_id, "timed_out")
        return swept

    def _release(self, claim: ClaimRecord, reason: str) -> None:
        try:
            self.claim_store.release(claim.claim_id, claim.run_id, claim.driver_id,
                                     claim.claim_generation, reason, now=self.clock())
        except ClaimConflict:
            raise ExecutionGateError("claim_release_conflict")

    def _fail_launch(self, run_id: str, claim: ClaimRecord, exc: BaseException) -> None:
        """Make a post-claim launch failure terminal and release the claim.

        The Dispatcher claim is already durable by the time any adapter-start
        failure can occur, so a failed worker start must never leave the Run
        ``in_progress`` without a live worker: the Run is marked terminal
        (``blocked`` with stable ``adapter_start_failed`` evidence) through the
        sanctioned dispatcher completion path, and the execution-map claim is
        released with an attributable terminal reason. Original Run history is
        preserved: ``Dispatcher.complete`` refuses a second terminal
        transition, so a later legitimate completion cannot overwrite this
        record, and retry always requires a fresh ``run_id`` and fresh receipt.
        """
        evidence = {
            "category": "adapter_start_failed",
            "code": getattr(exc, "code", None) or exc.__class__.__name__,
            "recovery": getattr(exc, "recovery", None) or str(exc),
        }
        try:
            self.dispatcher.complete(
                run_id, "blocked",
                {"error": evidence,
                 "evidence": f"worker start failed before dispatch: {type(exc).__name__}"})
        except Exception as complete_exc:  # noqa: BLE001 - best-effort terminal marker
            # The Run may not exist yet (failure before the dispatcher claim
            # landed) or complete() itself failed; the claim release still runs.
            print(f"[work_launcher] failed to mark {run_id} terminal: {complete_exc}",
                  file=sys.stderr)
        finally:
            try:
                self._release(claim, "terminal:adapter_start_failed")
            except ExecutionGateError as release_exc:
                print(f"[work_launcher] failed to release claim for {run_id}: {release_exc}",
                      file=sys.stderr)

    def _claim_dispatcher(self, run_id: str, *args: Any):
        if "run_id" not in inspect.signature(self.dispatcher.claim).parameters:
            raise ExecutionGateError("dispatcher_run_id_unsupported")
        run = self.dispatcher.claim(*args, run_id=run_id)
        if run.run_id != run_id:
            raise ExecutionGateError("dispatcher_run_id_mismatch")
        return run

    def _dispatch(self, run, prompt: str, worktree: Path) -> None:
        """Start the worker, bound to its isolated worktree when one exists.

        The worktree is passed to the adapter (dispatch_async -> invoke) so the
        worker subprocess runs with that directory as cwd. A worktree path that
        was never created (the resume path) is not forwarded -- there is no
        directory to bind to, and inventing one would break the worker.

        An engine with no registered adapter (adapter-start failure) is mapped
        to a stable `LauncherDispatchError` with recovery guidance instead of a
        generic exception.
        """
        try:
            # `on_terminal` releases the execution-map claim once the async
            # worker actually reaches a terminal status, regardless of which
            # status that is (succeeded, failed, or timed_out via the
            # adapter's own timeout handling): dispatch_async's background
            # thread calls Dispatcher.complete() directly and never went
            # through WorkLauncher.submit(), so without this hook a claim
            # stayed held past its Run's terminal transition (S7b terminal-
            # claim-release dogfood defect).
            kwargs = {"worktree": worktree} if worktree.is_dir() else {}
            # `self.dispatch` is injectable (tests pass minimal fakes with a
            # fixed 3-arg signature); only forward on_terminal when the
            # callable actually declares it, so existing fakes keep working
            # unchanged.
            if "on_terminal" in inspect.signature(self.dispatch).parameters:
                kwargs["on_terminal"] = self._on_worker_terminal
            self.dispatch(self.dispatcher, run, prompt, **kwargs)
        except UnknownRuntimeError as exc:
            raise LauncherDispatchError(
                "adapter_not_registered",
                recovery=f"No adapter is registered for runtime {run.runtime!r}; register an adapter, or "
                         f"approve an issue Engine policy that routes to a registered engine.") from exc

    ISOLATION_WORKTREE = "worktree"
    ISOLATION_SHARED = "shared-checkout"

    def _isolation_result(self, run_id: str, worktree: Path, created: bool) -> dict:
        """Describe the working directory the worker was actually given.

        S7d (#473), from the #472 dogfood finding 8: this used to return
        ``branch: f"work/{run_id}"`` and the worktree path unconditionally,
        including on the resume path that never creates either. The reported
        branch was constructed from the run_id rather than projected from
        durable state, so a reviewer saw a plausible `work/<run_id>` branch
        that had never existed and no signal that the change had landed in
        the launcher's own checkout instead. A launch result now describes
        only what exists: an isolated run reports its real branch/worktree, a
        shared-checkout run reports ``None`` for both plus the repository
        directory the worker actually ran in.
        """
        if created:
            return {"worktree": str(worktree), "branch": f"work/{run_id}",
                    "isolation": self.ISOLATION_WORKTREE, "working_dir": str(worktree)}
        return {"worktree": None, "branch": None,
                "isolation": self.ISOLATION_SHARED, "working_dir": str(self.repo_path)}

    def _record_isolation(self, run_id: str, created: bool) -> None:
        """Carry the isolation mode onto the durable Run record.

        Best-effort: a registry without `update` (older/injected fakes) simply
        keeps no isolation field, and recording it must never fail a launch
        that has otherwise succeeded.
        """
        registry = getattr(self.dispatcher, "registry", None)
        if registry is None or not hasattr(registry, "update"):
            return
        fields = {"isolation": self.ISOLATION_WORKTREE if created else self.ISOLATION_SHARED,
                  "branch": f"work/{run_id}" if created else None}
        try:
            registry.update(run_id, **fields)
        except Exception as exc:  # noqa: BLE001 - provenance metadata, never fatal
            print(f"[work_launcher] could not record isolation for {run_id}: {exc}",
                  file=sys.stderr)

    def _launch(self, issue_id: str, prompt: str, *, runtime: str, worker_role: str,
                workflow: str, max_runtime_seconds: int, create_worktree: bool,
                max_cost_usd: float | None = None,
                max_parallel_workers: int | None = None,
                delegation_depth: int | None = None,
                artifact_policy: str | None = None,
                request_id: str | None = None) -> dict:
        # Single authoritative pre-claim config gate (S7b #482 follow-on):
        # `runtime_launch_config_ok` is the same function the eligibility
        # projection consults (action_host._build_dispatch_request,
        # cli_ports.gh_claim_run_resume), so a runtime that eligibility
        # reported as launchable can never diverge from what actually starts
        # here. Checked before ANY claim (execution-map gate or Dispatcher
        # claim) is created -- a missing provider/model/auth-config runtime
        # must fail closed before touching either claim store, not just when
        # the adapter itself later refuses to start.
        if not runtime_launch_config_ok(runtime):
            raise ExecutionGateError("runtime_not_configured")
        if self.claim_store is None:
            # Legacy (pre-#262) path: no execution-map gate; Dispatcher owns the run_id.
            run = self.dispatcher.claim(issue_id, workflow, worker_role, runtime,
                                        max_runtime_seconds)
            run_id = run.run_id
            worktree = self.worktree_root / run_id
            if create_worktree:
                branch = f"work/{run_id}"
                self.worktree_root.mkdir(parents=True, exist_ok=True)
                proc = self.run_worktree(["git", "worktree", "add", "-b", branch,
                                          str(worktree), "HEAD"], capture_output=True, text=True,
                                         cwd=str(self.repo_path))
                if getattr(proc, "returncode", 0):
                    self.dispatcher.complete(run_id, "blocked",
                                             {"error": "isolated worktree creation failed"})
                    raise LauncherDispatchError(
                        "worktree_creation_failed",
                        recovery="Ensure the worktree root is writable and retry with a fresh run.")
            self._record_isolation(run_id, create_worktree)
            self._dispatch(run, prompt, worktree)
            return {"issue_id": issue_id, "run_id": run_id,
                    **self._isolation_result(run_id, worktree, create_worktree)}

        # Per-request worker ceiling, carried from the approved dispatch request
        # and enforced before any claim is acquired (issue #471 AC2/AC4).
        if max_parallel_workers is not None and hasattr(self.dispatcher.registry, "active_issue_ids"):
            if len(self.dispatcher.registry.active_issue_ids()) >= max_parallel_workers:
                raise ExecutionGateError("max_parallel_workers_reached")

        run_id = self.id_generator()
        worktree = self.worktree_root / run_id
        claim, receipt = self._gate(issue_id, workflow, runtime, max_runtime_seconds, run_id, worktree)
        try:
            run = self._claim_dispatcher(run_id, issue_id, workflow, worker_role, runtime,
                                         max_runtime_seconds)
            # Carry the full dispatch request onto the durable run record so the
            # claim/run identity reflects the executed mandate (issue #471 AC2).
            limit_fields = {}
            if max_cost_usd is not None:
                limit_fields["max_cost_usd"] = max_cost_usd
            if max_parallel_workers is not None:
                limit_fields["max_parallel_workers"] = max_parallel_workers
            if delegation_depth is not None:
                limit_fields["delegation_depth"] = delegation_depth
            if artifact_policy is not None:
                limit_fields["artifact_policy"] = artifact_policy
            if request_id is not None:
                limit_fields["request_id"] = request_id
            if limit_fields and hasattr(self.dispatcher.registry, "update"):
                self.dispatcher.registry.update(run_id, **limit_fields)
            if create_worktree:
                branch = f"work/{run_id}"
                self.worktree_root.mkdir(parents=True, exist_ok=True)
                proc = self.run_worktree(["git", "worktree", "add", "-b", branch,
                                          str(worktree), "HEAD"], capture_output=True, text=True,
                                         cwd=str(self.repo_path))
                if getattr(proc, "returncode", 0):
                    failure = LauncherDispatchError(
                        "worktree_creation_failed",
                        recovery="Ensure the worktree root is writable and retry with a fresh run.")
                    self._fail_launch(run_id, claim, failure)
                    raise failure
            self._record_isolation(run_id, create_worktree)
            self._claims_by_run[run_id] = claim
            self._dispatch(run, prompt, worktree)
            return {"issue_id": issue_id, "run_id": run_id,
                    **self._isolation_result(run_id, worktree, create_worktree),
                    "claim_id": claim.claim_id,
                    "claim_generation": claim.claim_generation,
                    "receipt_id": receipt.receipt_id, "store_session_id": claim.store_session_id,
                    "engine_session_id": claim.engine_session_id}
        except Exception as exc:
            # Any post-claim failure (adapter start, worktree creation,
            # dispatcher claim drift) must make the durable Run terminal and
            # release the claim -- never leave in_progress without a worker.
            self._fail_launch(run_id, claim, exc)
            raise

    def create(self, repo: str, title: str, scope: str, acceptance_criteria: list[str], *,
               runtime: str, worker_role: str, workflow: str, max_runtime_seconds: int,
               max_cost_usd: float, approved: bool) -> dict:
        if not approved:
            raise ValueError("operator approval is required before claim and dispatch")
        limits = {"max_cost_usd": max_cost_usd, "max_runtime_seconds": max_runtime_seconds,
                  "max_parallel_workers": "operator policy", "delegation_depth": 0}
        prompt = generate_worker_prompt(scope, acceptance_criteria, limits)
        body = f"## Scope\n\n{scope}\n\n## Acceptance criteria\n\n" + "\n".join(f"- {x}" for x in acceptance_criteria)
        issue_id = self.github.create_issue(repo, title, body)
        self.github.approve(issue_id)
        return self._launch(issue_id, prompt, runtime=runtime, worker_role=worker_role,
                            workflow=workflow, max_runtime_seconds=max_runtime_seconds,
                            create_worktree=True)

    def resume(self, issue_id: str, *, runtime: str, worker_role: str, workflow: str,
               max_runtime_seconds: int, prompt: str,
               max_cost_usd: float | None = None,
               max_parallel_workers: int | None = None,
               delegation_depth: int | None = None,
               artifact_policy: str | None = None,
               request_id: str | None = None,
               isolate: bool = False) -> dict:
        """Resume a ready issue with the full approved dispatch request.

        The dispatch-contract fields (cost ceiling, parallel-worker ceiling,
        delegation depth, artifact policy, request snapshot id) are carried
        onto the durable claim/run record and enforced: the worker ceiling is
        checked before any claim, the cost ceiling is enforced in `submit()`
        (a reported cost above the ceiling is recorded as budget_exceeded,
        never silently accepted as success), and delegation depth is enforced
        per run by `Dispatcher.spawn_child`.

        `isolate` requests one isolated linked git worktree plus a
        `work/<run_id>` branch for this run, the same physical isolation
        `create()` uses. It defaults to False because that is the behavior the
        UI launch path has today (#472 finding 6/8); an approved mandate whose
        artifact policy requires the change to stay inside the run's own
        worktree must pass `isolate=True`, and a worktree that cannot be
        created then fails the launch closed rather than silently downgrading
        to the shared checkout.
        """
        return self._launch(issue_id, prompt, runtime=runtime, worker_role=worker_role,
                            workflow=workflow, max_runtime_seconds=max_runtime_seconds,
                            create_worktree=isolate, max_cost_usd=max_cost_usd,
                            max_parallel_workers=max_parallel_workers,
                            delegation_depth=delegation_depth,
                            artifact_policy=artifact_policy, request_id=request_id)

    def submit(self, run_id: str, result: dict) -> dict:
        """Record a terminal result, enforcing the approved cost ceiling.

        When the run's mandate carries `max_cost_usd` and the result envelope
        reports a numeric cost above that ceiling, the run is recorded as
        `budget_exceeded` instead of whatever status the worker claimed --
        the platform never accepts an over-budget result as success.
        """
        registry = getattr(self.dispatcher, "registry", None)
        ceiling = None
        if registry is not None and hasattr(registry, "get"):
            run = registry.get(run_id)
            if run is not None:
                ceiling = getattr(run, "max_cost_usd", None)
        if ceiling is not None:
            cost = (result or {}).get("cost")
            if isinstance(cost, (int, float)) and not isinstance(cost, bool) and cost > ceiling:
                result = {**dict(result or {}), "status": "budget_exceeded",
                          "error": {"category": "budget_exceeded",
                                    "recovery": "Approved cost ceiling exceeded; amend the issue ceiling or "
                                                "reduce scope, then start a fresh run."}}
        run = self.dispatcher.complete(run_id, result["status"], result)
        claim = self._claims_by_run.pop(run_id, None)
        if claim is None and self.claim_store is not None:
            claim = next((x for x in self.claim_store.active_claims(self.clock()) if x.run_id == run_id), None)
        if claim is not None:
            self._release(claim, f"terminal:{run.status}")
        return {"issue_id": run.issue_id, "run_id": run.run_id, "status": run.status}

    def list_active(self) -> list[dict]:
        now = self.clock()
        claims = {x.run_id: x for x in (self.claim_store.active_claims(now) if self.claim_store else ())}
        runs = getattr(self.dispatcher.registry, "_runs", {})
        rows = []
        for run_id in sorted(set(runs) | set(claims)):
            run, claim = runs.get(run_id), claims.get(run_id)
            if run is not None and run.status != "in_progress" and claim is None:
                continue
            rows.append({"run_id": run_id, "issue_id": run.issue_id if run else claim.issue_id,
                         "run_status": run.status if run else None,
                         "claim_id": claim.claim_id if claim else None,
                         "claim_state": claim.state if claim else None,
                         "store_session_id": claim.store_session_id if claim else None,
                         "engine_session_id": claim.engine_session_id if claim else None,
                         "engine_id": claim.engine_id if claim else (run.runtime if run else None),
                         "claimed_at": run.claimed_at if run else claim.acquired_at,
                         "last_update": run.heartbeat_at if run else claim.heartbeat_at,
                         "elapsed_seconds": now - (run.claimed_at if run else claim.acquired_at),
                         "worker": run.worker_role if run else None})
        return sorted(rows, key=lambda x: (x["claimed_at"], x["run_id"]))

    combined_status = list_active


def default_launcher(registry_path: Path, *, daemon_state_dir: Path | None = None,
                     lifecycle_store: Path | None = None,
                     repo_path: Path | None = None) -> WorkLauncher:
    store = SqliteClaimStore(registry_path.with_suffix(".claims.sqlite3"))
    dispatcher = Dispatcher(RunRegistry(registry_path))
    github = LauncherGitHub()
    return WorkLauncher(
        dispatcher, github, claim_store=store,
        graph_reader=make_graph_reader(github.get_issue),
        inventory_readers={
            "active_claims": lambda: (),
            "dispatcher_registry": dispatcher_registry_reader(dispatcher.registry),
            "daemon_claims": daemon_claims_reader(daemon_state_dir),
            "git_resources": git_resources_reader(),
            "lifecycle_sessions": lifecycle_sessions_reader(lifecycle_store),
        },
        writer_reader=writer_domain_reader(),
        repo_path=repo_path,
    )
