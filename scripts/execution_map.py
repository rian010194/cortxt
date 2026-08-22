#!/usr/bin/env python3
"""Read-only execution map and durable conditional claims (ADR-039)."""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

WORKFLOW_PREFIX = "workflow:"
ACTIVE_STATES = ("active", "expired_pending_reconciliation")
FATAL_DRIFT = {"self_edge", "prerequisite_cycle", "missing_target", "cross_repo_target"}
RELATION = re.compile(r"^(Part of|Blocked by|Depends on):\s+([^\s]+)\s*$", re.MULTILINE)
ISSUE_ID = re.compile(r"^([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)#([1-9][0-9]*)$")
RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


class ExecutionMapError(RuntimeError):
    pass


class ClaimConflict(ExecutionMapError):
    pass


class GenerationConflict(ClaimConflict):
    pass


@dataclass(frozen=True)
class Issue:
    issue_id: str
    body: str = ""
    state: str = "open"
    labels: tuple[str, ...] = ()
    area: str | None = None
    milestone: str | None = None
    native_parent: str | None = None
    native_prerequisites: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "Issue":
        return cls(
            issue_id=canonical_issue_id(str(value["issue_id"])), body=str(value.get("body", "")),
            state=str(value.get("state", "open")).lower(),
            labels=tuple(sorted(_label_name(x) for x in value.get("labels", ()))),
            area=value.get("area"), milestone=value.get("milestone"),
            native_parent=value.get("native_parent"),
            native_prerequisites=tuple(value.get("native_prerequisites", ())),
        )


@dataclass(frozen=True, order=True)
class Edge:
    kind: str
    source: str
    target: str
    evidence: tuple[str, ...] = ()


@dataclass(frozen=True)
class Drift:
    code: str
    issue_id: str
    edge_kind: str = ""
    target: str = ""
    witness: tuple[str, ...] = ()

    def sort_key(self) -> tuple[Any, ...]:
        return (self.code, issue_sort_key(self.issue_id), self.edge_kind,
                issue_sort_key(self.target) if _is_issue_id(self.target) else self.target, self.witness)


@dataclass(frozen=True)
class Graph:
    issues: tuple[Issue, ...]
    containment: tuple[Edge, ...]
    prerequisites: tuple[Edge, ...]
    drift: tuple[Drift, ...]
    non_launchable: tuple[str, ...]


def _label_name(value: Any) -> str:
    return str(value.get("name", "")) if isinstance(value, Mapping) else str(value)


def _is_issue_id(value: str) -> bool:
    return bool(ISSUE_ID.fullmatch(value or ""))


def canonical_issue_id(value: str, default_repo: str | None = None) -> str:
    value = value.strip()
    if value.startswith("#") and default_repo:
        value = default_repo + value
    match = ISSUE_ID.fullmatch(value)
    if not match:
        raise ValueError(f"malformed canonical issue id: {value}")
    return f"{match.group(1).lower()}/{match.group(2).lower()}#{int(match.group(3))}"


def issue_sort_key(value: str) -> tuple[str, str, int]:
    match = ISSUE_ID.fullmatch(value)
    return (match.group(1).lower(), match.group(2).lower(), int(match.group(3))) if match else (value, "", 0)


def _target(raw: str, repo: str) -> tuple[str | None, str | None]:
    try:
        result = canonical_issue_id(raw, repo)
    except ValueError:
        return None, "missing_target"
    if result.rsplit("#", 1)[0] != repo:
        return result, "cross_repo_target"
    return result, None


def _cycle_witness(nodes: Iterable[str], edges: Iterable[tuple[str, str]]) -> tuple[str, ...] | None:
    adjacency = {node: [] for node in nodes}
    for source, target in edges:
        if source in adjacency and target in adjacency:
            adjacency[source].append(target)
    for values in adjacency.values():
        values.sort(key=issue_sort_key)
    found: list[tuple[str, ...]] = []
    def visit(start: str, node: str, path: list[str], seen: set[str]) -> None:
        for nxt in adjacency[node]:
            if nxt == start:
                found.append(tuple(path + [start]))
            elif nxt not in seen:
                visit(start, nxt, path + [nxt], seen | {nxt})
    for start in sorted(adjacency, key=issue_sort_key):
        visit(start, start, [start], {start})
    if not found:
        return None
    cycle = min(found, key=lambda x: (len(x), tuple(issue_sort_key(v) for v in x)))
    core = cycle[:-1]
    low = min(range(len(core)), key=lambda i: issue_sort_key(core[i]))
    rotated = core[low:] + core[:low]
    return tuple(rotated + (rotated[0],))


