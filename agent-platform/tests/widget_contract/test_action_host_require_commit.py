"""S7b dogfood defect regression: proof/gated-launch source-integrity gate.

A previous session started the action host through an installed `cortxt.exe`
and silently ran stale code (a fixed cp1252 bug reappeared). `source_signature`
reports the actually-running commit; `main(require_commit=...)` refuses to
start when it does not match -- an opt-in check so ordinary local
`cortxt widget --enable-actions` usage (no `--require-commit`) is unaffected,
while proof/gated-launch tooling that DOES pass it fails closed against a
stale checkout or wrong worktree.
"""
from pathlib import Path

from widget.action_host import main, source_signature


def test_source_signature_reports_unknown_when_git_unavailable():
    def _raising(*args, **kwargs):
        raise FileNotFoundError("git not found")
    sig = source_signature(run_subprocess=_raising, repo_dir=Path("."))
    assert sig["git_commit"] == "unknown"
    assert sig["git_branch"] == "unknown"


def test_require_commit_match_starts_the_host(monkeypatch):
    """A matching --require-commit does not block startup."""
    started = {}

    class _FakeServer:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def serve_forever(self):
            started["served"] = True
            raise KeyboardInterrupt()

    import widget.action_host as action_host_mod
    monkeypatch.setattr(action_host_mod, "_ReusableThreadingHTTPServer", _FakeServer)
    monkeypatch.setattr(action_host_mod, "source_signature",
                        lambda: {"module_file": "x", "repo_dir": "y",
                                 "git_commit": "abc123", "git_branch": "main"})
    rc = main(require_commit="abc123")
    assert rc == 0
    assert started.get("served") is True


def test_require_commit_mismatch_refuses_to_start(monkeypatch, capsys):
    """A mismatched --require-commit fails closed BEFORE the server binds --
    the S7b dogfood defect this check exists to catch (stale cortxt.exe or
    wrong worktree silently serving old code)."""
    bound = {}

    class _FakeServer:
        def __init__(self, *a, **k):
            bound["called"] = True

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def serve_forever(self):
            pass

    import widget.action_host as action_host_mod
    monkeypatch.setattr(action_host_mod, "_ReusableThreadingHTTPServer", _FakeServer)
    monkeypatch.setattr(action_host_mod, "source_signature",
                        lambda: {"module_file": "x", "repo_dir": "y",
                                 "git_commit": "wrong-commit", "git_branch": "main"})
    rc = main(require_commit="expected-commit")
    assert rc == 1
    assert "called" not in bound  # the HTTP server was never even constructed
    out = capsys.readouterr().out
    assert "refusing to start" in out


def test_no_require_commit_is_backward_compatible_ordinary_local_use(monkeypatch):
    """Omitting --require-commit (the default) never blocks ordinary local
    `cortxt widget --enable-actions` regardless of the running commit."""
    class _FakeServer:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def serve_forever(self):
            raise KeyboardInterrupt()

    import widget.action_host as action_host_mod
    monkeypatch.setattr(action_host_mod, "_ReusableThreadingHTTPServer", _FakeServer)
    monkeypatch.setattr(action_host_mod, "source_signature",
                        lambda: {"module_file": "x", "repo_dir": "y",
                                 "git_commit": "whatever", "git_branch": "main"})
    assert main() == 0


def test_source_signature_reports_clean_and_dirty_worktree(tmp_path):
    """`clean_status` reflects `git status --porcelain`: clean when empty,
    dirty when it reports anything (staged, unstaged, or untracked)."""
    import subprocess

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=repo, capture_output=True, check=True)
    (repo / "f.txt").write_text("x")
    subprocess.run(["git", "add", "f.txt"], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, capture_output=True, check=True)

    sig_clean = source_signature(repo_dir=repo)
    assert sig_clean["clean_status"] == "clean"

    (repo / "f.txt").write_text("changed")
    sig_dirty = source_signature(repo_dir=repo)
    assert sig_dirty["clean_status"] == "dirty"


def _init_repo(repo: Path) -> None:
    import subprocess
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=repo, capture_output=True, check=True)
    (repo / "f.txt").write_text("x")
    # `scripts/` must already be a tracked directory (as it is in the real
    # repo) so `git status --porcelain` lists the untracked audit-evidence
    # files individually, not the whole new directory collapsed to one line.
    (repo / "scripts").mkdir()
    (repo / "scripts" / "dispatcher.py").write_text("# placeholder")
    subprocess.run(["git", "add", "f.txt", "scripts/dispatcher.py"], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, capture_output=True, check=True)


