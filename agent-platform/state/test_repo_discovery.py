"""Tests for read-area repository discovery (B-16).

Colocated with the module per the ``state/`` convention.

No test shells out. ``discover_repositories`` takes an injectable ``runner``
with ``subprocess.run``'s signature, and every test here passes a fake one, so
the suite is fast, offline and deterministic, and can assert things a real git
would not let it -- a failing ``git status``, a repository with no
``origin/main``, a missing git binary.

The trees are real directories, because what counts as a repository is a
filesystem question (a ``.git`` that may be a file or a directory) and faking
that would test the fake.
"""

import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from repo_discovery import (
    DiscoveryCaps,
    RepoObservation,
    discover_repositories,
)


def fake_git(**answers):
    """A ``subprocess.run`` stand-in answering per git subcommand.

    Keys are the distinguishing part of the command ("branch", "head",
    "origin", "status", "main"); a value is either the stdout string or the
    sentinel ``FAIL`` for a non-zero exit. Recorded calls are exposed on
    ``.calls`` so a test can assert what was and was not run.
    """
    calls = []

    def _run(argv, **kwargs):
        calls.append(SimpleNamespace(argv=list(argv), kwargs=kwargs))
        joined = " ".join(argv)
        if "--abbrev-ref" in argv:
            key = "branch"
        elif "refs/remotes/origin/main" in argv:
            key = "main"
        elif "remote" in argv:
            key = "origin"
        elif "status" in argv:
            key = "status"
        else:
            key = "head"
        answer = answers.get(key, DEFAULTS[key])
        if answer is FAIL:
            return SimpleNamespace(returncode=1, stdout="", stderr=f"fake failure: {joined}")
        return SimpleNamespace(returncode=0, stdout=answer, stderr="")

    _run.calls = calls
    return _run


FAIL = object()
DEFAULTS = {
    "branch": "feat/some-branch\n",
    "head": "a" * 40 + "\n",
    "origin": "https://github.com/example/repo.git\n",
    "status": "",
    "main": "b" * 40 + "\n",
}


