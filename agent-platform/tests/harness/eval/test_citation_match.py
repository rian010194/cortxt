# agent-platform/tests/harness/eval/test_citation_match.py
from harness.eval.citation_match import ExpectedFact, citation_match_v1


def test_passes_when_all_facts_present_and_correctly_cited():
    facts = [ExpectedFact(fact="the deadline is March 3rd", required_locator="doc-2.txt")]
    assert citation_match_v1(answer="Per doc-2.txt, the deadline is March 3rd.",
                              cited_locators={"doc-2.txt"}, expected_facts=facts) is True


def test_fails_when_fact_present_but_not_cited():
    facts = [ExpectedFact(fact="the deadline is March 3rd", required_locator="doc-2.txt")]
    assert citation_match_v1(answer="The deadline is March 3rd.",
                              cited_locators=set(), expected_facts=facts) is False


def test_fails_when_fact_missing_even_if_a_citation_exists():
    facts = [ExpectedFact(fact="the deadline is March 3rd", required_locator="doc-2.txt")]
    assert citation_match_v1(answer="See doc-2.txt for details.",
                              cited_locators={"doc-2.txt"}, expected_facts=facts) is False
