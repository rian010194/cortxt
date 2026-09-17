"""Tests for the Cortxt data-home resolver (B-1).

Colocated with the module per the C-2 convention that ``state/`` tests live
beside the code (``tests/state/`` does not exist).

The valid-path cases run against a temporary directory with
``tempfile.gettempdir`` patched away, because a real data home under Temp/ is
exactly what the resolver refuses. Patching the seam keeps the tests from
writing anywhere durable while still exercising the success path.
"""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import data_home
from data_home import DATA_HOME_ENV, DataHomeError, core_root, resolve_data_home


class DataHomeTestCase(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.tmp = Path(self.temporary.name).resolve()
        # A checkout root that no test path is inside, unless it says so.
        self.checkout = self.tmp / "checkout"
        self.checkout.mkdir()
        # Move the "system temp directory" somewhere nothing under test lives,
        # so self.tmp reads as an ordinary durable location.
        self.no_temp = mock.patch.object(
            data_home.tempfile, "gettempdir",
            return_value=str(self.tmp / "pretend-temp"))

    def tearDown(self):
        self.temporary.cleanup()

    def _resolve(self, value, **kwargs):
        kwargs.setdefault("env", {})
        kwargs.setdefault("repo_root", self.checkout)
        return resolve_data_home(value, **kwargs)

    def assertCode(self, code, value, **kwargs):
        with self.assertRaises(DataHomeError) as caught:
            self._resolve(value, **kwargs)
        self.assertEqual(caught.exception.code, code)
        return caught.exception

    # --- unset is not an error: today's behaviour, preserved ----------------

    def test_unset_environment_resolves_to_none(self):
        self.assertIsNone(resolve_data_home(None, env={}, repo_root=self.checkout))

    def test_unrelated_environment_variables_do_not_configure_a_home(self):
        self.assertIsNone(resolve_data_home(
            None, env={"HOME": str(self.tmp)}, repo_root=self.checkout))

    # --- resolution order ---------------------------------------------------

    def test_explicit_argument_wins_over_the_environment(self):
        with self.no_temp:
            chosen = self.tmp / "explicit"
            resolved = resolve_data_home(
                chosen, env={DATA_HOME_ENV: str(self.tmp / "from-env")},
                repo_root=self.checkout)
        self.assertEqual(resolved, chosen)

    def test_environment_is_used_when_no_argument_is_given(self):
        with self.no_temp:
            resolved = resolve_data_home(
                None, env={DATA_HOME_ENV: str(self.tmp / "from-env")},
                repo_root=self.checkout)
        self.assertEqual(resolved, self.tmp / "from-env")

    # --- the success shape --------------------------------------------------

    def test_valid_absolute_path_outside_the_checkout_resolves(self):
        with self.no_temp:
            resolved = self._resolve(self.tmp / "cortxt-data")
        self.assertTrue(resolved.is_absolute())
        self.assertEqual(resolved, self.tmp / "cortxt-data")

    def test_the_directory_is_not_created_here(self):
        # CoreStore.__init__ already creates it; doing it twice would be two
        # authorities for one rule.
        target = self.tmp / "not-created"
        with self.no_temp:
            self._resolve(target)
        self.assertFalse(target.exists())

    def test_an_existing_directory_is_accepted(self):
        target = self.tmp / "already-here"
        target.mkdir()
        with self.no_temp:
            self.assertEqual(self._resolve(target), target)

    # --- one case per refusal code -----------------------------------------

    def test_empty_value_refused_as_unset_value(self):
        self.assertCode("unset_value", "")

    def test_whitespace_only_value_refused_as_unset_value(self):
        self.assertCode("unset_value", "   ")

    def test_relative_path_refused_as_not_absolute(self):
        error = self.assertCode("not_absolute", "cortxt-data")
        self.assertIn("working directory", str(error))

    def test_parent_traversal_refused_as_unsafe_path(self):
        self.assertCode("unsafe_path", self.tmp / ".." / "escape")

    def test_path_inside_the_checkout_refused(self):
        error = self.assertCode("inside_checkout", self.checkout / "agent-platform" / "data")
        self.assertIn("changes branch", str(error))

    def test_the_checkout_root_itself_is_refused(self):
        self.assertCode("inside_checkout", self.checkout)

    def test_path_under_the_system_temp_directory_refused(self):
        # Unpatched gettempdir: self.tmp really is under it.
        self.assertCode("temp_path", self.tmp / "core-data")

    def test_path_that_is_an_existing_file_refused_as_io_error(self):
        target = self.tmp / "a-file"
        target.write_text("not a directory", encoding="utf-8")
        with self.no_temp:
            error = self.assertCode("io_error", target)
        self.assertIn("not a directory", str(error))

    def test_uncreatable_path_refused_as_io_error(self):
        blocker = self.tmp / "blocking-file"
        blocker.write_text("x", encoding="utf-8")
        with self.no_temp:
            self.assertCode("io_error", blocker / "beneath" / "a" / "file")

    def test_a_refusal_names_the_source_of_the_offending_value(self):
        # The operator has to know which of the two inputs to fix.
        from_env = self.assertCode("not_absolute", None,
                                   env={DATA_HOME_ENV: "relative"})
        self.assertIn(DATA_HOME_ENV, str(from_env))
        from_arg = self.assertCode("not_absolute", "relative")
        self.assertIn("--data-home", str(from_arg))

    def test_the_error_is_not_a_core_store_error(self):
        # Configuration codes, not storage categories: a misconfigured start
        # must not read as a storage failure.
        error = DataHomeError("not_absolute", "message")
        self.assertEqual(error.code, "not_absolute")
        self.assertFalse(hasattr(error, "category"))

    # --- core_root ----------------------------------------------------------

    def test_core_root_appends_core(self):
        self.assertEqual(core_root(self.tmp / "home"), self.tmp / "home" / "core")

    def test_core_root_does_not_create_anything(self):
        root = core_root(self.tmp / "home")
        self.assertFalse(root.exists())


if __name__ == "__main__":
    unittest.main()
