import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


HERE = Path(__file__).parent
CLI = HERE / "synthetic_journey.py"
SCENARIO = HERE / "fixtures" / "t1-synthetic-journey.json"


class SyntheticJourneyTests(unittest.TestCase):
    def run_cli(self, *arguments):
        return subprocess.run([sys.executable, str(CLI), *map(str, arguments)],
                              capture_output=True, text=True, check=False)

    def test_separate_process_interrupt_resume_result_and_verification(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "evidence"
            started = self.run_cli("start", "--scenario", SCENARIO, "--output", output)
            self.assertEqual(started.returncode, 0, started.stderr)
            self.assertFalse(json.loads(started.stdout)["terminal"])

            resumed = self.run_cli("resume", "--output", output)
            self.assertEqual(resumed.returncode, 0, resumed.stderr)
            self.assertTrue(json.loads(resumed.stdout)["terminal"])

            verified = self.run_cli("verify", "--output", output)
            self.assertEqual(verified.returncode, 0, verified.stderr)
            report = json.loads(verified.stdout)
            self.assertEqual(report["status"], "succeeded")
            self.assertTrue(report["budget_verified"])
            self.assertTrue(report["evidence_verified"])
            self.assertTrue(report["integrity_verified"])
            self.assertEqual(report["event_types"], ["run.created", "run.started",
                             "run.interrupted", "run.resumed", "run.result"])

    def test_resume_is_single_use_and_tampering_fails_verification(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "evidence"
            self.assertEqual(self.run_cli("start", "--scenario", SCENARIO,
                                         "--output", output).returncode, 0)
            self.assertEqual(self.run_cli("resume", "--output", output).returncode, 0)
            self.assertNotEqual(self.run_cli("resume", "--output", output).returncode, 0)
            result = output / "synthetic-result.json"
            result.write_text('{"tampered":true}\n', encoding="utf-8")
            rejected = self.run_cli("verify", "--output", output)
            self.assertEqual(rejected.returncode, 1)
            self.assertIn("evidence hash does not match", rejected.stderr)

    def test_over_budget_scenario_fails_before_run_creation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            scenario = json.loads(SCENARIO.read_text(encoding="utf-8"))
            scenario["actual_cost_usd"] = "0.01"
            scenario_path = root / "scenario.json"
            scenario_path.write_text(json.dumps(scenario), encoding="utf-8")
            rejected = self.run_cli("start", "--scenario", scenario_path,
                                    "--output", root / "evidence")
            self.assertEqual(rejected.returncode, 1)
            self.assertIn("exceeds its budget", rejected.stderr)
            self.assertFalse((root / "evidence").exists())


if __name__ == "__main__":
    unittest.main()