def derive_graph(issue_values: Sequence[Issue | Mapping[str, Any]]) -> Graph:
    issues = tuple(sorted((x if isinstance(x, Issue) else Issue.from_dict(x) for x in issue_values),
                          key=lambda x: issue_sort_key(x.issue_id)))
    by_id = {x.issue_id: x for x in issues}
    drifts: list[Drift] = []
    candidates: dict[tuple[str, str, str], set[str]] = {}
    for issue in issues:
        repo = issue.issue_id.rsplit("#", 1)[0]
        workflow = [x for x in issue.labels if x.startswith(WORKFLOW_PREFIX)]
        if issue.state == "open" and len(workflow) != 1:
            drifts.append(Drift("workflow_label_cardinality", issue.issue_id))
        if not issue.area or not issue.milestone:
            drifts.append(Drift("missing_area_or_milestone", issue.issue_id))
        text_parents: list[str] = []
        for phrase, raw in RELATION.findall(issue.body):
            target, error = _target(raw, repo)
            kind = "containment" if phrase == "Part of" else "prerequisite"
            if error:
                drifts.append(Drift(error, issue.issue_id, kind, target or raw))
                continue
            assert target
            if kind == "containment":
                text_parents.append(target)
                key = (kind, issue.issue_id, target)  # child -> parent
            else:
                key = (kind, target, issue.issue_id)  # prerequisite -> blocked
            if "text" in candidates.setdefault(key, set()):
                drifts.append(Drift("duplicate_edge", issue.issue_id, kind, target))
            candidates[key].add("text")
        if len(set(text_parents)) > 1:
            drifts.append(Drift("multiple_parents", issue.issue_id, "containment",
                                ",".join(sorted(set(text_parents), key=issue_sort_key))))
        native_parent = None
        if issue.native_parent:
            native_parent, error = _target(issue.native_parent, repo)
            if error:
                drifts.append(Drift(error, issue.issue_id, "containment", native_parent or issue.native_parent))
            else:
                candidates.setdefault(("containment", issue.issue_id, native_parent), set()).add("native")
        if native_parent and text_parents and set(text_parents) != {native_parent}:
            drifts.append(Drift("native_text_parent_mismatch", issue.issue_id, "containment",
                                ",".join(sorted(set(text_parents) | {native_parent}, key=issue_sort_key))))
        for raw in issue.native_prerequisites:
            target, error = _target(raw, repo)
            if error:
                drifts.append(Drift(error, issue.issue_id, "prerequisite", target or raw))
            else:
                evidence = candidates.setdefault(("prerequisite", target, issue.issue_id), set())
                if "native" in evidence:
                    drifts.append(Drift("duplicate_edge", issue.issue_id, "prerequisite", target))
                evidence.add("native")
    edges: dict[str, list[Edge]] = {"containment": [], "prerequisite": []}
    for (kind, source, target), evidence in sorted(candidates.items()):
        owner = source if kind == "containment" else target
        relation_target = target if kind == "containment" else source
        if source == target:
            drifts.append(Drift("self_edge", owner, kind, relation_target))
            continue
        if relation_target not in by_id:
            drifts.append(Drift("missing_target", owner, kind, relation_target))
            continue
        edges[kind].append(Edge(kind, source, target, tuple(sorted(evidence))))
    for kind, code in (("containment", "containment_cycle"), ("prerequisite", "prerequisite_cycle")):
        witness = _cycle_witness(by_id, ((x.source, x.target) for x in edges[kind]))
        if witness:
            for node in sorted(set(witness[:-1]), key=issue_sort_key):
                drifts.append(Drift(code, node, kind, witness[1] if len(witness) > 1 else node, witness))
    fatal = {d.issue_id for d in drifts if d.code in FATAL_DRIFT}
    prereq_adj: dict[str, list[str]] = {x: [] for x in by_id}
    for edge in edges["prerequisite"]:
        prereq_adj[edge.source].append(edge.target)
    queue = list(fatal)
    while queue:
        for affected in prereq_adj.get(queue.pop(), ()):
            if affected not in fatal:
                fatal.add(affected); queue.append(affected)
    unique = {(d.code, d.issue_id, d.edge_kind, d.target, d.witness): d for d in drifts}
    return Graph(issues, tuple(sorted(edges["containment"])), tuple(sorted(edges["prerequisite"])),
                 tuple(sorted(unique.values(), key=Drift.sort_key)),
                 tuple(sorted(fatal, key=issue_sort_key)))


