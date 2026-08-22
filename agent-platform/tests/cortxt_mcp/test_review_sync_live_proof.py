"""Network-free coverage for the issue #252 live review synchronization proof."""
import json
import subprocess

import pytest

from cortxt_mcp.mcp_dogfood_proof import ProofSubprocessUnavailable
from cortxt_mcp.review_sync_live_proof import _verify_final_labels, main


class FakeGh:
    def __init__(self):
        self.calls = []

    def __call__(self, args, **kwargs):
        self.calls.append(args)
        if args[2] == "view":
            value = {"state": "OPEN", "labels": [
                {"name": "workflow:in-progress"}, {"name": "proof-fixture"}]}
            return subprocess.CompletedProcess(args, 0, json.dumps(value), "")
        return subprocess.CompletedProcess(args, 0, "", "")


def test_external_mcp_review_sync_chain_is_network_free(tmp_path):
    fake = FakeGh()
    try:
        report = main(tmp_path, issue_ref="owner/repo#252", run_subprocess=fake)
    except ProofSubprocessUnavailable as error:
        pytest.skip(str(error))
    assert report["synced"] and not report["failed"]
    assert report["skipped"] == [{"review_submission_id": report["synced"][0],
                                  "reason": "already_synced"}]
    assert report["fixture_issue_ref"] == "owner/repo#252"
    assert report["final_labels"] == []
    assert len(fake.calls) == 2
    assert fake.calls[0] == ["gh", "issue", "view", "252", "--repo", "owner/repo",
                             "--json", "state,labels"]
    assert fake.calls[1] == ["gh", "issue", "edit", "252", "--repo", "owner/repo",
                             "--remove-label", "workflow:in-progress",
                             "--add-label", "workflow:review"]


def test_final_label_verification_uses_injected_runner():
    calls = []

    def fake(args, **kwargs):
        calls.append(args)
        value = {"state": "OPEN", "labels": [
            {"name": "proof-fixture"}, {"name": "workflow:review"}]}
        return subprocess.CompletedProcess(args, 0, json.dumps(value), "")

    assert _verify_final_labels("owner/repo#252", fake) == [
        "proof-fixture", "workflow:review"]
    assert len(calls) == 1
