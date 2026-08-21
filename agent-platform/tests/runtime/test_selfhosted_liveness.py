from runtime.selfhosted_liveness import LivenessSample, _LivenessHttpProbe, parse_liveness

VLLM_METRICS_FIXTURE = """
# HELP vllm:num_requests_running Number of requests in model execution batches.
vllm:num_requests_running{engine="0",model_name="Qwen/Qwen3-8B-AWQ"} 1.0
# HELP vllm:num_requests_waiting Number of requests waiting to be processed.
vllm:num_requests_waiting{engine="0",model_name="Qwen/Qwen3-8B-AWQ"} 0.0
# HELP vllm:num_requests_waiting_by_reason Number of waiting requests by reason.
vllm:num_requests_waiting_by_reason{engine="0",model_name="Qwen/Qwen3-8B-AWQ",reason="capacity"} 0.0
# HELP vllm:kv_cache_usage_perc KV-cache usage. 1 means 100 percent usage.
vllm:kv_cache_usage_perc{engine="0",model_name="Qwen/Qwen3-8B-AWQ"} 0.42
"""
# Fixture captured verbatim (metric names/labels) against a live vLLM 0.27.1
# instance during Phase B provisioning, 2026-08-17 -- vLLM's real metric name is
# `kv_cache_usage_perc`, not `gpu_cache_usage_perc` as an earlier draft assumed.

def test_parse_liveness_healthy_with_metrics():
    sample = parse_liveness(health_ok=True, metrics_text=VLLM_METRICS_FIXTURE)
    assert sample.alive is True
    assert sample.queue_depth == 0
    assert sample.vram_pct == 42.0

def test_parse_liveness_health_down_ignores_metrics():
    sample = parse_liveness(health_ok=False, metrics_text=VLLM_METRICS_FIXTURE)
    assert sample.alive is False
    assert sample.vram_pct is None  # degraded, not fabricated

def test_parse_liveness_malformed_metrics_degrades_not_crashes():
    sample = parse_liveness(health_ok=True, metrics_text="not prometheus format")
    assert sample.alive is True
    assert sample.vram_pct is None
    assert sample.queue_depth is None


def test_probe_classifies_timeout(monkeypatch):
    def raise_timeout(*a, **kw):
        raise TimeoutError()
    monkeypatch.setattr("runtime.selfhosted_liveness.urllib.request.urlopen", raise_timeout)
    probe = _LivenessHttpProbe(base_url="https://example.invalid", timeout_ms=100)
    sample = probe.check()
    assert sample.alive is False

def test_probe_success_calls_parse_liveness(monkeypatch):
    monkeypatch.setattr(
        "runtime.selfhosted_liveness._LivenessHttpProbe._fetch_health", lambda self: True)
    monkeypatch.setattr(
        "runtime.selfhosted_liveness._LivenessHttpProbe._fetch_metrics",
        lambda self: VLLM_METRICS_FIXTURE)
    probe = _LivenessHttpProbe(base_url="https://example.invalid", timeout_ms=1000)
    sample = probe.check()
    assert sample.alive is True
    assert sample.vram_pct == 42.0


def test_probe_sends_bearer_auth_header_from_env(monkeypatch):
    # Phase 7's real Vast.ai deployment fronts vLLM with a Caddy proxy requiring
    # Authorization: Bearer <token> (verified live, 2026-08-17) -- the probe
    # must send it, same convention as TextInferencePort/EmbeddingPort.
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def read(self):
            return b"ok"

    def fake_urlopen(request, timeout=None):
        captured["headers"] = dict(request.header_items())
        return FakeResponse()

    monkeypatch.setattr("runtime.selfhosted_liveness.urllib.request.urlopen", fake_urlopen)
    monkeypatch.setenv("CORTXT_SELFHOSTED_API_KEY", "secret-token")
    probe = _LivenessHttpProbe(
        base_url="https://example.invalid", timeout_ms=1000,
        api_key_env="CORTXT_SELFHOSTED_API_KEY",
    )
    probe._fetch_health()
    assert captured["headers"].get("Authorization") == "Bearer secret-token"
