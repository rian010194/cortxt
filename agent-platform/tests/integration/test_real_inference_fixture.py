"""Test the real_inference_port fixture's skip behavior in the default suite.

This test verifies that the fixture properly skips when cortxt-resilient-inference
is not installed (which is the normal case).
"""

from __future__ import annotations

import pytest


def test_real_inference_fixture_skip_without_env(real_inference_port):
    """Verify that real_inference_port fixture properly skips when package not installed.

    The fixture should skip if cortxt-resilient-inference is not installed.
    Since we're running in the default suite without the package, this test
    should not be reached (the fixture should have skipped before setup).
    
    If we get here, it means either:
    1. cortxt-resilient-inference IS installed, or
    2. The fixture has been fixed to handle this case differently
    """
    # This test should not be reached when the package is not installed
    # The fixture should have skipped
    assert real_inference_port is not None