def blocker_satisfied(issue: Issue) -> bool:
    return issue.state == "closed" or "workflow:done" in issue.labels


def topological_waves(graph: Graph) -> tuple[tuple[str, ...], ...]:
    """Kahn waves over unfinished prerequisite edges; containment is ignored."""
    ids = {x.issue_id for x in graph.issues}
    by_id = {x.issue_id: x for x in graph.issues}
    incoming = {x: 0 for x in ids}
    outgoing = {x: [] for x in ids}
    for edge in graph.prerequisites:
        if blocker_satisfied(by_id[edge.source]):
            continue
        incoming[edge.target] += 1
        outgoing[edge.source].append(edge.target)
    remaining = set(ids) - set(graph.non_launchable)
    waves: list[tuple[str, ...]] = []
    while remaining:
        wave = tuple(sorted((x for x in remaining if incoming[x] == 0), key=issue_sort_key))
        if not wave:
            break
        waves.append(wave)
        remaining.difference_update(wave)
        for source in wave:
            for target in outgoing[source]:
                incoming[target] -= 1
    return tuple(waves)


def normalize_worktree(path: str | Path) -> str:
    return os.path.normcase(os.path.abspath(os.path.normpath(str(path)))).replace("\\", "/")


def collision_keys(*, issue_id: str, run_id: str, worktree: str | Path,
                   workflow_label: str, store_session_id: str | None = None,
                   engine_session_id: str | None = None) -> tuple[str, ...]:
    issue_id = canonical_issue_id(issue_id)
    if not RUN_ID.fullmatch(run_id):
        raise ValueError("malformed run id")
    if not workflow_label.startswith(WORKFLOW_PREFIX):
        raise ValueError("malformed workflow label")
    values = [f"issue:{issue_id}", f"run:{run_id}", f"branch:work/{run_id}",
              f"worktree:{normalize_worktree(worktree)}", f"workflow_label:{issue_id}",
              f"label_state:{issue_id}:{workflow_label}"]
    if store_session_id is not None:
        values.append(f"store_session:{store_session_id}")
    if engine_session_id is not None:
        values.append(f"engine_session:{engine_session_id}")
    return tuple(sorted(values))


CLAIM_FIELDS = ("claim_version", "claim_id", "issue_id", "workflow", "run_id", "branch_ref",
                "worktree_path", "store_session_id", "engine_id", "engine_session_id", "driver_id",
                "state", "acquired_at", "heartbeat_at", "lease_expires_at", "released_at",
                "release_reason", "expected_workflow_label", "claim_generation")


@dataclass(frozen=True)
class ClaimRecord:
    claim_version: int
    claim_id: str
    issue_id: str
    workflow: str
    run_id: str
    branch_ref: str
    worktree_path: str
    store_session_id: str | None
    engine_id: str
    engine_session_id: str | None
    driver_id: str
    state: str
    acquired_at: float
    heartbeat_at: float
    lease_expires_at: float
    released_at: float | None
    release_reason: str | None
    expected_workflow_label: str
    claim_generation: int


class ClaimStore(ABC):
    @abstractmethod
    def generation(self) -> int: ...
    @abstractmethod
    def active_claims(self, now: float | None = None) -> tuple[ClaimRecord, ...]: ...
    @abstractmethod
    def acquire(self, claim: ClaimRecord, resources: Sequence[str], expected_generation: int) -> ClaimRecord: ...
    @abstractmethod
    def heartbeat(self, claim_id: str, run_id: str, driver_id: str, generation: int,
                  lease_expires_at: float, now: float | None = None) -> ClaimRecord: ...
    @abstractmethod
    def release(self, claim_id: str, run_id: str, driver_id: str, generation: int,
                reason: str, now: float | None = None) -> ClaimRecord: ...
    @abstractmethod
    def expire_leases(self, now: float | None = None) -> tuple[ClaimRecord, ...]: ...


