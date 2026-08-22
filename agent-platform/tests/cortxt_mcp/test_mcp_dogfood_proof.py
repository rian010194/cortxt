"""External MCP stdio dogfood proof for issue #247."""
import pytest

from cortxt_mcp.mcp_dogfood_proof import ProofSubprocessUnavailable, main


def test_external_mcp_lifecycle_dogfood(tmp_path):
    try:
        assert main(tmp_path) == 0
    except ProofSubprocessUnavailable as error:
        pytest.skip(str(error))
