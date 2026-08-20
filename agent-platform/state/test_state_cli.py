import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import ledger
from subprocess_windows import no_window_kwargs

HERE = Path(__file__).parent
CLI = HERE / "state_cli.py"


class StateCliTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.store = self.root / "state"
        self.store.mkdir()
        self.policy = self.root / "evidence.json"
        self.payload = self.root / "payload.json"
        self.policy.write_text(json.dumps({"provider_id": "synthetic-provider", "approved": True}),
                               encoding="utf-8")
        self.payload.write_text('{"status":"running"}', encoding="utf-8")

    def tearDown(self):
        self.temporary.cleanup()

    def run_cli(self, *arguments):
        return subprocess.run([sys.executable, str(CLI), *map(str, arguments)],
                              text=True, capture_output=True, check=False, **no_window_kwargs())

    def create(self):
        result = self.run_cli("create", "--store", self.store, "--task-id", "synthetic-task-107",
                              "--data-class", "L0", "--workflow", "foundation.state/v1", "--max-cost-usd", "0",
                              "--provider-evidence-file", self.policy)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_offline_create_append_show_round_trip_and_hash_chain(self):
        created = self.create()
        run_id = created["run_id"]
        self.assertRegex(run_id, r"^run_[0-9a-f]{32}$")
        self.assertEqual(created["schema_version"], 1)
        self.assertEqual(created["events"][0]["payload"]["task_id"], "synthetic-task-107")
        self.assertEqual(created["events"][0]["payload"]["data_class"], "L0")
        self.assertEqual(created["events"][0]["payload"]["budget"], {"max_cost_usd": "0"})
        appended = self.run_cli("append", "--store", self.store, "--run-id", run_id,
                                "--expected-sequence", "0", "--event-type", "run.started",
                                "--payload-file", self.payload)
        self.assertEqual(appended.returncode, 0, appended.stderr)
        shown = self.run_cli("show", "--store", self.store, "--run-id", run_id)
        self.assertEqual(shown.returncode, 0, shown.stderr)
        ledger = json.loads(shown.stdout)
        self.assertEqual(ledger, json.loads(appended.stdout))
        self.assertEqual(len(ledger["events"]), 2)
        self.assertTrue(all(event["timestamp"].endswith("Z") for event in ledger["events"]))
        for index, event in enumerate(ledger["events"]):
            unsigned = {key: value for key, value in event.items() if key != "hash"}
            encoded = json.dumps(unsigned, ensure_ascii=False, allow_nan=False,
                                 sort_keys=True, separators=(",", ":")).encode()
            self.assertEqual(event["hash"], hashlib.sha256(encoded).hexdigest())
            if index:
                self.assertEqual(event["previous_hash"], ledger["events"][index - 1]["hash"])

    def test_sequence_conflict_does_not_modify_ledger(self):
        ledger = self.create()
        path = self.store / ledger["run_id"] / "ledger.json"
        before = path.read_bytes()
        result = self.run_cli("append", "--store", self.store, "--run-id", ledger["run_id"],
                              "--expected-sequence", "9", "--event-type", "run.started",
                              "--payload-file", self.payload)
        self.assertEqual(result.returncode, 5)
        self.assertEqual(json.loads(result.stderr)["error"]["category"], "sequence_conflict")
        self.assertEqual(path.read_bytes(), before)
        self.assertNotIn("Traceback", result.stderr)

    def test_tampering_fails_closed(self):
        ledger = self.create()
        path = self.store / ledger["run_id"] / "ledger.json"
        persisted = json.loads(path.read_text(encoding="utf-8"))
        persisted["events"][0]["payload"]["workflow"] = "tampered"
        path.write_text(json.dumps(persisted), encoding="utf-8")
        result = self.run_cli("show", "--store", self.store, "--run-id", ledger["run_id"])
        self.assertEqual(result.returncode, 6)
        self.assertEqual(json.loads(result.stderr)["error"]["category"], "integrity_error")

    def test_denied_policy_and_invalid_budgets_fail_closed(self):
        denied = {"provider_id": "synthetic-provider", "approved": False,
                  "allowed": True, "reasons": ["forged"]}
        self.policy.write_text(json.dumps(denied), encoding="utf-8")
        denied_result = self.run_cli("create", "--store", self.store, "--task-id", "x",
                                     "--data-class", "L0", "--workflow", "x", "--max-cost-usd", "1",
                                     "--provider-evidence-file", self.policy)
        self.assertEqual(denied_result.returncode, 3)
        self.policy.write_text(json.dumps({"provider_id": "synthetic-provider", "approved": True}),
                               encoding="utf-8")
        mismatch = self.run_cli("create", "--store", self.store, "--task-id", "x",
                                "--data-class", "L3", "--workflow", "x", "--max-cost-usd", "1",
                                "--provider-evidence-file", self.policy)
        self.assertEqual(mismatch.returncode, 3)
        for invalid in ("-1", "nan", "inf", "unknown"):
            result = self.run_cli("create", "--store", self.store, "--task-id", "x",
                                  "--data-class", "L0", "--workflow", "x", "--max-cost-usd", invalid,
                                  "--provider-evidence-file", self.policy)
            self.assertEqual(result.returncode, 3)

    def test_traversal_and_symlink_are_rejected(self):
        result = self.run_cli("show", "--store", self.store, "--run-id", "../escape")
        self.assertEqual(result.returncode, 3)
        if hasattr(os, "symlink"):
            link = self.root / "policy-link.json"
            try:
                os.symlink(self.policy, link)
            except OSError:
                self.skipTest("symlinks unavailable")
            result = self.run_cli("create", "--store", self.store, "--task-id", "x",
                                  "--data-class", "L0", "--workflow", "x", "--max-cost-usd", "0",
                                  "--provider-evidence-file", link)
            self.assertEqual(result.returncode, 3)
            self.assertEqual(json.loads(result.stderr)["error"]["category"], "unsafe_path")

    def test_detected_symlink_component_is_rejected_on_every_platform(self):
        with mock.patch.object(Path, "exists", return_value=True), \
             mock.patch.object(Path, "is_symlink", return_value=True):
            with self.assertRaises(ledger.LedgerError) as caught:
                ledger.safe_store(str(self.store))
        self.assertEqual(caught.exception.category, "unsafe_path")

    def test_detected_windows_reparse_component_is_rejected(self):
        with mock.patch.object(Path, "exists", return_value=True), \
             mock.patch.object(Path, "is_symlink", return_value=False), \
             mock.patch.object(ledger, "_is_reparse", return_value=True):
            with self.assertRaises(ledger.LedgerError) as caught:
                ledger.safe_store(str(self.store))
        self.assertEqual(caught.exception.category, "unsafe_path")

    def test_decimal_budget_is_exact_canonical_and_precision_is_bounded(self):
        result = self.run_cli("create", "--store", self.store, "--task-id", "x",
                              "--data-class", "L0", "--workflow", "x",
                              "--max-cost-usd", "0001.230000",
                              "--provider-evidence-file", self.policy)
        self.assertEqual(result.returncode, 0, result.stderr)
        value = json.loads(result.stdout)["events"][0]["payload"]["budget"]["max_cost_usd"]
        self.assertEqual(value, "1.23")
        too_precise = self.run_cli("create", "--store", self.store, "--task-id", "x",
                                   "--data-class", "L0", "--workflow", "x",
                                   "--max-cost-usd", "0.1234567",
                                   "--provider-evidence-file", self.policy)
        self.assertEqual(too_precise.returncode, 3)

    def test_ledger_cannot_be_transplanted_between_run_directories(self):
        first = self.create()
        second = self.create()
        source = self.store / first["run_id"] / "ledger.json"
        destination = self.store / second["run_id"] / "ledger.json"
        transplanted = json.loads(source.read_text(encoding="utf-8"))
        transplanted["run_id"] = second["run_id"]
        destination.write_text(json.dumps(transplanted), encoding="utf-8")
        result = self.run_cli("show", "--store", self.store, "--run-id", second["run_id"])
        self.assertEqual(result.returncode, 6)

    def test_malformed_persistent_types_timestamp_event_and_nonfinite_json_fail(self):
        mutations = (
            lambda state: state.__setitem__("schema_version", True),
            lambda state: state["events"][0].__setitem__("sequence", False),
            lambda state: state["events"][0].__setitem__("event_type", "INVALID TYPE"),
            lambda state: state["events"][0].__setitem__("timestamp", "2026-01-01T00:00:00+01:00"),
        )
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                created = self.create()
                path = self.store / created["run_id"] / "ledger.json"
                persisted = json.loads(path.read_text(encoding="utf-8"))
                mutate(persisted)
                path.write_text(json.dumps(persisted), encoding="utf-8")
                result = self.run_cli("show", "--store", self.store, "--run-id", created["run_id"])
                self.assertEqual(result.returncode, 6)
        created = self.create()
        path = self.store / created["run_id"] / "ledger.json"
        path.write_text('{"schema_version":NaN}', encoding="utf-8")
        self.assertEqual(self.run_cli("show", "--store", self.store,
                                     "--run-id", created["run_id"]).returncode, 6)

    def test_deep_payload_is_rejected_and_persistent_lock_file_is_recoverable(self):
        value = "leaf"
        for _ in range(40):
            value = [value]
        self.payload.write_text(json.dumps(value), encoding="utf-8")
        created = self.create()
        rejected = self.run_cli("append", "--store", self.store, "--run-id", created["run_id"],
                                "--expected-sequence", "0", "--event-type", "run.started",
                                "--payload-file", self.payload)
        self.assertEqual(rejected.returncode, 3)
        (self.store / created["run_id"] / ".append.lock").write_text("stale", encoding="ascii")
        self.payload.write_text('{"status":"running"}', encoding="utf-8")
        recovered = self.run_cli("append", "--store", self.store, "--run-id", created["run_id"],
                                 "--expected-sequence", "0", "--event-type", "run.started",
                                 "--payload-file", self.payload)
        self.assertEqual(recovered.returncode, 0, recovered.stderr)

    def test_usage_and_missing_run_are_deterministic_json_without_traceback(self):
        usage = self.run_cli("create")
        self.assertEqual(usage.returncode, 2)
        self.assertEqual(json.loads(usage.stderr)["error"]["category"], "usage_error")
        missing = self.run_cli("show", "--store", self.store,
                               "--run-id", "run_" + "0" * 32)
        self.assertEqual(missing.returncode, 4)
        self.assertEqual(json.loads(missing.stderr)["error"]["category"], "not_found")
        self.assertNotIn("Traceback", usage.stderr + missing.stderr)


if __name__ == "__main__":
    unittest.main()
