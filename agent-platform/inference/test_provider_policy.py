import unittest
from provider_policy import AssuranceStatus, ProviderEvidence, evaluate_provider

class ProviderPolicyTests(unittest.TestCase):
    def test_l0_allows_approved_provider(self):
        self.assertTrue(evaluate_provider("L0", ProviderEvidence("synthetic-inferx", True)).allowed)
    def test_inferx_like_evidence_denied_above_l0(self):
        evidence = ProviderEvidence("synthetic-inferx", True)
        self.assertFalse(evaluate_provider("L1", evidence).allowed)
        self.assertFalse(evaluate_provider("L2", evidence).allowed)
    def test_l1_requires_zdr_and_encryption(self):
        evidence = ProviderEvidence("provider-a", True, True)
        self.assertEqual(evaluate_provider("L1", evidence).reasons, ("missing_encryption",))
    def test_in_progress_assurance_is_insufficient(self):
        evidence = ProviderEvidence("provider-b", True, True, True, True, True, True, True,
                                    AssuranceStatus.IN_PROGRESS)
        self.assertEqual(evaluate_provider("L2", evidence).reasons,
                         ("independent_assurance_not_completed",))
    def test_complete_l2_evidence_is_allowed(self):
        evidence = ProviderEvidence("provider-b", True, True, True, True, True, True, True,
                                    AssuranceStatus.COMPLETED)
        self.assertTrue(evaluate_provider("L2", evidence).allowed)
    def test_l3_and_unknown_fail_closed(self):
        evidence = ProviderEvidence("provider-a", True)
        self.assertEqual(evaluate_provider("L3", evidence).reasons, ("l3_policy_not_defined",))
        self.assertEqual(evaluate_provider("L9", evidence).reasons, ("unknown_data_class",))
    def test_missing_evidence_fails_closed(self):
        self.assertEqual(evaluate_provider("L0", None).reasons, ("missing_provider_evidence",))
        self.assertEqual(evaluate_provider("L0", ProviderEvidence(" ", True)).reasons,
                         ("missing_provider_evidence",))
        self.assertEqual(evaluate_provider("L0", ProviderEvidence(None, True)).reasons,
                         ("missing_provider_evidence",))
    def test_truthy_unknown_values_fail_closed(self):
        evidence = ProviderEvidence("provider-a", "false", "unknown", "yes")
        self.assertEqual(evaluate_provider("L0", evidence).reasons, ("missing_approved",))
        self.assertEqual(evaluate_provider("L1", evidence).reasons,
                         ("missing_approved", "missing_zero_data_retention",
                          "missing_encryption"))

if __name__ == "__main__":
    unittest.main()


def test_vastai_selfhosted_route_allowed_at_l0():
    evidence = ProviderEvidence(provider_id="cortxt-selfhosted-vastai-qwen3-8b", approved=True)
    decision = evaluate_provider("L0", evidence)
    assert decision.allowed is True

def test_vastai_selfhosted_route_denied_at_l1_without_zdr():
    evidence = ProviderEvidence(
        provider_id="cortxt-selfhosted-vastai-qwen3-8b", approved=True,
        zero_data_retention=False,
    )
    decision = evaluate_provider("L1", evidence)
    assert decision.allowed is False
    assert "missing_zero_data_retention" in decision.reasons
