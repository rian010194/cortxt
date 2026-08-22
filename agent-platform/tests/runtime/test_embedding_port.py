"""EmbeddingPort: real-inference gate + provider-policy check, drop-in for EmbeddingFn.

No real network calls here (default CI); real_inference-marked coverage is separate.
"""
from __future__ import annotations

import pytest
from adapters.inference.budget_gate import BudgetExhausted, BudgetGate
from runtime.embedding_port import EmbeddingError, EmbeddingPort, configured_embedder


def _gate(tmp_path, max_calls):
    return BudgetGate(max_calls=max_calls, db_path=tmp_path / "spend.db")


def test_call_denied_by_provider_policy(tmp_path):
    port = EmbeddingPort(
        model="synthetic-embedding-model",
        budget_gate=_gate(tmp_path, max_calls=5),
        provider_evidence={"approved": False, "provider_id": "untrusted"},
        data_class="L2",
    )
    with pytest.raises(EmbeddingError) as exc:
        port("embed this")
    assert "policy" in str(exc.value).lower()


def test_call_blocked_by_budget_before_any_backend_call(tmp_path, monkeypatch):
    called = []
    monkeypatch.setattr(
        "runtime.embedding_port.EmbeddingPort._call_backend",
        lambda self, text: called.append(1) or [0.1, 0.2],
    )
    port = EmbeddingPort(
        model="synthetic-embedding-model",
        budget_gate=_gate(tmp_path, max_calls=0),
        provider_evidence={"approved": True, "provider_id": "synthetic-provider"},
        data_class="L0",
    )
    with pytest.raises(BudgetExhausted):
        port("embed this")
    assert called == []  # backend never reached


def test_call_success_returns_vector_from_backend(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "runtime.embedding_port.EmbeddingPort._call_backend",
        lambda self, text: [0.1, 0.2, 0.3],
    )
    port = EmbeddingPort(
        model="synthetic-embedding-model",
        budget_gate=_gate(tmp_path, max_calls=5),
        provider_evidence={"approved": True, "provider_id": "synthetic-provider"},
        data_class="L0",
    )
    result = port("embed this")
    assert result == [0.1, 0.2, 0.3]


def test_call_raises_when_backend_package_unavailable(tmp_path, monkeypatch):
    # Force the "package not installed" branch explicitly rather than relying on
    # cortxt_resilient_inference happening to be absent from this environment.
    monkeypatch.setattr("runtime.embedding_port._RI_AVAILABLE", False)
    port = EmbeddingPort(
        model="synthetic-embedding-model",
        budget_gate=_gate(tmp_path, max_calls=5),
        provider_evidence={"approved": True, "provider_id": "synthetic-provider"},
        data_class="L0",
    )
    with pytest.raises(EmbeddingError) as exc:
        port("embed this")
    assert "unavailable" in str(exc.value).lower()


def test_call_raises_when_backend_env_not_configured(tmp_path, monkeypatch):
    # Package present, but CORTXT_EMBEDDING_URL/API_KEY unset -- must fail closed
    # with a clear "not configured" error, not attempt a network call.
    monkeypatch.setattr("runtime.embedding_port._RI_AVAILABLE", True)
    monkeypatch.delenv("CORTXT_EMBEDDING_URL", raising=False)
    monkeypatch.delenv("CORTXT_EMBEDDING_API_KEY", raising=False)
    port = EmbeddingPort(
        model="synthetic-embedding-model",
        budget_gate=_gate(tmp_path, max_calls=5),
        provider_evidence={"approved": True, "provider_id": "synthetic-provider"},
        data_class="L0",
    )
    with pytest.raises(EmbeddingError) as exc:
        port("embed this")
    assert "not configured" in str(exc.value).lower()


