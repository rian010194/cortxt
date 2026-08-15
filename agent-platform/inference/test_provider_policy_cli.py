import json
import subprocess
import sys
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
CLI = HERE / "provider_policy_cli.py"
FIXTURES = HERE / "fixtures"


def invoke(*args: str, stdin: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        input=stdin,
        text=True,
        capture_output=True,
        check=False,
        cwd=HERE,
        timeout=10,
    )


class ProviderPolicyCliTests(unittest.TestCase):
    def test_synthetic_l0_is_allowed(self):
        result = invoke(str(FIXTURES / "l0-inferx-like.json"))
        self.assertEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout)["reasons"], ["requirements_satisfied"])

    def test_same_synthetic_provider_is_denied_at_l2(self):
        result = invoke(str(FIXTURES / "l2-inferx-like.json"))
        self.assertEqual(result.returncode, 2)
        payload = json.loads(result.stdout)
        self.assertFalse(payload["allowed"])
        self.assertEqual(payload["provider_id"], "synthetic-inferx")
        self.assertIn("independent_assurance_not_completed", payload["reasons"])

    def test_complete_l2_is_allowed(self):
        result = invoke(str(FIXTURES / "l2-complete.json"))
        self.assertEqual(result.returncode, 0)
        self.assertTrue(json.loads(result.stdout)["allowed"])

    def test_stdin_and_stable_compact_output(self):
        request = '{"provider_evidence":{"provider_id":"p","approved":true},"data_class":"L0"}'
        result = invoke(stdin=request)
        self.assertEqual(
            result.stdout,
            '{"allowed":true,"data_class":"L0","provider_id":"p","reasons":["requirements_satisfied"]}\n',
        )

    def test_invalid_json_has_no_traceback(self):
        result = invoke(stdin="{")
        self.assertEqual(result.returncode, 3)
        self.assertEqual(json.loads(result.stdout), {"error": "invalid_json"})
        self.assertEqual(result.stderr, "")

    def test_deeply_nested_json_has_no_traceback(self):
        # sys.getrecursionlimit() defaults to 1000; 2000 levels stopped reliably
        # tripping json.loads's RecursionError on Python 3.12 (see #131), so use
        # a depth with real headroom over the limit instead of guessing again.
        depth = sys.getrecursionlimit() * 3
        result = invoke(stdin="[" * depth + "]" * depth)
        self.assertEqual(result.returncode, 3)
        self.assertEqual(json.loads(result.stdout), {"error": "invalid_json"})
        self.assertEqual(result.stderr, "")

    def test_invalid_shape_has_deterministic_error(self):
        result = invoke(stdin='{"data_class":"L0"}')
        self.assertEqual(result.returncode, 3)
        self.assertEqual(json.loads(result.stdout), {"error": "invalid_request_shape"})

    def test_wrong_typed_truthy_evidence_is_denied(self):
        request = json.dumps({
            "data_class": "L1",
            "provider_evidence": {
                "provider_id": "p", "approved": "true",
                "zero_data_retention": "true", "encryption": "true"
            },
        })
        result = invoke(stdin=request)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stdout)["reasons"], [
            "missing_approved", "missing_zero_data_retention", "missing_encryption"
        ])

    def test_unknown_assurance_status_is_denied_not_malformed(self):
        request = (FIXTURES / "l2-complete.json").read_text(encoding="utf-8").replace(
            '"completed"', '"unknown"'
        )
        result = invoke(stdin=request)
        self.assertEqual(result.returncode, 2)
        self.assertIn("independent_assurance_not_completed", json.loads(result.stdout)["reasons"])


if __name__ == "__main__":
    unittest.main()
