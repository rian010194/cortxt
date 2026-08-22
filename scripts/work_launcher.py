#!/usr/bin/env python3
"""Operator-facing parallel work launcher built on the dispatch contract."""
from __future__ import annotations

import inspect
import json
import re
import subprocess
import time
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from dispatcher import Dispatcher, RunRegistry
from execution_map import (ClaimConflict, ClaimRecord, ClaimStore, Issue,
                           SqliteClaimStore, collision_keys, derive_graph,
                           preflight_validate, validate_receipt)
from worker_adapters import dispatch_async

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


class LauncherGitHub:
    """Small injectable GitHub port used by the launcher."""

    def _gh(self, *args: str) -> str:
        proc = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=20)
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
                 engine_session_id: str | None = None):
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
        self._claims_by_run: dict[str, ClaimRecord] = {}

    @staticmethod
    def _missing_issue_reader(issue_id: str) -> Mapping[str, Any]:
        raise ExecutionGateError("issue_reader_required")

    def _snapshot(self) -> tuple[dict[str, Sequence[Mapping[str, Any]]], Sequence[Mapping[str, Any]]]:
        inventories = {name: tuple(self.inventory_readers.get(name, lambda: ())())
                       for name in self.INVENTORY_NAMES}
        return inventories, tuple(self.writer_reader())

    def _gate(self, issue_id: str, workflow: str, runtime: str, lease: int,
              run_id: str, worktree: Path) -> tuple[ClaimRecord, object]:
        if self.claim_store is None:
            raise ExecutionGateError("execution_map_store_required")
        first = self.issue_reader(issue_id)
        issue = first if isinstance(first, Issue) else Issue.from_dict(first)
        graph_values = self.graph_reader(issue_id) if self.graph_reader else (issue,)
        graph = derive_graph(graph_values)
        inventories, writers = self._snapshot()
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

    def _release(self, claim: ClaimRecord, reason: str) -> None:
        try:
            self.claim_store.release(claim.claim_id, claim.run_id, claim.driver_id,
                                     claim.claim_generation, reason, now=self.clock())
        except ClaimConflict:
            raise ExecutionGateError("claim_release_conflict")

    def _claim_dispatcher(self, run_id: str, *args: Any):
        if "run_id" not in inspect.signature(self.dispatcher.claim).parameters:
            raise ExecutionGateError("dispatcher_run_id_unsupported")
        run = self.dispatcher.claim(*args, run_id=run_id)
        if run.run_id != run_id:
            raise ExecutionGateError("dispatcher_run_id_mismatch")
        return run

    def _launch(self, issue_id: str, prompt: str, *, runtime: str, worker_role: str,
                workflow: str, max_runtime_seconds: int, create_worktree: bool) -> dict:
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
                                          str(worktree), "HEAD"], capture_output=True, text=True)
                if getattr(proc, "returncode", 0):
                    self.dispatcher.complete(run_id, "blocked",
                                             {"error": "isolated worktree creation failed"})
                    raise RuntimeError("isolated worktree creation failed")
            self.dispatch(self.dispatcher, run, prompt)
            return {"issue_id": issue_id, "run_id": run_id, "worktree": str(worktree),
                    "branch": f"work/{run_id}"}

        run_id = self.id_generator()
        worktree = self.worktree_root / run_id
        claim, receipt = self._gate(issue_id, workflow, runtime, max_runtime_seconds, run_id, worktree)
        try:
            run = self._claim_dispatcher(run_id, issue_id, workflow, worker_role, runtime,
                                         max_runtime_seconds)
            if create_worktree:
                branch = f"work/{run_id}"
                self.worktree_root.mkdir(parents=True, exist_ok=True)
                proc = self.run_worktree(["git", "worktree", "add", "-b", branch,
                                          str(worktree), "HEAD"], capture_output=True, text=True)
                if getattr(proc, "returncode", 0):
                    self.dispatcher.complete(run_id, "blocked", {"error": "isolated worktree creation failed"})
                    self._release(claim, "terminal:blocked")
                    raise RuntimeError("isolated worktree creation failed")
            self._claims_by_run[run_id] = claim
            self.dispatch(self.dispatcher, run, prompt)
            return {"issue_id": issue_id, "run_id": run_id, "worktree": str(worktree),
                    "branch": f"work/{run_id}", "claim_id": claim.claim_id,
                    "claim_generation": claim.claim_generation,
                    "receipt_id": receipt.receipt_id, "store_session_id": claim.store_session_id,
                    "engine_session_id": claim.engine_session_id}
        except Exception:
            if run_id not in self._claims_by_run:
                self._release(claim, "launch_rejected")
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
               max_runtime_seconds: int, prompt: str) -> dict:
        return self._launch(issue_id, prompt, runtime=runtime, worker_role=worker_role,
                            workflow=workflow, max_runtime_seconds=max_runtime_seconds,
                            create_worktree=False)

    def submit(self, run_id: str, result: dict) -> dict:
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


def default_launcher(registry_path: Path) -> WorkLauncher:
    store = SqliteClaimStore(registry_path.with_suffix(".claims.sqlite3"))
    return WorkLauncher(Dispatcher(RunRegistry(registry_path)), LauncherGitHub(), claim_store=store)