class SqliteClaimStore(ClaimStore):
    """SQLite WAL store; every conditional write uses BEGIN IMMEDIATE."""
    def __init__(self, path: str | Path, timeout: float = 5.0):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(self.path), timeout=timeout, isolation_level=None,
                                  check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value INTEGER NOT NULL);
        INSERT OR IGNORE INTO meta VALUES ('generation', 0);
        CREATE TABLE IF NOT EXISTS claims (
          claim_version INTEGER NOT NULL, claim_id TEXT PRIMARY KEY, issue_id TEXT NOT NULL,
          workflow TEXT NOT NULL, run_id TEXT NOT NULL, branch_ref TEXT NOT NULL,
          worktree_path TEXT NOT NULL, store_session_id TEXT, engine_id TEXT NOT NULL,
          engine_session_id TEXT, driver_id TEXT NOT NULL, state TEXT NOT NULL,
          acquired_at REAL NOT NULL, heartbeat_at REAL NOT NULL, lease_expires_at REAL NOT NULL,
          released_at REAL, release_reason TEXT, expected_workflow_label TEXT NOT NULL,
          claim_generation INTEGER NOT NULL);
        CREATE UNIQUE INDEX IF NOT EXISTS one_active_issue ON claims(issue_id)
          WHERE state IN ('active','expired_pending_reconciliation');
        CREATE UNIQUE INDEX IF NOT EXISTS one_active_run ON claims(run_id)
          WHERE state IN ('active','expired_pending_reconciliation');
        CREATE TABLE IF NOT EXISTS resources (
          resource_key TEXT PRIMARY KEY, claim_id TEXT NOT NULL REFERENCES claims(claim_id));
        CREATE TABLE IF NOT EXISTS history (
          sequence INTEGER PRIMARY KEY AUTOINCREMENT, claim_id TEXT NOT NULL,
          generation INTEGER NOT NULL, event TEXT NOT NULL, at REAL NOT NULL, detail TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS receipts (receipt_id TEXT PRIMARY KEY, used_at REAL);
        """)

    def close(self) -> None:
        self.db.close()

    def generation(self) -> int:
        return int(self.db.execute("SELECT value FROM meta WHERE key='generation'").fetchone()[0])

    def _expire_locked(self, now: float) -> None:
        rows = self.db.execute("SELECT claim_id FROM claims WHERE state='active' AND lease_expires_at<=?", (now,)).fetchall()
        for row in rows:
            self.db.execute("UPDATE claims SET state='expired_pending_reconciliation' WHERE claim_id=?", (row[0],))
            generation = self._bump()
            self.db.execute("INSERT INTO history(claim_id,generation,event,at,detail) VALUES(?,?,?,?,?)",
                            (row[0], generation, "lease_expired", now, "{}"))

    def _bump(self) -> int:
        self.db.execute("UPDATE meta SET value=value+1 WHERE key='generation'")
        return self.generation()

    def active_claims(self, now: float | None = None) -> tuple[ClaimRecord, ...]:
        rows = self.db.execute("SELECT * FROM claims WHERE state IN (?,?) ORDER BY issue_id,claim_id", ACTIVE_STATES)
        return tuple(ClaimRecord(**dict(x)) for x in rows)

    def expire_leases(self, now: float | None = None) -> tuple[ClaimRecord, ...]:
        """Explicit reconciliation entry; expiry never frees resource rows."""
        now = time.time() if now is None else now
        self.db.execute("BEGIN IMMEDIATE")
        try:
            self._expire_locked(now); self.db.commit()
        except Exception:
            self.db.rollback(); raise
        return self.active_claims()

    def acquire(self, claim: ClaimRecord, resources: Sequence[str], expected_generation: int) -> ClaimRecord:
        if claim.state != "active" or len(set(resources)) != len(resources) or not resources:
            raise ValueError("claim must be active with unique resources")
        self.db.execute("BEGIN IMMEDIATE")
        try:
            self._expire_locked(claim.acquired_at)
            if self.generation() != expected_generation:
                raise GenerationConflict("claim generation changed")
            generation = self._bump()
            value = asdict(claim); value["claim_generation"] = generation
            columns = ",".join(CLAIM_FIELDS); marks = ",".join("?" for _ in CLAIM_FIELDS)
            self.db.execute(f"INSERT INTO claims({columns}) VALUES({marks})", tuple(value[x] for x in CLAIM_FIELDS))
            self.db.executemany("INSERT INTO resources(resource_key,claim_id) VALUES(?,?)",
                                ((x, claim.claim_id) for x in sorted(resources)))
            self.db.execute("INSERT INTO history(claim_id,generation,event,at,detail) VALUES(?,?,?,?,?)",
                            (claim.claim_id, generation, "acquired", claim.acquired_at,
                             json.dumps({"resources": sorted(resources)}, separators=(",", ":"))))
            self.db.commit()
            return ClaimRecord(**value)
        except sqlite3.IntegrityError as error:
            self.db.rollback(); raise ClaimConflict("exclusive resource already claimed") from error
        except Exception:
            self.db.rollback(); raise

    def _transition(self, claim_id: str, run_id: str, driver_id: str, generation: int,
                    event: str, now: float, updates: Mapping[str, Any]) -> ClaimRecord:
        self.db.execute("BEGIN IMMEDIATE")
        try:
            row = self.db.execute("SELECT * FROM claims WHERE claim_id=?", (claim_id,)).fetchone()
            if not row or row["run_id"] != run_id or row["driver_id"] != driver_id or row["claim_generation"] != generation:
                raise ClaimConflict("claim ownership or generation mismatch")
            if row["state"] != "active":
                raise ClaimConflict("claim is not active")
            new_generation = self._bump()
            values = dict(updates); values["claim_generation"] = new_generation
            sets = ",".join(f"{x}=?" for x in values)
            self.db.execute(f"UPDATE claims SET {sets} WHERE claim_id=?", (*values.values(), claim_id))
            if event == "released":
                self.db.execute("DELETE FROM resources WHERE claim_id=?", (claim_id,))
            self.db.execute("INSERT INTO history(claim_id,generation,event,at,detail) VALUES(?,?,?,?,?)",
                            (claim_id, new_generation, event, now, json.dumps(dict(updates), sort_keys=True)))
            self.db.commit()
            return ClaimRecord(**dict(self.db.execute("SELECT * FROM claims WHERE claim_id=?", (claim_id,)).fetchone()))
        except Exception:
            self.db.rollback(); raise

    def heartbeat(self, claim_id: str, run_id: str, driver_id: str, generation: int,
                  lease_expires_at: float, now: float | None = None) -> ClaimRecord:
        now = time.time() if now is None else now
        if lease_expires_at <= now:
            raise ValueError("heartbeat must extend lease")
        return self._transition(claim_id, run_id, driver_id, generation, "heartbeat", now,
                                {"heartbeat_at": now, "lease_expires_at": lease_expires_at})

    def release(self, claim_id: str, run_id: str, driver_id: str, generation: int,
                reason: str, now: float | None = None) -> ClaimRecord:
        if not reason.strip():
            raise ValueError("release reason is required")
        now = time.time() if now is None else now
        return self._transition(claim_id, run_id, driver_id, generation, "released", now,
                                {"state": "released", "released_at": now, "release_reason": reason})

    def bind_engine_session(self, claim_id: str, run_id: str, driver_id: str, generation: int,
                            engine_session_id: str, now: float | None = None) -> ClaimRecord:
        if not engine_session_id:
            raise ValueError("engine session id is required")
        now = time.time() if now is None else now
        row = self.db.execute("SELECT engine_session_id FROM claims WHERE claim_id=?", (claim_id,)).fetchone()
        if not row or row[0] is not None:
            raise ClaimConflict("engine session is already bound or claim is missing")
        return self._transition(claim_id, run_id, driver_id, generation, "engine_session_bound", now,
                                {"engine_session_id": engine_session_id})

    def history(self, claim_id: str) -> tuple[dict[str, Any], ...]:
        return tuple(dict(x) for x in self.db.execute(
            "SELECT * FROM history WHERE claim_id=? ORDER BY sequence", (claim_id,)))

    def consume_receipt(self, receipt_id: str) -> bool:
        self.db.execute("BEGIN IMMEDIATE")
        try:
            self.db.execute("INSERT INTO receipts(receipt_id,used_at) VALUES(?,?)", (receipt_id, time.time()))
            self.db.commit(); return True
        except sqlite3.IntegrityError:
            self.db.rollback(); return False


@dataclass(frozen=True)
class ValidationReceipt:
    receipt_id: str
    snapshot_fingerprint: str
    claim_id: str
    claim_generation: int
    resources: tuple[str, ...]
    run_id: str
    expires_at: float
    decision: str


@dataclass(frozen=True)
class PreflightResult:
    decision: str
    collision_codes: tuple[str, ...]
    receipt: ValidationReceipt | None = None


def fingerprint(snapshot: Mapping[str, Any]) -> str:
    payload = json.dumps(snapshot, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _inventory_keys(records: Iterable[Any], source: str) -> tuple[set[str], list[str]]:
    keys: set[str] = set(); errors: list[str] = []
    for value in records:
        if not isinstance(value, Mapping):
            errors.append(f"malformed_{source}"); continue
        owner = value.get("owner") or value.get("driver_id")
        if not owner:
            errors.append("missing_owner")
        raw_keys = value.get("resources")
        if raw_keys is None:
            raw_keys = []
            for name, prefix in (("issue_id", "issue"), ("run_id", "run"), ("branch", "branch"),
                                 ("worktree", "worktree"), ("store_session_id", "store_session"),
                                 ("engine_session_id", "engine_session")):
                if value.get(name):
                    item = normalize_worktree(value[name]) if name == "worktree" else value[name]
                    raw_keys.append(f"{prefix}:{item}")
        if not isinstance(raw_keys, (list, tuple)) or any(not isinstance(x, str) for x in raw_keys):
            errors.append(f"malformed_{source}"); continue
        if value.get("stale") or value.get("state") == "expired_pending_reconciliation":
            errors.append("stale_unreconciled")
        keys.update(raw_keys)
    return keys, errors


def preflight_validate(*, issue: Issue, graph: Graph, run_id: str, worktree: str | Path,
                       store_session_id: str | None, engine_id: str,
                       engine_session_id: str | None, driver_id: str, workflow: str,
                       store: ClaimStore, inventories: Mapping[str, Sequence[Any]],
                       writers: Sequence[Mapping[str, Any]] = (), now: float | None = None,
                       ttl_seconds: float = 30.0, acquire: bool = True) -> PreflightResult:
    """Validate injected state. Only the optional final store acquire mutates."""
    now = time.time() if now is None else now
    codes: list[str] = []
    workflow_labels = [x for x in issue.labels if x.startswith(WORKFLOW_PREFIX)]
    if issue.state != "open" or workflow_labels != ["workflow:ready"] or "atlas:map" in issue.labels:
        codes.append("issue_not_ready")
    if issue.issue_id in graph.non_launchable:
        codes.append("fatal_relation_drift")
    by_id = {x.issue_id: x for x in graph.issues}
    if any(edge.target == issue.issue_id and not blocker_satisfied(by_id[edge.source]) for edge in graph.prerequisites):
        codes.append("unsatisfied_prerequisite")
    try:
        resources = collision_keys(issue_id=issue.issue_id, run_id=run_id, worktree=worktree,
                                   workflow_label="workflow:ready", store_session_id=store_session_id,
                                   engine_session_id=engine_session_id)
    except ValueError:
        return PreflightResult("reject", ("malformed_request",))
    occupied: set[str] = set()
    for source, records in sorted(inventories.items()):
        found, errors = _inventory_keys(records, source)
        occupied.update(found); codes.extend(errors)
    try:
        active = store.active_claims(now)
        generation = store.generation()
    except Exception:
        return PreflightResult("reject", ("store_unavailable",))
    for claim in active:
        occupied.update(collision_keys(issue_id=claim.issue_id, run_id=claim.run_id,
                                       worktree=claim.worktree_path,
                                       workflow_label=claim.expected_workflow_label,
                                       store_session_id=claim.store_session_id,
                                       engine_session_id=claim.engine_session_id))
    if occupied.intersection(resources):
        codes.append("resource_collision")
    domains: dict[str, set[str]] = {}
    for writer in writers:
        domain, owner = writer.get("domain"), writer.get("owner")
        if not domain or not owner:
            codes.append("missing_owner")
        else:
            domains.setdefault(str(domain), set()).add(str(owner))
    if any(len(owners | {driver_id}) > 1 for owners in domains.values()):
        codes.append("shared_store_writer_conflict")
    snapshot = {"issue": asdict(issue), "graph_drift": [asdict(x) for x in graph.drift],
                "inventories": inventories, "writers": writers, "generation": generation}
    if codes or not acquire:
        return PreflightResult("reject" if codes else "validated_read_only", tuple(sorted(set(codes))))
    claim_id = uuid.uuid4().hex
    claim = ClaimRecord(1, claim_id, issue.issue_id, workflow, run_id, f"work/{run_id}",
                        normalize_worktree(worktree), store_session_id, engine_id,
                        engine_session_id, driver_id, "active", now, now, now + ttl_seconds,
                        None, None, "workflow:ready", 0)
    try:
        claim = store.acquire(claim, resources, generation)
    except ClaimConflict:
        return PreflightResult("reject", ("resource_collision",))
    except Exception:
        return PreflightResult("reject", ("store_unavailable",))
    receipt_seed = f"{claim_id}:{run_id}:{claim.claim_generation}:{now}"
    receipt = ValidationReceipt(hashlib.sha256(receipt_seed.encode()).hexdigest(), fingerprint(snapshot),
                                claim_id, claim.claim_generation, resources, run_id,
                                now + min(ttl_seconds, 30.0), "allow")
    return PreflightResult("allow", (), receipt)


def validate_receipt(receipt: ValidationReceipt, *, snapshot: Mapping[str, Any],
                     claim: ClaimRecord, resources: Sequence[str], run_id: str,
                     store: SqliteClaimStore, now: float | None = None) -> bool:
    now = time.time() if now is None else now
    valid = (receipt.decision == "allow" and now < receipt.expires_at and receipt.run_id == run_id
             and receipt.claim_id == claim.claim_id and receipt.claim_generation == claim.claim_generation
             and tuple(sorted(resources)) == receipt.resources
             and fingerprint(snapshot) == receipt.snapshot_fingerprint)
    return bool(valid and store.consume_receipt(receipt.receipt_id))


def read_projection(graph: Graph, claims: Sequence[ClaimRecord] = (),
                    collision_codes: Sequence[str] = (), role: str = "observer") -> dict[str, Any]:
    waves = topological_waves(graph)
    wave_by_id = {issue_id: number for number, wave in enumerate(waves) for issue_id in wave}
    blockers = {x.issue_id: [] for x in graph.issues}
    by_id = {x.issue_id: x for x in graph.issues}
    for edge in graph.prerequisites:
        if not blocker_satisfied(by_id[edge.source]): blockers[edge.target].append(edge.source)
    return {"role": role, "issues": [{"id": x.issue_id, "wave": wave_by_id.get(x.issue_id),
             "blockers": sorted(blockers[x.issue_id], key=issue_sort_key),
             "drift_codes": sorted({d.code for d in graph.drift if d.issue_id == x.issue_id}),
             "launchable": x.issue_id not in graph.non_launchable} for x in graph.issues],
            "waves": [list(x) for x in waves],
            "claims": [{"claim_id": x.claim_id, "issue_id": x.issue_id, "run_id": x.run_id,
                        "state": x.state, "lease_expires_at": x.lease_expires_at,
                        "driver_id": x.driver_id} for x in sorted(claims, key=lambda c: (issue_sort_key(c.issue_id), c.claim_id))],
            "collision_codes": sorted(set(collision_codes))}


def plan_from_json(value: Mapping[str, Any]) -> dict[str, Any]:
    graph = derive_graph(value.get("issues", ()))
    claims = tuple(ClaimRecord(**x) for x in value.get("claims", ()))
    return read_projection(graph, claims, value.get("collision_codes", ()), value.get("role", "observer"))
