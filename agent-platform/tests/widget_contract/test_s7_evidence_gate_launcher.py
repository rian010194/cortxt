"""S7 (#490, #493): review regressions for the launcher and the sync workflow.

Findings 5 to 8 of the independent review of PR #494. Findings 1 to 4 -- the
Evidence Gate itself -- live in `test_s7_evidence_gate_review.py`.

These four are all about the moments *around* the gate: what must be recorded
before a worker starts, what must never start at all, what must be cleaned up
when something raises, and whether the workflow that performs the review
transition can even run.
"""
import subprocess
import sys
import time
import inspect
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_DIR = REPO_ROOT / "scripts"
PLATFORM_DIR = REPO_ROOT / "agent-platform"
for _path in (SCRIPTS_DIR, PLATFORM_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import yaml  # noqa: E402

from dispatcher import Run  # noqa: E402
from work_launcher import (  # noqa: E402
    ExecutionGateError, WorkLauncher, parse_scope_file)
from cli.unified_cli import _run_work  # noqa: E402

POLICY = "Only `docs/agents/work-launcher.md` inside the run's isolated worktree."


def _run(**overrides) -> Run:
    fields = dict(
        run_id="run-1", issue_id="owner/repo#485", workflow="work-launcher/v1",
        worker_role="builder", runtime="hermes-free", claimed_at=1000.0,
        lease_seconds=600, status="in_progress", mutating=True,
        isolation="worktree", branch="work/run-1", artifact_policy=POLICY,
        request_id="sha256:abc",
    )
    fields.update(overrides)
    return Run(**fields)


class _Claim:
    def __init__(self, run_id):
        self.claim_id, self.run_id = "claim-" + run_id, run_id
        self.driver_id, self.claim_generation = "cortxt-work", 1
        self.store_session_id = self.engine_session_id = None


class _ClaimStore:
    """Minimal claim store that records what was released, and why."""

    def __init__(self):
        self.claims = {}
        self.released = []

    def hold(self, run_id):
        self.claims[run_id] = _Claim(run_id)
        return self.claims[run_id]

    def active_claims(self, now):
        done = {run_id for run_id, _ in self.released}
        return [c for run_id, c in self.claims.items() if run_id not in done]

    def release(self, claim_id, run_id, driver_id, generation, reason, now=None):
        self.released.append((run_id, reason))


class _Registry:
    def __init__(self, run=None):
        self.runs = {run.run_id: run} if run else {}
        self.updates = []

    def get(self, run_id):
        return self.runs.get(run_id)

    def update(self, run_id, **fields):
        self.updates.append((run_id, fields))
        for key, value in fields.items():
            setattr(self.runs[run_id], key, value)
        return self.runs[run_id]


def _launcher(dispatcher, claim_store=None):
    app = WorkLauncher.__new__(WorkLauncher)
    app.dispatcher = dispatcher
    app.claim_store = claim_store
    app._claims_by_run = {}
    app.clock = time.time
    return app


def _dispatcherish(registry, complete=None):
    # `staticmethod`, so the injected callable keeps the dispatcher's own
    # signature instead of silently acquiring a `self`.
    namespace = {"registry": registry}
    if complete is not None:
        namespace["complete"] = staticmethod(complete)
    return type("Dispatcherish", (), namespace)()


# ==========================================================================
# Finding 5 -- the approved scope is persisted before dispatch.
# ==========================================================================

def test_the_approved_paths_are_persisted_on_the_run():
    """`create` always dispatches a mutating worker, so the gate must find a
    readable approved scope on the durable Run before the worker starts --
    never derived afterwards, and never from anything the worker returns."""
    registry = _Registry(_run(artifact_paths=None, artifact_policy=None))
    app = _launcher(_dispatcherish(registry))
    app._record_approved_scope("run-1", ["docs/agents/work-launcher.md", "LICENSE"])
    assert registry.updates == [
        ("run-1", {"artifact_paths": ["docs/agents/work-launcher.md", "LICENSE"]})]


def test_an_empty_approved_scope_is_refused():
    registry = _Registry(_run())
    app = _launcher(_dispatcherish(registry))
    with pytest.raises(ExecutionGateError) as exc:
        app._record_approved_scope("run-1", [])
    assert exc.value.code == "approved_artifact_paths_required"
    assert registry.updates == [], "nothing may be persisted for a refused scope"


@pytest.mark.parametrize("bad", [["../escape"], ["/etc/passwd"], ["C:/win.txt"]])
def test_a_scope_that_is_not_repository_relative_is_refused(bad):
    registry = _Registry(_run())
    app = _launcher(_dispatcherish(registry))
    with pytest.raises(ExecutionGateError) as exc:
        app._record_approved_scope("run-1", bad)
    assert exc.value.code == "artifact_path_not_repository_relative"
    assert registry.updates == []


def test_the_persisted_scope_is_normalized():
    """What is stored is what the gate compares, so it is normalized once here
    rather than differently at each comparison."""
    registry = _Registry(_run())
    app = _launcher(_dispatcherish(registry))
    app._record_approved_scope("run-1", ["./docs/agents/", "docs\\other/x.md"])
    assert registry.updates[0][1]["artifact_paths"] == ["docs/agents", "docs/other/x.md"]


def test_a_registry_that_cannot_carry_the_scope_fails_the_launch():
    """An unbounded mutating run is worse than a failed launch."""
    class NoUpdate:
        def get(self, run_id):
            return None

    app = _launcher(_dispatcherish(NoUpdate()))
    with pytest.raises(ExecutionGateError) as exc:
        app._record_approved_scope("run-1", ["LICENSE"])
    assert exc.value.code == "approved_scope_not_recordable"


def test_mutating_isolation_metadata_is_mandatory_before_dispatch(tmp_path):
    class BrokenRegistry(_Registry):
        def update(self, run_id, **fields):
            if "isolation" in fields:
                raise OSError("store unavailable")
            return super().update(run_id, **fields)

    app = _launcher(_dispatcherish(BrokenRegistry(_run())))
    with pytest.raises(ExecutionGateError) as exc:
        # A real worktree is supplied (#514) so the call reaches the store
        # write -- this test is about the write failing, not about a missing or
        # unresolvable directory.
        app.repo_path = tmp_path
        real = tmp_path / ".worktrees" / "run-1"
        real.mkdir(parents=True)
        app._record_isolation("run-1", True, required=True, base_commit="a" * 40,
                              worktree=real)
    assert exc.value.code == "isolation_not_recordable"


def test_a_mutating_run_without_a_recorded_base_fails_the_launch_closed():
    """#509: the Evidence Gate verifies everything the Run contributed on top
    of its base, so a mutating Run whose base could not be resolved would run
    under a gate that can only ever check its tip commit. Fail the launch
    instead, the way an unrecordable isolation already does."""
    app = _launcher(_dispatcherish(_Registry(_run())))
    with pytest.raises(ExecutionGateError) as exc:
        app._record_isolation("run-1", True, required=True, base_commit=None)
    assert exc.value.code == "base_commit_not_resolvable"


def test_a_non_mutating_run_still_launches_without_a_base():
    """Only a mutating Run is gated on a commit, so only a mutating Run needs
    a base to verify one against."""
    registry = _Registry(_run())
    app = _launcher(_dispatcherish(registry))
    app._record_isolation("run-1", True, required=False, base_commit=None)
    assert registry.updates[-1][1]["base_commit"] is None


def test_the_scope_file_carries_the_approved_paths(tmp_path):
    """`cortxt work new` reads the concrete scope from the issue text, so the
    operator states the paths and no parser stands between that approval and
    what the gate enforces."""
    scope = tmp_path / "scope.md"
    scope.write_text(
        "# Task\n\nDo the thing.\n\n## Acceptance criteria\n\n- It works.\n\n"
        "## Artifact policy\n\nOnly `docs/agents/work-launcher.md` and `LICENSE`.\n",
        encoding="utf-8")
    assert parse_scope_file(scope)["artifact_paths"] == [
        "docs/agents/work-launcher.md", "LICENSE"]


def test_a_scope_file_without_an_artifact_policy_yields_no_paths(tmp_path):
    """...and `create` then refuses, rather than launching unbounded."""
    scope = tmp_path / "scope.md"
    scope.write_text("# Task\n\nDo it.\n\n## Acceptance criteria\n\n- Works.\n",
                     encoding="utf-8")
    assert parse_scope_file(scope)["artifact_paths"] == []


def test_create_refuses_without_an_approved_scope():
    app = _launcher(_dispatcherish(_Registry()))
    with pytest.raises(ExecutionGateError) as exc:
        app.create("owner/repo", "T", "scope", ["AC"], runtime="hermes-free",
                   worker_role="builder", workflow="work-launcher/v1",
                   max_runtime_seconds=60, max_cost_usd=1.0, approved=True,
                   artifact_paths=[])
    assert exc.value.code == "approved_artifact_paths_required"


# ==========================================================================
# Finding 6 -- a mutating run is isolated, or it does not start.
# ==========================================================================

def test_a_mutating_resume_without_isolation_is_refused_before_any_claim():
    """The Evidence Gate would refuse this run's *result* -- but only after the
    worker had already run in the launcher's shared checkout, which is the
    #485/#489 breach itself. Refusing at launch is the only moment at which the
    shared checkout is still protected."""
    claims = []

    def claim(*args, **kwargs):
        claims.append(args)
        raise AssertionError("claim must not be reached")

    app = _launcher(_dispatcherish(_Registry()))
    app.dispatcher.claim = claim
    with pytest.raises(ExecutionGateError) as exc:
        app.resume("owner/repo#485", runtime="hermes-free", worker_role="builder",
                   workflow="work-launcher/v1", max_runtime_seconds=60,
                   prompt="do it", artifact_policy=POLICY, isolate=False,
                   mutating=True)
    assert exc.value.code == "mutating_run_requires_isolation"
    assert claims == [], "no claim may be created for a refused launch"


def test_launch_itself_refuses_the_unsafe_combination():
    """The guard is in `_launch` too, so no caller can route around `resume`."""
    app = _launcher(_dispatcherish(_Registry()))
    with pytest.raises(ExecutionGateError) as exc:
        app._launch("owner/repo#485", "prompt", runtime="hermes-free",
                    worker_role="builder", workflow="work-launcher/v1",
                    max_runtime_seconds=60, create_worktree=False, mutating=True)
    assert exc.value.code == "mutating_run_requires_isolation"


def test_isolation_is_what_decides_whether_a_resume_is_mutating():
    """A sanctioned shared-checkout mandate is not an evidence-bearing run; an
    isolated one is. Deriving this from `artifact_policy is not None` was wrong
    in both directions: it made a shared-checkout mandate mutating (which the
    guard above then refuses outright), and left an isolated run carrying no
    policy ungated."""
    import inspect

    source = inspect.getsource(WorkLauncher.resume)
    assert "mutating = isolate" in source


def test_cli_request_snapshot_always_enables_its_approved_worktree_isolation():
    """A request-file cannot be used to reopen the shared-checkout bypass."""
    source = inspect.getsource(_run_work)
    assert "effective_isolate = request is not None or" in source
    assert "isolate=effective_isolate" in source


# ==========================================================================
# Finding 7 -- cleanup runs even when completion raises after persisting.
# ==========================================================================

def test_submit_releases_the_claim_when_complete_raises_after_persisting():
    """`complete()` persists the terminal transition first, then syncs GitHub
    and writes the review submission. When a later step raises, the Run is
    already terminal -- so the execution-map claim must still be released, or
    it is held forever for a Run that has finished."""
    run = _run(status="succeeded")
    store = _ClaimStore()
    claim = store.hold("run-1")

    def complete(run_id, status, envelope):
        raise RuntimeError("review submission store unwritable")

    app = _launcher(_dispatcherish(_Registry(run), complete), claim_store=store)
    app._claims_by_run["run-1"] = claim
    with pytest.raises(RuntimeError) as exc:
        app.submit("run-1", {"status": "succeeded"})
    # The original error survives the cleanup...
    assert "review submission store unwritable" in str(exc.value)
    # ...and the claim was released, with the Run's real terminal status.
    assert store.released == [("run-1", "terminal:succeeded")]


def test_a_failing_cleanup_never_masks_the_original_error():
    """A cleanup must not convert one failure into a different, misleading one."""
    class ExplodingStore(_ClaimStore):
        def release(self, *args, **kwargs):
            raise RuntimeError("release exploded")

    store = ExplodingStore()
    claim = store.hold("run-1")

    def complete(run_id, status, envelope):
        raise RuntimeError("the original failure")

    app = _launcher(_dispatcherish(_Registry(_run(status="succeeded")), complete),
                    claim_store=store)
    app._claims_by_run["run-1"] = claim
    with pytest.raises(RuntimeError) as exc:
        app.submit("run-1", {"status": "succeeded"})
    assert "the original failure" in str(exc.value)


def test_a_cleanup_baseexception_never_masks_the_primary_baseexception():
    class ExplodingStore(_ClaimStore):
        def release(self, *args, **kwargs):
            raise SystemExit("cleanup")

    store = ExplodingStore()
    claim = store.hold("run-1")

    def complete(run_id, status, envelope):
        raise KeyboardInterrupt("primary")

    app = _launcher(_dispatcherish(_Registry(_run(status="succeeded")), complete),
                    claim_store=store)
    app._claims_by_run["run-1"] = claim
    with pytest.raises(KeyboardInterrupt, match="primary"):
        app.submit("run-1", {"status": "succeeded"})


def test_the_release_reason_records_what_actually_happened():
    """On the failure path the status is read back from the registry, so the
    release reason states the Run's real terminal status rather than a guess."""
    store = _ClaimStore()
    claim = store.hold("run-1")

    def complete(run_id, status, envelope):
        raise RuntimeError("later step failed")

    app = _launcher(_dispatcherish(_Registry(_run(status="blocked")), complete),
                    claim_store=store)
    app._claims_by_run["run-1"] = claim
    with pytest.raises(RuntimeError):
        app.submit("run-1", {"status": "succeeded"})
    assert store.released == [("run-1", "terminal:blocked")]


def test_submit_still_releases_the_claim_on_the_success_path():
    run = _run(status="succeeded")
    store = _ClaimStore()
    claim = store.hold("run-1")
    app = _launcher(_dispatcherish(_Registry(run), lambda *a: run), claim_store=store)
    app._claims_by_run["run-1"] = claim
    assert app.submit("run-1", {"status": "succeeded"})["status"] == "succeeded"
    assert store.released == [("run-1", "terminal:succeeded")]


def test_releasing_twice_is_harmless():
    """Replay safety: the claim is popped and the store no longer reports it
    active, so a second pass releases nothing."""
    store = _ClaimStore()
    claim = store.hold("run-1")
    app = _launcher(_dispatcherish(_Registry(_run(status="succeeded"))), claim_store=store)
    app._claims_by_run["run-1"] = claim
    app._release_terminal_claim("run-1", status="succeeded")
    app._release_terminal_claim("run-1", status="succeeded")
    assert store.released == [("run-1", "terminal:succeeded")]


def test_a_run_with_no_claim_releases_nothing():
    store = _ClaimStore()
    app = _launcher(_dispatcherish(_Registry(_run(status="succeeded"))), claim_store=store)
    app._release_terminal_claim("run-1", status="succeeded")
    assert store.released == []


# ==========================================================================
# Finding 8 -- the review-sync workflow must actually be able to run.
# ==========================================================================

WORKFLOW = REPO_ROOT / ".github" / "workflows" / "review-sync-trigger.yml"


def _workflow():
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _sync_step():
    steps = _workflow()["jobs"]["sync-review"]["steps"]
    return next(s for s in steps if "sync-review" in str(s.get("run", "")))


def test_the_review_sync_workflow_can_import_the_cli_it_invokes():
    """`cli` lives in agent-platform/, not at the repository root, and this job
    deliberately does not install the package. `python -m cli.unified_cli` from
    the root therefore failed with ModuleNotFoundError on every trigger: the
    pass never ran, and the job's green tick said nothing at all."""
    step = _sync_step()
    assert "python -m cli.unified_cli" in str(step["run"])
    working_dir = str(step.get("working-directory", "")).strip()
    if working_dir in ("", "."):
        pythonpath = str(step.get("env", {}).get("PYTHONPATH", ""))
        assert "agent-platform" in pythonpath, (
            "running from the repository root requires agent-platform on PYTHONPATH")
    else:
        assert working_dir == "agent-platform"


def test_review_sync_has_an_explicit_manual_recovery_trigger():
    workflow = _workflow()
    triggers = workflow.get("on", workflow.get(True, {}))
    assert "workflow_dispatch" in triggers


def test_the_workflow_fails_loudly_if_the_import_path_regresses():
    """A guard step, so a future path change fails the job instead of silently
    skipping the pass -- which is how this defect stayed invisible."""
    invocation = str(_sync_step()["run"])
    assert "import cli.unified_cli" in invocation
    assert "set -euo pipefail" in invocation


def test_the_store_paths_stay_repository_relative():
    """The working directory stays at the root so REVIEW_SYNC_STORE and
    REVIEW_SYNC_STATE_DIR keep resolving as repository-relative paths."""
    env = _workflow()["jobs"]["sync-review"]["env"]
    assert "agent-platform/.sessions" in str(env["REVIEW_SYNC_STORE"])
    assert "agent-platform/.daemon-state" in str(env["REVIEW_SYNC_STATE_DIR"])
    assert str(_sync_step().get("working-directory", "")).strip() in ("", ".")


def test_the_anti_loop_and_concurrency_guards_survive_the_fix():
    """The fix must not quietly drop the guards the workflow already had."""
    doc = _workflow()
    assert doc["concurrency"]["group"] == "review-sync"
    guard = doc["jobs"]["sync-review"]["if"]
    assert "github-actions[bot]" in guard
    assert "cortxt-atlas[bot]" in guard


def test_the_cli_is_importable_exactly_the_way_the_workflow_invokes_it():
    """The decisive check, not a reading of the YAML: run the import in a
    subprocess with `-S`, so no editable install can answer for the path the
    workflow actually has."""
    base_env = {"SYSTEMROOT": "C:\\Windows", "PATH": ""}
    without = subprocess.run(
        [sys.executable, "-S", "-c", "import cli.unified_cli"],
        cwd=str(REPO_ROOT), capture_output=True, text=True, env=base_env)
    assert without.returncode != 0, (
        "precondition: from the repository root with no PYTHONPATH the import "
        "must fail, or this test proves nothing")
    with_path = subprocess.run(
        [sys.executable, "-S", "-c", "import cli.unified_cli"],
        cwd=str(REPO_ROOT), capture_output=True, text=True,
        env={**base_env, "PYTHONPATH": "agent-platform"})
    assert with_path.returncode == 0, with_path.stderr