def test_call_backend_builds_correct_request_and_parses_embedding_response(tmp_path, monkeypatch):
    monkeypatch.setattr("runtime.embedding_port._RI_AVAILABLE", True)
    monkeypatch.setenv("CORTXT_EMBEDDING_URL", "https://inference.example/m3/v1")
    monkeypatch.setenv("CORTXT_EMBEDDING_API_KEY", "test-key")

    captured = {}

    def fake_execute(request, adapters):
        captured["request"] = request
        captured["adapters"] = adapters
        return {
            "status": "succeeded",
            "response": {"embedding": [0.5, -0.5, 1.0]},
        }

    monkeypatch.setattr("runtime.embedding_port._resilient_execute", fake_execute)

    port = EmbeddingPort(
        model="Qwen/Qwen3-Embedding-0.6B",
        budget_gate=_gate(tmp_path, max_calls=5),
        provider_evidence={"approved": True, "provider_id": "synthetic-provider"},
        data_class="L0",
    )
    result = port("embed this system")

    assert result == [0.5, -0.5, 1.0]
    route = captured["request"]["routes"][0]
    assert route["base_url"] == "https://inference.example/m3/v1"
    assert route["model"] == "Qwen/Qwen3-Embedding-0.6B"
    assert route["api_key_env"] == "CORTXT_EMBEDDING_API_KEY"
    assert "l0-embedding" in captured["adapters"]
    assert captured["adapters"]["l0-embedding"].text == "embed this system"


def test_call_backend_raises_when_execute_does_not_succeed(tmp_path, monkeypatch):
    monkeypatch.setattr("runtime.embedding_port._RI_AVAILABLE", True)
    monkeypatch.setenv("CORTXT_EMBEDDING_URL", "https://inference.example/m3/v1")
    monkeypatch.setenv("CORTXT_EMBEDDING_API_KEY", "test-key")
    monkeypatch.setattr(
        "runtime.embedding_port._resilient_execute",
        lambda request, adapters: {"status": "blocked", "terminal_reason": "provider_unavailable"},
    )
    port = EmbeddingPort(
        model="m", budget_gate=_gate(tmp_path, max_calls=5),
        provider_evidence={"approved": True, "provider_id": "synthetic-provider"}, data_class="L0",
    )
    with pytest.raises(EmbeddingError) as exc:
        port("p")
    assert "did not succeed" in str(exc.value).lower()


def test_call_backend_raises_on_expected_dim_mismatch(tmp_path, monkeypatch):
    monkeypatch.setattr("runtime.embedding_port._RI_AVAILABLE", True)
    monkeypatch.setenv("CORTXT_EMBEDDING_URL", "https://inference.example/m3/v1")
    monkeypatch.setenv("CORTXT_EMBEDDING_API_KEY", "test-key")
    monkeypatch.setattr(
        "runtime.embedding_port._resilient_execute",
        lambda request, adapters: {"status": "succeeded", "response": {"embedding": [0.1, 0.2]}},
    )
    port = EmbeddingPort(
        model="m", budget_gate=_gate(tmp_path, max_calls=5),
        provider_evidence={"approved": True, "provider_id": "synthetic-provider"}, data_class="L0",
        expected_dim=1024,
    )
    with pytest.raises(EmbeddingError) as exc:
        port("p")
    assert "dim=2" in str(exc.value) and "1024" in str(exc.value)


def test_embedding_port_is_drop_in_compatible_with_geometric_embedder_surface(tmp_path, monkeypatch):
    """CandidatePathScore.embedder / GraphMetrics.semantic_closeness accept any
    Callable[[str], list[float]] -- an EmbeddingPort instance must satisfy that directly,
    with no adapter/wrapper glue, per the Phase 6 §27#10 decision doc's 'drop-in' claim."""
    from reasoning.geometric.metrics import GraphMetrics
    from reasoning.geometric.graph_space import ProblemSpace

    monkeypatch.setattr(
        "runtime.embedding_port.EmbeddingPort._call_backend",
        lambda self, text: [1.0, 0.0] if text == "a" else [0.0, 1.0],
    )
    port = EmbeddingPort(
        model="synthetic-embedding-model",
        budget_gate=_gate(tmp_path, max_calls=5),
        provider_evidence={"approved": True, "provider_id": "synthetic-provider"},
        data_class="L0",
    )
    space = ProblemSpace()
    closeness = GraphMetrics.semantic_closeness(space, "a", "b", embedder=port)
    assert closeness == pytest.approx(0.0)  # orthogonal vectors -> cosine 0


