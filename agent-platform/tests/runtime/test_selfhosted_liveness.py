from runtime.selfhosted_liveness import LivenessSample, parse_liveness

VLLM_METRICS_FIXTURE = """
# HELP vllm:num_requests_running Number of requests currently running on GPU.
vllm:num_requests_running{model_name="qwen3-8b-instruct"} 1.0
# HELP vllm:num_requests_waiting Number of requests waiting to be processed.
vllm:num_requests_waiting{model_name="qwen3-8b-instruct"} 0.0
# HELP vllm:gpu_cache_usage_perc GPU KV-cache usage.
vllm:gpu_cache_usage_perc{model_name="qwen3-8b-instruct"} 0.42
"""

def test_parse_liveness_healthy_with_metrics():
    sample = parse_liveness(health_ok=True, metrics_text=VLLM_METRICS_FIXTURE)
    assert sample.alive is True
    assert sample.queue_depth == 0
    assert sample.vram_pct == 42.0

def test_parse_liveness_health_down_ignores_metrics():
    sample = parse_liveness(health_ok=False, metrics_text=VLLM_METRICS_FIXTURE)
    assert sample.alive is False
    assert sample.vram_pct is None  # degraderat, inte fabricerat

def test_parse_liveness_malformed_metrics_degrades_not_crashes():
    sample = parse_liveness(health_ok=True, metrics_text="not prometheus format")
    assert sample.alive is True
    assert sample.vram_pct is None
    assert sample.queue_depth is None
