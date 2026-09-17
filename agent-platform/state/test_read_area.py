"""Tests for the Cortxt read-area resolver (B-16).

Colocated with the module per the convention that ``state/`` tests live beside
the code (``tests/state/`` does not exist), the same way
``test_data_home.py`` sits beside ``data_home.py``.

Roots must exist to be accepted, so every valid case runs against real
directories in a temporary tree. Unlike the data home, a read area under the
system temp directory is perfectly legitimate -- the resolver has no opinion
about where the operator keeps their repositories -- so nothing is patched.
"""

import os
import tempfile
import unittest
from pathlib import Path

from read_area import READ_AREA_ENV, ReadAreaError, resolve_read_area


class ReadAreaTestCase(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.tmp = Path(self.temporary.name).resolve()

    def tearDown(self):
        self.temporary.cleanup()

    def _dir(self, name):
        target = self.tmp / name
        target.mkdir(parents=True)
        return target

    def _resolve(self, value, **kwargs):
        kwargs.setdefault("env", {})
        return resolve_read_area(value, **kwargs)

    def assertCode(self, code, value, **kwargs):
        with self.assertRaises(ReadAreaError) as caught:
            self._resolve(value, **kwargs)
        self.assertEqual(caught.exception.code, code)
        return caught.exception

    # --- unconfigured is not an error: discovery never gates anything -------

    def test_unset_environment_resolves_to_an_empty_tuple(self):
        self.assertEqual(resolve_read_area(None, env={}), ())

    def test_the_empty_result_is_a_tuple_not_none(self):
        # Callers iterate it; None would make every call site branch.
        self.assertIsInstance(resolve_read_area(None, env={}), tuple)

    def test_unrelated_environment_variables_do_not_configure_a_read_area(self):
        self.assertEqual(
            resolve_read_area(None, env={"HOME": str(self.tmp)}), ())

    # --- resolution order ---------------------------------------------------

    def test_explicit_argument_wins_over_the_environment(self):
        chosen, other = self._dir("explicit"), self._dir("from-env")
        self.assertEqual(
            resolve_read_area(chosen, env={READ_AREA_ENV: str(other)}), (chosen,))

    def test_environment_is_used_when_no_argument_is_given(self):
        root = self._dir("from-env")
        self.assertEqual(
            resolve_read_area(None, env={READ_AREA_ENV: str(root)}), (root,))

    # --- the success shape --------------------------------------------------

    def test_a_single_existing_directory_resolves(self):
        root = self._dir("workspace")
        resolved = self._resolve(root)
        self.assertEqual(resolved, (root,))
        self.assertTrue(resolved[0].is_absolute())

    def test_several_roots_are_separated_by_the_platform_path_separator(self):
        first, second = self._dir("one"), self._dir("two")
        value = f"{first}{os.pathsep}{second}"
        self.assertEqual(self._resolve(value), (first, second))

    def test_the_order_given_is_the_order_returned(self):
        first, second, third = self._dir("a"), self._dir("b"), self._dir("c")
        value = os.pathsep.join(str(p) for p in (third, first, second))
        self.assertEqual(self._resolve(value), (third, first, second))

    def test_a_path_object_is_one_root_and_is_never_split(self):
        root = self._dir("single")
        self.assertEqual(self._resolve(root), (root,))

    def test_surrounding_whitespace_in_an_entry_is_tolerated(self):
        root = self._dir("padded")
        self.assertEqual(self._resolve(f"  {root}  "), (root,))

    def test_a_read_area_containing_a_checkout_is_accepted(self):
        # THE case data_home.py refuses and this resolver must not. A read
        # area exists in order to contain repository checkouts; refusing that
        # would refuse every valid configuration.
        root = self._dir("workspace")
        (root / "some-repo" / ".git").mkdir(parents=True)
        self.assertEqual(self._resolve(root), (root,))

    def test_nothing_is_created_and_nothing_is_written(self):
        root = self._dir("workspace")
        before = sorted(p.name for p in root.iterdir())
        self._resolve(root)
        self.assertEqual(sorted(p.name for p in root.iterdir()), before)

    # --- one case per refusal code -----------------------------------------

    def test_empty_value_refused_as_unset_value(self):
        self.assertCode("unset_value", "")

    def test_whitespace_only_value_refused_as_unset_value(self):
        self.assertCode("unset_value", "   ")

    def test_a_stray_separator_refused_as_unset_value(self):
        root = self._dir("one")
        error = self.assertCode("unset_value", f"{root}{os.pathsep}{os.pathsep}{root}")
        self.assertIn("empty entry", str(error))

    def test_relative_root_refused_as_not_absolute(self):
        error = self.assertCode("not_absolute", "workspace")
        self.assertIn("working directory", str(error))

    def test_one_relative_root_among_valid_ones_is_still_refused(self):
        root = self._dir("one")
        self.assertCode("not_absolute", f"{root}{os.pathsep}relative")

    def test_parent_traversal_refused_as_unsafe_path(self):
        self.assertCode("unsafe_path", self.tmp / ".." / "escape")

    def test_missing_directory_refused_as_not_a_directory(self):
        self.assertCode("not_a_directory", self.tmp / "never-created")

    def test_an_existing_file_refused_as_not_a_directory(self):
        target = self.tmp / "a-file"
        target.write_text("not a directory", encoding="utf-8")
        self.assertCode("not_a_directory", target)

    def test_the_same_root_twice_refused_as_duplicate_root(self):
        root = self._dir("one")
        error = self.assertCode("duplicate_root", f"{root}{os.pathsep}{root}")
        self.assertIn("twice", str(error))

    def test_a_root_nested_in_another_refused_as_duplicate_root(self):
        outer = self._dir("outer")
        inner = self._dir("outer/inner")
        self.assertCode("duplicate_root", f"{outer}{os.pathsep}{inner}")

    def test_nesting_is_refused_in_either_order(self):
        outer = self._dir("outer")
        inner = self._dir("outer/inner")
        self.assertCode("duplicate_root", f"{inner}{os.pathsep}{outer}")

    def test_sibling_roots_are_not_duplicates(self):
        first, second = self._dir("shared/one"), self._dir("shared/two")
        self.assertEqual(self._resolve(f"{first}{os.pathsep}{second}"),
                         (first, second))

    # --- the deliberate absence --------------------------------------------

    def test_the_repository_checkout_itself_is_a_valid_read_area(self):
        """The rule data_home.py has and this module must never acquire.

        Pinned behaviourally rather than left to the docstring: a future edit
        that copies the neighbouring resolver's refusal list would refuse
        every valid read area, and the failure would look like a
        configuration problem rather than a code one. This is the exact value
        ``test_data_home.test_the_checkout_root_itself_is_refused`` rejects.
        """
        import read_area
        checkout = Path(read_area.__file__).resolve().parent.parent.parent
        self.assertEqual(self._resolve(checkout), (checkout,))

    # --- the refusal has to be actionable -----------------------------------

    def test_a_refusal_names_the_source_of_the_offending_value(self):
        from_env = self.assertCode("not_absolute", None,
                                   env={READ_AREA_ENV: "relative"})
        self.assertIn(READ_AREA_ENV, str(from_env))
        from_arg = self.assertCode("not_absolute", "relative")
        self.assertIn("--read-area", str(from_arg))

    def test_the_error_is_not_a_core_store_error(self):
        error = ReadAreaError("not_absolute", "message")
        self.assertEqual(error.code, "not_absolute")
        self.assertFalse(hasattr(error, "category"))

    def test_the_error_carries_its_message_attribute(self):
        error = ReadAreaError("unset_value", "the message")
        self.assertEqual(error.message, "the message")
        self.assertEqual(str(error), "the message")


if __name__ == "__main__":
    unittest.main()
