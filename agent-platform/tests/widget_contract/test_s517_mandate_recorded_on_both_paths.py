"""S7 (#517): both launcher paths record the same approved mandate.

`WorkLauncher._launch` took a shortened branch when `self.claim_store is None`
that never reached the `limit_fields` block, so a mutating Run reached the
worker carrying an approved mandate that was never written to its durable
record. The Evidence Gate then refused it for `request_id_not_recorded` --
correct and fail-closed, but naming the wrong cause: not "this Run was never
approved" but "this launcher path forgot to write the approval it was given".

Production was never affected (`default_launcher` always builds a
`SqliteClaimStore`). The cost was elsewhere, and is what these tests pin:

- the approved ceilings were silently dropped, and `max_cost_usd` is enforced
  in `submit()` by reading it off the Run record -- so that Run had no ceiling
  to enforce;
- the cheap test path diverged from production, which is how this was found:
  a negative-arm test refused for `request_id_not_recorded` instead of the
  `commit_predates_run` the arm exists to prove.
"""
import sys
import time
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[3] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from dispatcher import Dispatcher, RunRegistry  # noqa: E402
from execution_map import SqliteClaimStore  # noqa: E402
from work_launcher import ExecutionGateError, WorkLauncher  # noqa: E402

MANDATE = {
    "max_cost_usd": 2.0,
    "max_parallel_workers": 1,
    "delegation_depth": 0,
    "artifact_policy": "Only docs/agents/work-launcher.md inside the run's isolated worktree.",
    "request_id": "sha256:" + "a" * 64,
}
MANDATE_FIELDS = tuple(MANDATE)


class _NoopGitHub:
    """Duck-typed GitHubOps so the real Dispatcher needs no network."""

    def __init__(self):
        self.labels = {"owner/repo#517": ["workflow:ready"]}
        self.comments = []

    def get_labels(self, repo, num):
        return self.labels.get(f"{repo}#{num}", [])

    def swap_label(self, repo, num, remove, add):
        cur = self.labels.setdefault(f"{repo}#{num}", [])
        if remove in cur:
            cur.remove(remove)
        cur.append(add)

    def comment(self, repo, num, body):
        self.comments.append((f"{repo}#{num}", body))


def _issue_reader(issue_id):
    """The execution-map gate reads the Issue; the claim-store branch needs it."""
    return {"issue_id": issue_id, "number": 517, "state": "open",
            "title": "Mandate recording", "labels": ["workflow:ready", "background-task"]}


def _launcher(tmp_path, *, with_claim_store):
    tmp_path.mkdir(parents=True, exist_ok=True)
    registry = RunRegistry(tmp_path / "runs.json")
    dispatcher = Dispatcher(registry=registry, gh=_NoopGitHub())
    claim_store = SqliteClaimStore(tmp_path / "claims.db") if with_claim_store else None
    launcher = WorkLauncher(dispatcher, _NoopGitHub(), claim_store=claim_store,
                            worktree_root=tmp_path / "worktrees",
                            issue_reader=_issue_reader, repo_path=tmp_path)
    return launcher, registry


def _recorded(registry, run_id):
    run = registry.get(run_id)
    return {name: getattr(run, name, None) for name in MANDATE_FIELDS}


@pytest.fixture(autouse=True)
def _free_route(monkeypatch):
    monkeypatch.setenv("CORTXT_FREE_MODEL", "upstage/solar-pro4:free")
    monkeypatch.setenv("CORTXT_FREE_PROVIDER", "nous")


@pytest.fixture(autouse=True)
def _no_real_worker(monkeypatch):
    """Never start a worker: this is about what the record carries at dispatch."""
    monkeypatch.setattr(WorkLauncher, "_dispatch", lambda self, run, prompt, worktree: None)


@pytest.fixture(autouse=True)
def _no_real_worktree(monkeypatch, tmp_path):
    """A real `git worktree add` is not what these tests are about."""
    def _create(self, run_id, worktree):
        Path(worktree).mkdir(parents=True, exist_ok=True)
        return "b" * 40
    monkeypatch.setattr(WorkLauncher, "_create_worktree", _create)


@pytest.mark.parametrize("with_claim_store", [True, False],
                         ids=["claim-store", "no-claim-store"])
