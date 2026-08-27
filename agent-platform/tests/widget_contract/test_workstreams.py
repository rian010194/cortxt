from widget_contract.workstreams import build_workstream_projection


def test_projection_only_exposes_evidence_and_decision_when_authoritative():
    issues = [{"number": 42, "title": "Reviewed package", "body": "## Outcome\nShip it\n## Evidence\nCI passed",
               "labels": [{"name": "workflow:review"}], "url": "https://example/42"},
              {"number": 41, "title": "No evidence", "body": "", "labels": [{"name": "workflow:review"}], "url": "https://example/41"}]
    model = build_workstream_projection("owner/repo", issues)
    assert model["synthetic"] is False
    assert model["workstreams"][0]["decision"]["action_id"] == "record-decision"
    assert model["workstreams"][0]["evidence"][0]["detail"] == "CI passed"
    assert model["workstreams"][1]["decision"] is None
    assert model["workstreams"][1]["evidence"] == []


def test_projection_fails_semantically_closed_for_ambiguous_workflow():
    issue = {"number": 7, "title": "Ambiguous", "body": "## Evidence\nPresent",
             "labels": [{"name": "workflow:review"}, {"name": "workflow:done"}], "url": "https://example/7"}
    item = build_workstream_projection("owner/repo", [issue])["workstreams"][0]
    assert item["workflow"] == "unknown"
    assert item["decision"] is None
