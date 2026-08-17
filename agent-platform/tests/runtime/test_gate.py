# agent-platform/tests/runtime/test_gate.py
import pytest

from runtime.tools.gate import DataClassGate, ToolAdmissionError


def test_data_class_gate_admits_allowed_class():
    gate = DataClassGate(allowed_data_classes={"internal", "L0"})
    gate.admit("rlm_context_read", "internal")  # does not raise


def test_data_class_gate_rejects_disallowed_class():
    gate = DataClassGate(allowed_data_classes={"internal"})
    with pytest.raises(ToolAdmissionError):
        gate.admit("rlm_context_read", "restricted")