# -- configured_embedder: config-gated EmbeddingFn selection (ADR-035) ------- #


def _sentinel_embedder(text):
    return [0.0]


def _voyage_evidence():
    return {"approved": True, "provider_id": "voyage"}


def test_configured_embedder_returns_default_when_unconfigured(tmp_path, monkeypatch):
    monkeypatch.delenv("CORTXT_EMBEDDING_URL", raising=False)
    monkeypatch.delenv("CORTXT_EMBEDDING_API_KEY", raising=False)
    monkeypatch.delenv("CORTXT_EMBEDDING_MODEL", raising=False)
    result = configured_embedder(
        _gate(tmp_path, max_calls=5), _voyage_evidence(), default_embedder=_sentinel_embedder
    )
    assert result is _sentinel_embedder


def test_configured_embedder_returns_default_on_partial_config(tmp_path, monkeypatch):
    monkeypatch.setenv("CORTXT_EMBEDDING_URL", "https://api.voyageai.com/v1")
    monkeypatch.delenv("CORTXT_EMBEDDING_API_KEY", raising=False)
    monkeypatch.setenv("CORTXT_EMBEDDING_MODEL", "voyage-4-lite")
    result = configured_embedder(
        _gate(tmp_path, max_calls=5), _voyage_evidence(), default_embedder=_sentinel_embedder
    )
    assert result is _sentinel_embedder  # half-configured env never silently goes live


def test_configured_embedder_default_embedder_is_hash_embedding(tmp_path, monkeypatch):
    monkeypatch.delenv("CORTXT_EMBEDDING_URL", raising=False)
    monkeypatch.delenv("CORTXT_EMBEDDING_API_KEY", raising=False)
    monkeypatch.delenv("CORTXT_EMBEDDING_MODEL", raising=False)
    from reasoning.geometric.embeddings import hash_embedding

    result = configured_embedder(_gate(tmp_path, max_calls=5), _voyage_evidence())
    assert result is hash_embedding  # production default unchanged


def test_configured_embedder_builds_port_when_fully_configured(tmp_path, monkeypatch):
    monkeypatch.setenv("CORTXT_EMBEDDING_URL", "https://api.voyageai.com/v1")
    monkeypatch.setenv("CORTXT_EMBEDDING_API_KEY", "test-key")
    monkeypatch.setenv("CORTXT_EMBEDDING_MODEL", "voyage-4-lite")
    monkeypatch.setenv("CORTXT_EMBEDDING_DIM", "1024")
    gate = _gate(tmp_path, max_calls=5)
    port = configured_embedder(gate, _voyage_evidence(), data_class="L0")
    assert isinstance(port, EmbeddingPort)
    assert port._model == "voyage-4-lite"
    assert port._expected_dim == 1024
    assert port._base_url_env == "CORTXT_EMBEDDING_URL"
    assert port._api_key_env == "CORTXT_EMBEDDING_API_KEY"


def test_configured_embedder_ignores_unparsable_dim(tmp_path, monkeypatch):
    monkeypatch.setenv("CORTXT_EMBEDDING_URL", "https://api.voyageai.com/v1")
    monkeypatch.setenv("CORTXT_EMBEDDING_API_KEY", "test-key")
    monkeypatch.setenv("CORTXT_EMBEDDING_MODEL", "voyage-4-lite")
    monkeypatch.setenv("CORTXT_EMBEDDING_DIM", "not-a-number")
    port = configured_embedder(_gate(tmp_path, max_calls=5), _voyage_evidence())
    assert isinstance(port, EmbeddingPort)
    assert port._expected_dim is None
