"""Static config for Agent Runtime's read-only research profile.

Phase 2 v0.1: single-file read only. Phase 5: adds multi-document long-context
tools (context_store-backed range slicing) — see runtime/tools/research_tools.py.
"""

RESEARCH_PROFILE = {
    "profile_id": "research-v0.2",
    "allowed_tools": ["read_fixture_file", "list_fixture_documents", "read_fixture_file_sliced"],
    "workflow": "vertical-01-ai-act/classify",
}
