"""Tests for the A4b append-only Core store (#609, frozen 4a sections 7.1/7.2).

Colocated with the module per the C-2 convention (``tests/state/`` does not
exist at the pin; state tests live beside the code). Durability is proven
against a temporary directory ONLY -- any real deployment path is a separate
operator/infra decision (P2-9) and is never asserted here.
"""

import inspect
import json
import tempfile
import threading
import unittest
from pathlib import Path

import core_store
from core_store import (
    BACKUP_CONFIGURED,
    BACKUP_UNFULFILLED,
    OUTCOME_APPENDED,
    OUTCOME_CONFLICT,
    OUTCOME_REDELIVERY,
    CoreError,
    CoreStore,
)


def _payload(tag: str, value: int = 1) -> dict:
    return {"kind": "package.revision", "tag": tag, "value": value}


class CoreStoreTestCase(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "core"
        self.store = CoreStore(self.root)

    def tearDown(self):
        self.temporary.cleanup()

    # --- requirement 1: append-only, records freeze, supersession appended --

    def test_record_is_frozen_after_append(self):
        payload = _payload("freeze")
        first = self.store.append(payload)
        self.assertEqual(first["outcome"], OUTCOME_APPENDED)
        stored = self.store.get(first["identity"])
        before = (self.store.records_dir / f"{first['identity']}.json").read_bytes()
        # A later re-delivery and a conflicting attempt never mutate storage.
        self.store.append(dict(payload))
        self.store.append(_payload("freeze", value=2), identity=first["identity"])
        after = (self.store.records_dir / f"{first['identity']}.json").read_bytes()
        self.assertEqual(before, after)
        self.assertEqual(self.store.get(first["identity"]), stored)

    def test_supersession_appends_a_separate_record(self):
        first = self.store.append(_payload("rev1"))
        second = self.store.append(_payload("rev2"), supersedes=first["record_digest"])
        self.assertEqual(second["outcome"], OUTCOME_APPENDED)
        self.assertNotEqual(second["record_digest"], first["record_digest"])
        self.assertEqual(second["identity"], second["record_digest"])
        original = self.store.get(first["identity"])
        self.assertEqual(original["payload"]["tag"], "rev1")
        self.assertEqual(self.store.get_by_digest(second["record_digest"])["supersedes"],
                         first["record_digest"])
        self.assertIsNone(original["supersedes"])

    def test_supersedes_must_reference_a_stored_record(self):
        with self.assertRaises(CoreError) as caught:
            self.store.append(_payload("orphan"),
                              supersedes="ab" * 32)
        self.assertEqual(caught.exception.category, "invalid_input")

    def test_no_update_or_delete_api_exists(self):
        for forbidden in ("update", "delete", "remove", "replace", "mutate"):
            self.assertFalse(hasattr(self.store, forbidden), forbidden)

    # --- requirement 2: digest-keyed addressing + dedupe ---------------------

    def test_record_digest_is_sha256_of_canonical_payload(self):
        payload = _payload("digest")
        result = self.store.append(payload)
        expected = core_store.sha256_hex(core_store.canonical_json(payload))
        self.assertEqual(result["record_digest"], expected)
        self.assertEqual(result["identity"], expected)
        stored = self.store.get(result["record_digest"])
        self.assertIsNotNone(stored)
        self.assertEqual(stored["record_digest"], expected)

    def test_deduplication_by_digest(self):
        payload = _payload("dedupe")
        first = self.store.append(payload)
        second = self.store.append(dict(payload))
        self.assertEqual(second["outcome"], OUTCOME_REDELIVERY)
        self.assertFalse(second["appended"])
        self.assertEqual(len(self.store.iter_records()), 1)
        self.assertEqual(self.store.get_by_digest(first["record_digest"])["identity"],
                         first["identity"])

    def test_canonical_form_matches_frozen_4a_section_2_1(self):
        # sorted keys, compact separators, ensure_ascii, default=str.
        value = {"b": 1, "a": "x", "u": "\u00e5"}
        self.assertEqual(core_store.canonical_json(value),
                         json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=True, default=str))

    def test_prefixed_digest_inputs_are_normalized_fail_closed(self):
        payload = _payload("prefix")
        first = self.store.append(payload)
        prefixed = self.store.get_by_digest("sha256:" + first["record_digest"])
        self.assertIsNotNone(prefixed)
        for bad in ("AB" * 32, "sha256:sha256:" + first["record_digest"], "ab" * 31):
            with self.assertRaises(CoreError):
                core_store.normalize_digest_input(bad)
            with self.assertRaises(CoreError):
                self.store.get_by_digest(bad)

    # --- requirement 3: atomic insert-if-absent / CAS ------------------------

    def test_concurrent_first_writes_exactly_one_winner(self):
        barrier = threading.Barrier(2)
        results: list[dict] = []
        errors: list[Exception] = []
        payload_a = _payload("race", value=1)
        payload_b = _payload("race", value=2)

        def contender(candidate: dict) -> None:
            store = CoreStore(self.root)
            barrier.wait()
            try:
                results.append(store.append(candidate, identity="race-key"))
            except Exception as error:  # noqa: BLE001 - surfaced below
                errors.append(error)

        threads = [threading.Thread(target=contender, args=(p,))
                   for p in (payload_a, payload_b)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(30)
        self.assertEqual(errors, [])
        appended = [r for r in results if r["outcome"] == OUTCOME_APPENDED]
        losers = [r for r in results if r["outcome"] != OUTCOME_APPENDED]
        self.assertEqual(len(appended), 1)
        self.assertEqual(len(losers), 1)
        self.assertEqual(len(self.store.iter_records()), 1)
        winner = self.store.get("race-key")
        loser = losers[0]
        if winner["record_digest"] == loser["record_digest"]:
            self.assertEqual(loser["outcome"], OUTCOME_REDELIVERY)
        else:
            self.assertEqual(loser["outcome"], OUTCOME_CONFLICT)

    def test_loser_renders_re_delivery_on_same_payload(self):
        payload = _payload("same")
        first = self.store.append(payload, identity="idem")
        second = self.store.append(dict(payload), identity="idem")
        self.assertEqual(second["outcome"], OUTCOME_REDELIVERY)
        self.assertFalse(second["appended"])
        self.assertEqual(second["record_digest"], first["record_digest"])
        self.assertEqual(len(self.store.iter_records()), 1)

    def test_loser_renders_conflict_on_different_payload(self):
        first = self.store.append(_payload("clash", value=1), identity="clash")
        second = self.store.append(_payload("clash", value=2), identity="clash")
        self.assertEqual(second["outcome"], OUTCOME_CONFLICT)
        self.assertFalse(second["appended"])
        self.assertEqual(second["conflict"]["field"], "payload_digest")
        self.assertEqual(second["conflict"]["values"],
                         [first["record_digest"], second["record_digest"]])
        self.assertEqual(len(self.store.iter_records()), 1)

    def test_read_sees_no_partial_record_from_concurrent_writer(self):
        # A reader racing a first-writer must either see a fully verified
        # record or nothing -- never a partially written file.
        errors: list[Exception] = []

        def reader() -> None:
            store = CoreStore(self.root)
            for _ in range(200):
                try:
                    record = store.get("partial-race")
                except CoreError as error:
                    errors.append(error)
                    return
                if record is not None:
                    return

        def writer() -> None:
            store = CoreStore(self.root)
            for _ in range(50):
                store.append(_payload("partial"), identity="partial-race")
                try:
                    (self.store.records_dir / "partial-race.json").unlink()
                except PermissionError:
                    pass  # a reader holds the file open; the next pass retries

        writer_thread = threading.Thread(target=writer)
        reader_thread = threading.Thread(target=reader)
        writer_thread.start()
        reader_thread.start()
        writer_thread.join(30)
        reader_thread.join(30)
        self.assertEqual(errors, [])

    # --- requirement 4: conflict-not-merge rendering -------------------------

    def test_conflict_lists_both_values_and_never_merges(self):
        first = self.store.append(_payload("merge", value=1), identity="merge")
        second = self.store.append(_payload("merge", value=2), identity="merge")
        self.assertEqual(second["conflict"]["values"],
                         [first["record_digest"], second["record_digest"]])
        stored = self.store.get("merge")
        self.assertEqual(stored["record_digest"], first["record_digest"])
        # The conflicting payload is NOT stored anywhere under the identity.
        self.assertIsNone(self.store.get("merge-conflict"))

    def test_tampered_record_is_never_served(self):
        first = self.store.append(_payload("tamper"), identity="tamper")
        path = self.store.records_dir / f"{first['identity']}.json"
        envelope = json.loads(path.read_text(encoding="utf-8"))
        envelope["payload"]["value"] = 999  # in-place mutation attempt
        path.write_text(json.dumps(envelope), encoding="utf-8")
        with self.assertRaises(CoreError) as caught:
            self.store.get("tamper")
        self.assertEqual(caught.exception.category, "integrity_error")
        with self.assertRaises(CoreError):
            self.store.verify()

    # --- requirement 5: durable location + declared-open backup (P2-9) ------

    def test_backup_hook_is_declared_but_unfulfilled_by_default(self):
        store = CoreStore(self.root / "plain")
        self.assertEqual(store.backup_status, BACKUP_UNFULFILLED)
        self.assertIsNone(getattr(store, "_backup", None))
        # The gap stays open even after successful appends: no backup path,
        # policy, or copy is silently invented by the store.
        store.append(_payload("nobackup"))
        self.assertEqual(store.backup_status, BACKUP_UNFULFILLED)
        self.assertEqual(sorted(p.name for p in store.root.iterdir()), ["records"])

    def test_backup_may_be_injected_and_is_called_on_first_append(self):
        seen: list[tuple[Path, dict]] = []
        store = CoreStore(self.root / "hooked",
                          backup=lambda path, envelope: seen.append((path, envelope)))
        self.assertEqual(store.backup_status, BACKUP_CONFIGURED)
        result = store.append(_payload("backup"))
        self.assertEqual(len(seen), 1)
        self.assertEqual(Path(seen[0][0]).name, f"{result['identity']}.json")
        self.assertEqual(seen[0][1]["record_digest"], result["record_digest"])
        # Re-delivery does not invoke the hook (nothing was appended).
        store.append(_payload("backup"))
        self.assertEqual(len(seen), 1)

    def test_store_rejects_backup_hook_that_is_not_callable(self):
        with self.assertRaises(CoreError):
            CoreStore(self.root / "badhook", backup="not-callable")  # type: ignore[arg-type]

    def test_root_is_injectable_and_records_survive_store_reopen(self):
        payload = _payload("durable")
        first = CoreStore(self.root).append(payload)
        reopened = CoreStore(self.root)
        stored = reopened.get(first["identity"])
        self.assertIsNotNone(stored)
        self.assertEqual(stored["payload"], payload)
        self.assertEqual(reopened.verify(), 1)

    def test_store_never_derives_a_default_root(self):
        # The store never derives a root by itself: root is a required
        # constructor argument with no default, and the module declares no
        # default-root constant (P2-9 stays an operator decision).
        signature = inspect.signature(CoreStore.__init__)
        self.assertIn("root", signature.parameters)
        self.assertIs(signature.parameters["root"].default, inspect.Parameter.empty)
        source = Path(core_store.__file__).read_text(encoding="utf-8")
        for forbidden in ("DEFAULT_ROOT", "DEFAULT_CORE", "gettempdir",
                          "LOCALAPPDATA"):
            self.assertNotIn(forbidden, source, forbidden)

    # --- requirement 6: GitHub issues = reference only -----------------------

    def test_issue_ref_is_carried_verbatim_as_a_reference(self):
        result = self.store.append(_payload("ref"), issue_ref="rian010194/cortxt#609")
        stored = self.store.get(result["identity"])
        self.assertEqual(stored["issue_ref"], "rian010194/cortxt#609")

    def test_issue_ref_is_optional(self):
        result = self.store.append(_payload("noref"))
        self.assertIsNone(self.store.get(result["identity"])["issue_ref"])

    def test_issue_ref_is_never_resolved_or_synced(self):
        # No GitHub or network capability exists in the module (ADR-018
        # unchanged): reference, not reconciliation.
        source = Path(core_store.__file__).read_text(encoding="utf-8")
        self.assertNotRegex(source, r"import requests|import urllib|import http")
        self.assertNotRegex(source, r"github\.com|api\.github\.com|subprocess")
        for forbidden in ("sync", "reconcile"):
            self.assertFalse(any(name.startswith(forbidden)
                                 for name in dir(self.store)), forbidden)

    def test_filesystem_looking_issue_refs_are_rejected(self):
        for bad in ("/etc/passwd", "../escape", "C:/temp/x", "back\\slash",
                    "x" * 129, ""):
            with self.assertRaises(CoreError):
                self.store.append(_payload("badref"), issue_ref=bad)

    # --- fail-closed validation behaviour ------------------------------------

    def test_payload_must_be_a_bounded_json_object(self):
        with self.assertRaises(CoreError):
            self.store.append(["not", "an", "object"])
        with self.assertRaises(CoreError):
            self.store.append({"deep": [{"nested": float("nan")}]})
        with self.assertRaises(CoreError):
            self.store.append({"too_long": "x" * (core_store.MAX_TEXT_LENGTH + 1)})

    def test_identity_must_be_a_bounded_safe_token(self):
        with self.assertRaises(CoreError):
            self.store.append(_payload("bad"), identity="../escape")
        with self.assertRaises(CoreError):
            self.store.append(_payload("bad"), identity="UPPER")
        with self.assertRaises(CoreError):
            self.store.append(_payload("bad"), identity="x" * 129)

    def test_unsafe_roots_are_rejected(self):
        with self.assertRaises(CoreError) as caught:
            CoreStore(self.root.parent / ".." / "escape")
        self.assertIn(caught.exception.category, {"unsafe_path", "invalid_input"})

    def test_error_shape_carries_category_and_exit_code(self):
        try:
            core_store.validate_identity("../bad")
        except CoreError as error:
            self.assertEqual(error.category, "invalid_input")
            self.assertEqual(error.exit_code, 3)


if __name__ == "__main__":
    unittest.main()