class DiscoveryTestCase(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()

    def tearDown(self):
        self.temporary.cleanup()

    def make_repo(self, relative, *, as_file=False):
        """A directory carrying a ``.git`` entry, as a dir or as a file."""
        target = self.root / relative
        target.mkdir(parents=True, exist_ok=True)
        if as_file:
            (target / ".git").write_text("gitdir: /elsewhere/.git/worktrees/x\n",
                                         encoding="utf-8")
        else:
            (target / ".git").mkdir()
        return target

    def discover(self, *, roots=None, **kwargs):
        kwargs.setdefault("runner", fake_git())
        return discover_repositories(roots if roots is not None else [self.root], **kwargs)

    def caveat_text(self, observation):
        return " ".join(observation.caveats)

    # --- the unconfigured case ---------------------------------------------

    def test_no_roots_yields_no_observations(self):
        # The unconfigured state, and not a failure: nothing is gated on it.
        self.assertEqual(discover_repositories([], runner=fake_git()), [])

    def test_a_root_with_no_repositories_yields_no_observations(self):
        (self.root / "just" / "some" / "dirs").mkdir(parents=True)
        self.assertEqual(self.discover(), [])

    # --- what counts as a repository ---------------------------------------

    def test_a_directory_with_a_dot_git_directory_is_a_repository(self):
        repo = self.make_repo("alpha")
        found = self.discover()
        self.assertEqual([o.path for o in found], [repo])

    def test_a_worktree_whose_dot_git_is_a_file_is_a_repository(self):
        # A linked worktree's .git is a FILE. Treating only directories as
        # repositories would make every worktree invisible.
        repo = self.make_repo("a-worktree", as_file=True)
        self.assertEqual([o.path for o in self.discover()], [repo])

    def test_the_root_itself_can_be_the_repository(self):
        (self.root / ".git").mkdir()
        self.assertEqual([o.path for o in self.discover()], [self.root])

    def test_discovery_does_not_descend_into_a_repository(self):
        outer = self.make_repo("outer")
        self.make_repo("outer/vendored")
        self.assertEqual([o.path for o in self.discover()], [outer])

    def test_the_name_is_the_directory_name(self):
        self.make_repo("projects/ai-workspace-control-plane")
        self.assertEqual(self.discover()[0].name, "ai-workspace-control-plane")

    def test_several_repositories_are_reported_in_a_stable_order(self):
        for name in ("charlie", "alpha", "bravo"):
            self.make_repo(f"projects/{name}")
        names = [o.name for o in self.discover()]
        self.assertEqual(names, sorted(names))

    def test_several_roots_are_all_scanned(self):
        first, second = self.root / "one", self.root / "two"
        (first / "repo-a" / ".git").mkdir(parents=True)
        (second / "repo-b" / ".git").mkdir(parents=True)
        found = self.discover(roots=[first, second])
        self.assertEqual([o.name for o in found], ["repo-a", "repo-b"])

    # --- the revision state -------------------------------------------------

    def test_the_observation_carries_branch_head_origin_and_clean_state(self):
        self.make_repo("alpha")
        found = self.discover(runner=fake_git())[0]
        self.assertEqual(found.branch, "feat/some-branch")
        self.assertEqual(found.head, "a" * 40)
        self.assertEqual(found.origin_url, "https://github.com/example/repo.git")
        self.assertIs(found.dirty, False)
        self.assertEqual(found.origin_main_ref, "b" * 40)

    def test_a_non_empty_status_reads_as_dirty_with_a_caveat(self):
        self.make_repo("alpha")
        found = self.discover(runner=fake_git(status=" M file.py\n"))[0]
        self.assertIs(found.dirty, True)
        self.assertIn("uncommitted changes", self.caveat_text(found))
        self.assertIn("do not match the commit", self.caveat_text(found))

    def test_a_detached_head_reports_no_branch_rather_than_the_word_head(self):
        self.make_repo("alpha")
        found = self.discover(runner=fake_git(branch="HEAD\n"))[0]
        self.assertIsNone(found.branch)
        self.assertIn("detached", self.caveat_text(found))

    def test_the_observation_is_frozen(self):
        self.make_repo("alpha")
        found = self.discover()[0]
        with self.assertRaises(Exception):
            found.branch = "something-else"

    def test_caveats_is_a_tuple(self):
        self.make_repo("alpha")
        self.assertIsInstance(self.discover()[0].caveats, tuple)

    # --- caveats: the point of the unit --------------------------------------

    def test_a_present_origin_main_ref_is_declared_local_and_unverified(self):
        """The 2026-09-16 trap, stated in the result itself.

        A local refs/remotes/origin/main is whatever the last fetch brought
        down. On 2026-09-16 the primary checkout's was four days behind
        GitHub. A consumer that read the ref without this caveat would
        reproduce exactly that mistake.
        """
        self.make_repo("alpha")
        text = self.caveat_text(self.discover()[0])
        self.assertIn("LOCAL ref", text)
        self.assertIn("NOT been verified against the remote", text)
        self.assertIn("may be ahead", text)

    def test_a_missing_origin_main_ref_says_the_relation_is_unknown(self):
        self.make_repo("alpha")
        found = self.discover(runner=fake_git(main=FAIL))[0]
        self.assertIsNone(found.origin_main_ref)
        self.assertIn("cannot be established locally", self.caveat_text(found))

    def test_every_repository_carries_at_least_one_caveat(self):
        # There is no state of the world in which an observation is complete:
        # the origin/main relation is always either local-and-unverified or
        # unknown. A caveat-free observation would therefore be a bug.
        self.make_repo("alpha")
        self.assertTrue(self.discover()[0].caveats)

    def test_a_failed_branch_read_yields_none_plus_a_caveat(self):
        self.make_repo("alpha")
        found = self.discover(runner=fake_git(branch=FAIL))[0]
        self.assertIsNone(found.branch)
        self.assertIn("branch", self.caveat_text(found))
        self.assertIn("unknown", self.caveat_text(found))

    def test_a_failed_head_read_yields_none_plus_a_caveat(self):
        self.make_repo("alpha")
        found = self.discover(runner=fake_git(head=FAIL))[0]
        self.assertIsNone(found.head)
        self.assertIn("checked-out commit", self.caveat_text(found))

    def test_a_failed_origin_read_yields_none_plus_a_caveat(self):
        self.make_repo("alpha")
        found = self.discover(runner=fake_git(origin=FAIL))[0]
        self.assertIsNone(found.origin_url)
        self.assertIn("origin", self.caveat_text(found))

    def test_a_failed_status_read_yields_none_not_false(self):
        # False would assert the working copy is clean. It is unknown.
        self.make_repo("alpha")
        found = self.discover(runner=fake_git(status=FAIL))[0]
        self.assertIsNone(found.dirty)
        self.assertIn("whether there are uncommitted changes is unknown",
                      self.caveat_text(found))

    def test_no_field_is_ever_an_empty_string_standing_in_for_a_value(self):
        self.make_repo("alpha")
        found = self.discover(runner=fake_git(branch="\n", head="\n", origin="\n",
                                              main="\n"))[0]
        for value in (found.branch, found.head, found.origin_url, found.origin_main_ref):
            self.assertIsNot(value, "")
            self.assertIsNone(value)

    def test_a_missing_git_binary_yields_an_all_unknown_observation(self):
        def _explodes(argv, **kwargs):
            raise OSError("git is not installed")
        self.make_repo("alpha")
        found = self.discover(runner=_explodes)[0]
        self.assertEqual(
            (found.branch, found.head, found.origin_url, found.dirty,
             found.origin_main_ref),
            (None, None, None, None, None))
        self.assertGreaterEqual(len(found.caveats), 5)

    def test_a_git_timeout_is_an_unknown_not_a_crash(self):
        def _times_out(argv, **kwargs):
            raise subprocess.TimeoutExpired(cmd=argv, timeout=1)
        self.make_repo("alpha")
        found = self.discover(runner=_times_out)[0]
        self.assertIsNone(found.head)

    # --- caps ----------------------------------------------------------------

    def test_max_depth_bounds_how_far_below_a_root_discovery_descends(self):
        self.make_repo("a/b/c/d/deep")
        self.assertEqual(self.discover(caps=DiscoveryCaps(max_depth=3)), [])
        self.assertEqual(len(self.discover(caps=DiscoveryCaps(max_depth=5))), 1)

    def test_a_repository_at_exactly_max_depth_is_found(self):
        self.make_repo("a/b/c")
        found = self.discover(caps=DiscoveryCaps(max_depth=3))
        self.assertEqual([o.name for o in found], ["c"])

    def test_max_repositories_truncates(self):
        for name in ("alpha", "bravo", "charlie", "delta"):
            self.make_repo(f"projects/{name}")
        found = self.discover(caps=DiscoveryCaps(max_repositories=2))
        self.assertEqual(len(found), 2)

    def test_truncation_is_visible_as_a_caveat_never_silent(self):
        for name in ("alpha", "bravo", "charlie"):
            self.make_repo(f"projects/{name}")
        found = self.discover(caps=DiscoveryCaps(max_repositories=2))
        text = self.caveat_text(found[-1])
        self.assertIn("TRUNCATED", text)
        self.assertIn("max_repositories", text)

    def test_an_untruncated_result_is_not_labelled_truncated(self):
        # A complete result labelled incomplete is its own dishonesty.
        for name in ("alpha", "bravo"):
            self.make_repo(f"projects/{name}")
        found = self.discover(caps=DiscoveryCaps(max_repositories=2))
        self.assertEqual(len(found), 2)
        self.assertNotIn("TRUNCATED", self.caveat_text(found[-1]))

    def test_a_cap_below_one_is_refused_at_construction(self):
        """The degenerate state, closed where it is constructible.

        With a cap of 0 the first repository found trips truncation before
        anything has been appended, so the notice has nothing to ride on and
        discovery returns [] -- indistinguishable from a read area with no
        repositories in it. That is the one configuration in which truncation
        was silent, and silence is what this module exists to prevent.
        """
        with self.assertRaises(ValueError) as caught:
            DiscoveryCaps(max_repositories=0)
        self.assertIn("at least 1", str(caught.exception))

    def test_a_negative_cap_is_refused_too(self):
        with self.assertRaises(ValueError):
            DiscoveryCaps(max_repositories=-1)

    def test_the_refusal_says_how_to_scan_nothing(self):
        # A refusal names the fix, not only the fault.
        with self.assertRaises(ValueError) as caught:
            DiscoveryCaps(max_repositories=0)
        self.assertIn("pass no roots", str(caught.exception))

    def test_a_cap_of_one_is_allowed_and_still_reports_truncation(self):
        # The smallest cap that can describe its own result, so it must work.
        for name in ("alpha", "bravo"):
            self.make_repo(f"projects/{name}")
        found = self.discover(caps=DiscoveryCaps(max_repositories=1))
        self.assertEqual(len(found), 1)
        self.assertIn("TRUNCATED", self.caveat_text(found[0]))

    def test_a_negative_depth_is_refused(self):
        # It silently behaved as 0 rather than meaning anything of its own.
        with self.assertRaises(ValueError) as caught:
            DiscoveryCaps(max_depth=-1)
        self.assertIn("zero or greater", str(caught.exception))

    def test_a_depth_of_zero_is_allowed_and_looks_only_at_the_roots(self):
        (self.root / ".git").mkdir()
        self.make_repo("nested/deeper")
        found = self.discover(caps=DiscoveryCaps(max_depth=0))
        self.assertEqual([o.path for o in found], [self.root])

    def test_no_constructible_caps_can_truncate_silently(self):
        """The reviewer's requirement, stated as one assertion.

        Every cap DiscoveryCaps permits to exist must produce a result in
        which truncation is visible. A rule that holds only for the values
        callers happen to pass today is not a rule.
        """
        for name in ("alpha", "bravo", "charlie"):
            self.make_repo(f"projects/{name}")
        for cap in range(1, 5):
            found = self.discover(caps=DiscoveryCaps(max_repositories=cap))
            was_truncated = len(found) < 3
            says_truncated = bool(found) and "TRUNCATED" in self.caveat_text(found[-1])
            self.assertEqual(was_truncated, says_truncated,
                             f"cap={cap} truncated={was_truncated} but said {says_truncated}")

    def test_the_default_caps_are_the_documented_ones(self):
        self.assertEqual((DiscoveryCaps().max_depth, DiscoveryCaps().max_repositories),
                         (3, 64))

    # --- offline and read-only, by construction ------------------------------

    def test_every_git_call_passes_utf8_encoding(self):
        # The repository convention, and the exact defect fixed in 5c44425:
        # without it, Python decodes subprocess output as cp1252 here.
        self.make_repo("alpha")
        runner = fake_git()
        self.discover(runner=runner)
        self.assertTrue(runner.calls)
        for call in runner.calls:
            self.assertEqual(call.kwargs.get("encoding"), "utf-8")

    def test_no_git_call_touches_the_network(self):
        self.make_repo("alpha")
        runner = fake_git()
        self.discover(runner=runner)
        forbidden = ("fetch", "ls-remote", "pull", "push", "clone", "remote update")
        for call in runner.calls:
            joined = " ".join(call.argv)
            for word in forbidden:
                self.assertNotIn(word, joined)

    def test_no_git_call_mutates_the_repository(self):
        # Read is not write: discovery is read-only by construction.
        self.make_repo("alpha")
        runner = fake_git()
        self.discover(runner=runner)
        mutating = ("commit", "checkout", "switch", "reset", "merge", "rebase",
                    "add", "config", "gc", "prune", "clean")
        for call in runner.calls:
            subcommand = call.argv[3] if len(call.argv) > 3 else ""
            self.assertNotIn(subcommand, mutating)

    def test_git_is_addressed_with_dash_c_rather_than_a_working_directory(self):
        self.make_repo("alpha")
        runner = fake_git()
        self.discover(runner=runner)
        for call in runner.calls:
            self.assertEqual(call.argv[:2], ["git", "-C"])

    def test_discovery_writes_nothing_into_the_tree(self):
        repo = self.make_repo("alpha")
        before = sorted(p.name for p in repo.iterdir())
        self.discover()
        self.assertEqual(sorted(p.name for p in repo.iterdir()), before)

    def test_the_default_runner_is_subprocess_run(self):
        # Pinned so the injection seam cannot quietly become the only path.
        import inspect
        source = inspect.getsource(discover_repositories)
        self.assertIn("subprocess.run if runner is None", source)

    # --- the dataclass shape -------------------------------------------------

    def test_the_observation_fields_are_the_contract(self):
        self.assertEqual(
            tuple(RepoObservation.__dataclass_fields__),
            ("path", "name", "origin_url", "branch", "head", "dirty",
             "origin_main_ref", "caveats"))


if __name__ == "__main__":
    unittest.main()