def test_source_signature_ignores_known_audit_evidence_files(tmp_path):
    """Only the four known audit-evidence paths, all untracked and nothing
    else changed, must still read as clean -- they are proof-run artifacts
    left deliberately untracked (#482), not a sign the worktree is dirty."""
    repo = tmp_path / "repo"
    _init_repo(repo)

    scripts_dir = repo / "scripts"
    (scripts_dir / "runs.json").write_text("{}")
    (scripts_dir / "runs.claims.sqlite3").write_bytes(b"")
    (scripts_dir / "runs.claims.sqlite3-shm").write_bytes(b"")
    (scripts_dir / "runs.claims.sqlite3-wal").write_bytes(b"")

    sig = source_signature(repo_dir=repo)
    assert sig["clean_status"] == "clean"


def test_source_signature_dirty_with_extra_untracked_file_alongside_known(tmp_path):
    """An additional untracked file alongside the four known ones must still
    make the worktree dirty -- the exemption covers exactly those four
    paths, not "any untracked files present"."""
    repo = tmp_path / "repo"
    _init_repo(repo)

    scripts_dir = repo / "scripts"
    (scripts_dir / "runs.json").write_text("{}")
    (scripts_dir / "other_untracked.txt").write_text("surprise")

    sig = source_signature(repo_dir=repo)
    assert sig["clean_status"] == "dirty"


def test_source_signature_dirty_with_modified_tracked_file(tmp_path):
    """A modified tracked file must still make the worktree dirty, even
    with none of the four known audit-evidence files present."""
    repo = tmp_path / "repo"
    _init_repo(repo)

    (repo / "f.txt").write_text("changed")

    sig = source_signature(repo_dir=repo)
    assert sig["clean_status"] == "dirty"


def test_source_signature_path_match_is_exact_not_prefix(tmp_path):
    """A file that merely looks like a known audit-evidence path (a `.bak`
    sibling, or the same basename in a different directory) is NOT exempted
    and still makes the worktree dirty -- the match is exact, not a
    prefix/substring match."""
    repo = tmp_path / "repo"
    _init_repo(repo)

    scripts_dir = repo / "scripts"
    (scripts_dir / "runs.json.bak").write_text("{}")

    sig = source_signature(repo_dir=repo)
    assert sig["clean_status"] == "dirty"

    other_dir = repo / "other" / "scripts"
    other_dir.mkdir(parents=True)
    (other_dir / "runs.json").write_text("{}")
    (scripts_dir / "runs.json.bak").unlink()

    sig2 = source_signature(repo_dir=repo)
    assert sig2["clean_status"] == "dirty"


def test_require_clean_refuses_dirty_worktree(monkeypatch, capsys):
    """A dirty worktree with --require-clean fails closed BEFORE the server
    binds, even when --require-commit matches: a matching SHA alone doesn't
    prove the working tree matches it."""
    bound = {}

    class _FakeServer:
        def __init__(self, *a, **k):
            bound["called"] = True

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def serve_forever(self):
            pass

    import widget.action_host as action_host_mod
    monkeypatch.setattr(action_host_mod, "_ReusableThreadingHTTPServer", _FakeServer)
    monkeypatch.setattr(action_host_mod, "source_signature",
                        lambda: {"module_file": "x", "repo_dir": "y",
                                 "git_commit": "abc123", "git_branch": "main",
                                 "clean_status": "dirty"})
    rc = main(require_commit="abc123", require_clean=True)
    assert rc == 1
    assert "called" not in bound
    out = capsys.readouterr().out
    assert "refusing to start" in out


def test_require_clean_starts_on_clean_worktree(monkeypatch):
    """A clean worktree with matching --require-commit and --require-clean
    starts normally."""
    started = {}

    class _FakeServer:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def serve_forever(self):
            started["served"] = True
            raise KeyboardInterrupt()

    import widget.action_host as action_host_mod
    monkeypatch.setattr(action_host_mod, "_ReusableThreadingHTTPServer", _FakeServer)
    monkeypatch.setattr(action_host_mod, "source_signature",
                        lambda: {"module_file": "x", "repo_dir": "y",
                                 "git_commit": "abc123", "git_branch": "main",
                                 "clean_status": "clean"})
    rc = main(require_commit="abc123", require_clean=True)
    assert rc == 0
    assert started.get("served") is True


def test_require_clean_omitted_is_backward_compatible(monkeypatch):
    """Omitting --require-clean (the default) never blocks startup, even on
    a dirty worktree -- ordinary local widget use is unaffected."""
    started = {}

    class _FakeServer:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def serve_forever(self):
            started["served"] = True
            raise KeyboardInterrupt()

    import widget.action_host as action_host_mod
    monkeypatch.setattr(action_host_mod, "_ReusableThreadingHTTPServer", _FakeServer)
    monkeypatch.setattr(action_host_mod, "source_signature",
                        lambda: {"module_file": "x", "repo_dir": "y",
                                 "git_commit": "abc123", "git_branch": "main",
                                 "clean_status": "dirty"})
    assert main() == 0
    assert started.get("served") is True