def test_mutating_run_records_the_mandate_on_both_paths(tmp_path, with_claim_store):
    launcher, registry = _launcher(tmp_path, with_claim_store=with_claim_store)

    result = launcher._launch(
        "owner/repo#517", "do the task", runtime="hermes-free", worker_role="builder",
        workflow="work-launcher/v1", max_runtime_seconds=900, create_worktree=True,
        mutating=True, artifact_paths=["docs/agents/work-launcher.md"], **MANDATE)

    assert _recorded(registry, result["run_id"]) == MANDATE


def test_both_paths_record_an_identical_mandate(tmp_path):
    """#517's acceptance criterion, stated as one assertion.

    The two branches must not merely each record something -- they must record
    the same thing, because they are launching the same approval.
    """
    with_store, reg_a = _launcher(tmp_path / "a", with_claim_store=True)
    without_store, reg_b = _launcher(tmp_path / "b", with_claim_store=False)

    kwargs = dict(runtime="hermes-free", worker_role="builder",
                  workflow="work-launcher/v1", max_runtime_seconds=900,
                  create_worktree=True, mutating=True,
                  artifact_paths=["docs/agents/work-launcher.md"], **MANDATE)
    a = with_store._launch("owner/repo#517", "do the task", **kwargs)
    b = without_store._launch("owner/repo#517", "do the task", **kwargs)

    assert _recorded(reg_a, a["run_id"]) == _recorded(reg_b, b["run_id"])


@pytest.mark.parametrize("with_claim_store", [True, False],
                         ids=["claim-store", "no-claim-store"])
def test_request_id_is_recorded_so_the_gate_can_correlate(tmp_path, with_claim_store):
    """The specific field whose absence produced `request_id_not_recorded`."""
    launcher, registry = _launcher(tmp_path, with_claim_store=with_claim_store)

    result = launcher._launch(
        "owner/repo#517", "do the task", runtime="hermes-free", worker_role="builder",
        workflow="work-launcher/v1", max_runtime_seconds=900, create_worktree=True,
        mutating=True, **MANDATE)

    assert registry.get(result["run_id"]).request_id == MANDATE["request_id"]


@pytest.mark.parametrize("with_claim_store", [True, False],
                         ids=["claim-store", "no-claim-store"])
def test_unrecordable_mandate_fails_the_launch_closed(tmp_path, with_claim_store,
                                                      monkeypatch):
    """Refused before the worker starts, not by the gate after it has run.

    A mutating Run whose approved limits were not made durable is not an
    approved Run -- the same stance `artifact_paths`, `base_commit` and
    `worktree` already take.
    """
    launcher, registry = _launcher(tmp_path, with_claim_store=with_claim_store)
    dispatched = []
    monkeypatch.setattr(WorkLauncher, "_dispatch",
                        lambda self, run, prompt, worktree: dispatched.append(run))

    original = registry.update

    def _refuse(run_id, **fields):
        if "request_id" in fields:
            raise RuntimeError("registry cannot carry the mandate")
        return original(run_id, **fields)
    monkeypatch.setattr(registry, "update", _refuse)

    with pytest.raises(ExecutionGateError) as raised:
        launcher._launch(
            "owner/repo#517", "do the task", runtime="hermes-free", worker_role="builder",
            workflow="work-launcher/v1", max_runtime_seconds=900, create_worktree=True,
            mutating=True, **MANDATE)

    assert "mandate_not_recordable" in str(raised.value)
    assert dispatched == [], "the worker must never start on an unrecorded mandate"


@pytest.mark.parametrize("with_claim_store", [True, False],
                         ids=["claim-store", "no-claim-store"])
def test_non_mutating_run_is_not_refused_by_an_unrecordable_mandate(tmp_path,
                                                                    with_claim_store,
                                                                    monkeypatch):
    """A read-only run has nothing to correlate and keeps the tolerant path."""
    launcher, registry = _launcher(tmp_path, with_claim_store=with_claim_store)
    original = registry.update

    def _refuse(run_id, **fields):
        if "request_id" in fields:
            raise RuntimeError("registry cannot carry the mandate")
        return original(run_id, **fields)
    monkeypatch.setattr(registry, "update", _refuse)

    result = launcher._launch(
        "owner/repo#517", "read a doc", runtime="hermes-free", worker_role="researcher",
        workflow="work-launcher/v1", max_runtime_seconds=900, create_worktree=False,
        mutating=False, **MANDATE)

    assert result["run_id"]
