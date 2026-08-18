# agent-platform/tests/runtime/test_research_profile.py
from runtime.tools.gate import DataClassGate, ToolGate
from runtime.tools.research_tools import list_fixture_documents, read_fixture_file_sliced
from context_store.store import ContextReference


def test_list_fixture_documents_returns_all_docs_in_a_set(tmp_path):
    doc_dir = tmp_path / "doc-set-1"
    doc_dir.mkdir()
    (doc_dir / "doc-a.txt").write_text("alpha content", encoding="utf-8")
    (doc_dir / "doc-b.txt").write_text("beta content", encoding="utf-8")

    gate = ToolGate(allowed_roots=[tmp_path])
    docs = list_fixture_documents(gate, str(doc_dir))
    assert set(docs) == {"doc-a.txt", "doc-b.txt"}


def test_read_fixture_file_sliced_returns_only_the_requested_range(tmp_path):
    doc_dir = tmp_path / "doc-set-1"
    doc_dir.mkdir()
    (doc_dir / "doc-a.txt").write_text("0123456789", encoding="utf-8")

    ref = ContextReference(source="document_set", locator=str(doc_dir / "doc-a.txt"),
                            range=(2, 5), data_class="internal")
    tool_gate = ToolGate(allowed_roots=[tmp_path])
    data_class_gate = DataClassGate(allowed_data_classes={"internal"})
    content = read_fixture_file_sliced(tool_gate, data_class_gate, ref)
    assert content == "234"


def test_read_fixture_file_sliced_rejects_path_outside_allowed_roots(tmp_path):
    import pytest
    from runtime.tools.gate import ToolAdmissionError

    outside = tmp_path.parent / "not-allowed.txt"
    outside.write_text("secret", encoding="utf-8")
    ref = ContextReference(source="document_set", locator=str(outside),
                            range=(0, 6), data_class="internal")
    tool_gate = ToolGate(allowed_roots=[tmp_path])
    data_class_gate = DataClassGate(allowed_data_classes={"internal"})
    with pytest.raises(ToolAdmissionError):
        read_fixture_file_sliced(tool_gate, data_class_gate, ref)
