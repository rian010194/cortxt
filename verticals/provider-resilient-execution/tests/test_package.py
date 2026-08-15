import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "evals" / "synthetic"


class PackageTests(unittest.TestCase):
    def setUp(self):
        self.cases = [json.loads(path.read_text(encoding="utf-8")) for path in sorted(FIXTURES.glob("*.json"))]

    def test_exact_fixture_inventory(self):
        self.assertEqual([case["case_id"] for case in self.cases], [
            "model-404", "policy-denied-fallback", "rate-limited",
            "return-channel-stalled", "success", "timeout"
        ])

    def test_every_case_has_deterministic_expected_result(self):
        for case in self.cases:
            with self.subTest(case=case["case_id"]):
                self.assertIn(case["expected"]["status"], {"succeeded", "failed", "blocked"})
                self.assertEqual(case["expected"]["attempts"], len(case["events"]))
                self.assertLessEqual(case["expected"]["attempts"], case["input"]["max_attempts_total"])

    def test_selected_routes_are_policy_eligible(self):
        for case in self.cases:
            selected = case["expected"]["selected_route_id"]
            if selected is not None:
                route = next(route for route in case["input"]["routes"] if route["route_id"] == selected)
                self.assertIs(route["policy_eligible"], True)

    def test_policy_denied_fallback_blocks_without_attempt(self):
        case = next(case for case in self.cases if case["case_id"] == "policy-denied-fallback")
        self.assertEqual(case["expected"]["terminal_reason"], "no_eligible_fallback")
        self.assertEqual(case["expected"]["attempts"], 1)
        self.assertIs(case["input"]["routes"][1]["policy_eligible"], False)

    def test_fixture_inputs_match_request_contract_shape(self):
        required = {"task_id", "data_class", "idempotency", "max_attempts_total",
                    "per_attempt_timeout_ms", "routes"}
        route_required = {"route_id", "provider", "model", "policy_eligible"}
        for case in self.cases:
            with self.subTest(case=case["case_id"]):
                self.assertEqual(set(case["input"]), required)
                self.assertGreaterEqual(len(case["input"]["routes"]), 1)
                for route in case["input"]["routes"]:
                    self.assertEqual(set(route), route_required)
                    self.assertIs(type(route["policy_eligible"]), bool)

    def test_schema_documents_parse_as_json(self):
        for path in sorted((ROOT / "schemas").glob("*.json")):
            with self.subTest(path=path.name):
                document = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(document["$schema"], "https://json-schema.org/draft/2020-12/schema")
                self.assertFalse(document["additionalProperties"])


if __name__ == "__main__":
    unittest.main()
