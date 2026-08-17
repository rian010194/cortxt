# Fas 7 — Egenhostad inference — implementationsplan (TDD)

Status: **PLAN v2 — KLAR (Task 1–8 implementerade och gröna).** Slutverifiering med
`PYTHONPATH= python -m pytest agent-platform/ -m "not real_inference and not docker_required" -q`
→ **366 passed, 3 skipped, 0 failed** (bas 348/3 + 18 nya tester från Task 1–8; 0 regressioner),
körda med Python312 på branch `spec/fas7-self-hosted-inference`. Task 1–8 committade var för sig
(se git-log). Fas B (Vast.ai-provisionering + vLLM-deploy + levande endpoint-test) är ej påbörjad —
görs separat efter pre-flight-checklistan nedan.

Bygger på GODKÄND spec
`docs/superpowers/specs/2026-08-17-fas7-self-hosted-inference-v01-design.md` (v7, Kimi-granskad
`GODKÄND MED ANMÄRKNINGAR`, commit `4a6b854`; P1 åtgärdad, kvantiseringsvalet slutgiltigt
beslutat — se spec Beslut 2; 4×P2 kvar som pre-flight-verifieringspunkter, ej blockerande för
Task 1–8). Operatören godkände 2026-08-17 gate 0, kostnadstaket (~10 USD, redan laddat på
operatörens Vast.ai-konto) och **auktoriserade explicit autonom exekvering av resten av Fas 7**,
inklusive att Claude tar kontroll över operatörens inloggade Vast.ai-webbläsarsession för
admin-steg (se spec "Autonomt exekveringsmandat"). Task 1–8 dispatchas till Hermes för
implementation (build-arbete, inte skrivet direkt av Claude); Fas B:s Vast.ai-admin-steg utförs av
Claude via `claude-in-chrome`. Branch: `spec/fas7-self-hosted-inference`.

Goal: implementera den **deterministiska, GPU-oberoende kärnan** av Fas 7 — `route_id`-
parametrisering (Beslut 7-fix), `selfhosted_liveness.py` (Beslut 5), `selfhosted_lifecycle.py`
(Beslut 8: idle-stopp + `ensure_running()`), provider-evidence/policy för den nya routen
(Beslut 3), route-isolerad kostnadstelemetri (Beslut 6) och en L0-task-class-eval-harness
(Beslut 4) — allt testbart med **0 GPU-anrop, 0 Vast.ai-anrop**. Den faktiska deploymenten och
det empiriska exit-beviset är **Fas B** (separat, operatörsgodkänd GPU-provisionering, se sist i
detta dokument) — inte en del av denna TDD-sekvens.

Arbetsdisciplin: **TDD** (RED → verifiera fail → GREEN → verifiera pass) per task, vertikala
skivor, frekventa commits. Samma disciplin som Fas 2–6.
Kör kommandon från `C:\Users\rikar\Cortxt\projects\ai-workspace-control-plane\agent-platform`
med **Python312, tom `PYTHONPATH`** (samma pitfall-fix som Fas 6:s exit-checklista dokumenterade:
`C:\Users\rikar\AppData\Local\Programs\Python\Python312\python.exe`, annars kontaminerar
hermes-venvets `rpds`-installation importvägen).

Verifiering efter varje task: `PYTHONPATH= python -m pytest agent-platform/ -m "not real_inference and not docker_required" -q`
— förväntat basvärde **345 passed, 3 skipped** (Fas 6-slut) + nya tester per task, 0 regressioner.

---

## Task 1 — `route_id` som konstruktörsparameter på `TextInferencePort` (Kimi P1-fix)

**Objective:** åtgärda Kimi-granskningens P1: `route_id` är hårdkodat till `"l0-default"` i
`_call_backend`s request-dict (`text_inference_port.py:88`), vilket blockerar Beslut 6:s
route-medvetna kostnadsjämförelse. Görs bakåtkompatibelt (default oförändrad).

**Files:**
- Modify: `agent-platform/runtime/text_inference_port.py`
- Test: `agent-platform/tests/runtime/test_text_inference_port.py` (append)

**Step 1 (RED):**
```python
def test_route_id_defaults_to_l0_default(tmp_path, monkeypatch):
    captured = {}
    def fake_execute(request, adapters):
        captured["route_id"] = request["routes"][0]["route_id"]
        return {"status": "succeeded", "response": {"content": "{}"}}
    monkeypatch.setattr("runtime.text_inference_port._resilient_execute", fake_execute)
    monkeypatch.setattr("runtime.text_inference_port._RI_AVAILABLE", True)
    monkeypatch.setenv("CORTXT_INFERENCE_URL", "https://example.invalid")
    monkeypatch.setenv("CORTXT_INFERENCE_API_KEY", "k")
    port = TextInferencePort(
        model="synthetic-model", budget_gate=_gate(tmp_path, max_calls=5),
        provider_evidence={"approved": True, "provider_id": "p"}, data_class="L0",
    )
    port.invoke("x", output_schema={"type": "object"})
    assert captured["route_id"] == "l0-default"

def test_route_id_is_configurable(tmp_path, monkeypatch):
    captured = {}
    def fake_execute(request, adapters):
        captured["route_id"] = request["routes"][0]["route_id"]
        return {"status": "succeeded", "response": {"content": "{}"}}
    monkeypatch.setattr("runtime.text_inference_port._resilient_execute", fake_execute)
    monkeypatch.setattr("runtime.text_inference_port._RI_AVAILABLE", True)
    monkeypatch.setenv("CORTXT_SELFHOSTED_URL", "https://example.invalid")
    monkeypatch.setenv("CORTXT_SELFHOSTED_API_KEY", "k")
    port = TextInferencePort(
        model="qwen3-8b-instruct", budget_gate=_gate(tmp_path, max_calls=5),
        provider_evidence={"approved": True, "provider_id": "p"}, data_class="L0",
        base_url_env="CORTXT_SELFHOSTED_URL", api_key_env="CORTXT_SELFHOSTED_API_KEY",
        route_id="selfhosted-qwen3-8b",
    )
    port.invoke("x", output_schema={"type": "object"})
    assert captured["route_id"] == "selfhosted-qwen3-8b"
```

**Step 2:** kör → FAIL (`route_id` alltid `"l0-default"` oavsett konstruktörsargument;
`TypeError` om `route_id=` skickas in, eftersom parametern inte finns än).

**Step 3 (GREEN):** lägg `route_id: str = "l0-default"` som konstruktörsparameter, spara på
`self._route_id`, använd `self._route_id` istället för den hårdkodade strängen i
`_call_backend`s request-dict (`"route_id": self._route_id`).

**Step 4:** båda testen PASS; kör hela `test_text_inference_port.py` grön (ingen regression —
default oförändrad för alla befintliga anrop utan `route_id=`).

**Step 5:** commit `fix(runtime): parametrize TextInferencePort route_id (Kimi P1, Fas7 Beslut 7)`.

---

## Task 2 — `selfhosted_liveness.py`: `parse_liveness()` (ren funktion, vLLM `/health`+`/metrics`)

**Objective:** normalisera vLLM:s `/health`- och Prometheus-`/metrics`-svar till en typad
`LivenessSample` (Beslut 5) — 0 nätverksanrop i denna task, ren parsning mot fixtures.

**Files:**
- Create: `agent-platform/runtime/selfhosted_liveness.py`
- Test: `agent-platform/tests/runtime/test_selfhosted_liveness.py` (ny)

**Step 1 (RED):**
```python
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
```

**Step 2:** kör → FAIL (modulen finns inte).

**Step 3 (GREEN):** `LivenessSample` som `@dataclass(frozen=True)`
(`alive: bool, vram_pct: float|None, queue_depth: int|None, tokens_per_sec: float|None,
checked_at: float`). `parse_liveness(health_ok, metrics_text, now_fn=time.time)` — regex-baserad
extraktion av `vllm:gpu_cache_usage_perc` (→ `vram_pct = value*100`) och
`vllm:num_requests_waiting` (→ `queue_depth = int(value)`); `alive=False` → alla mätvärden
`None` (degraderat, aldrig fabricerat, samma princip som `embedding_port.py`s felklassificering);
regex-miss → `None` för respektive fält, inte exception.

**Step 4:** alla tre PASS.

**Step 5:** commit `feat(runtime): selfhosted_liveness.parse_liveness (Fas7 Beslut 5)`.

---

## Task 3 — `selfhosted_liveness.py`: `_LivenessHttpProbe` (I/O-gräns, felklassificering)

**Objective:** den enda I/O-gränsen som faktiskt pratar HTTP mot `/health` och `/metrics` —
samma split-mönster som `embedding_port.py`s `_EmbeddingHttpAdapter`.

**Files:**
- Modify: `agent-platform/runtime/selfhosted_liveness.py`
- Test: `agent-platform/tests/runtime/test_selfhosted_liveness.py` (append)

**Step 1 (RED):**
```python
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
```

**Step 2:** FAIL (`_LivenessHttpProbe` finns inte).

**Step 3 (GREEN):** `_LivenessHttpProbe(base_url, timeout_ms)` med `_fetch_health()` (GET
`/health`, 200 → True, annat/exception → False) och `_fetch_metrics()` (GET `/metrics`, text
eller `""` vid fel); `check()` anropar båda, delegerar till `parse_liveness` (Task 2). Samma
felklassificeringsdisciplin som `_EmbeddingHttpAdapter`: `TimeoutError`/`URLError`/`OSError` →
`alive=False`, aldrig en okontrollerad exception ut ur `check()`.

**Step 4:** PASS.

**Step 5:** commit `feat(runtime): _LivenessHttpProbe I/O boundary (Fas7 Beslut 5)`.

---

## Task 4 — `selfhosted_lifecycle.py`: idle-detektering (ren funktion)

**Objective:** Beslut 8:s mjuka idle-stopp, den beslutande logiken isolerad som en ren funktion
mot en `LivenessSample`-historik (eller senaste-aktivitet-tidsstämpel) — inget Vast.ai-anrop i
denna task.

**Files:**
- Create: `agent-platform/runtime/selfhosted_lifecycle.py`
- Test: `agent-platform/tests/runtime/test_selfhosted_lifecycle.py` (ny)

**Step 1 (RED):**
```python
from runtime.selfhosted_lifecycle import should_stop_for_idle

def test_should_stop_when_idle_past_threshold():
    assert should_stop_for_idle(last_activity_ts=1000.0, now_ts=1000.0 + 16*60,
                                 idle_threshold_minutes=15) is True

def test_should_not_stop_when_within_threshold():
    assert should_stop_for_idle(last_activity_ts=1000.0, now_ts=1000.0 + 5*60,
                                 idle_threshold_minutes=15) is False

def test_should_not_stop_when_no_activity_recorded_yet():
    # Fail-closed the other direction: never seen activity means "just started",
    # not "idle forever" -- caller passes provisioning time as last_activity_ts.
    assert should_stop_for_idle(last_activity_ts=1000.0, now_ts=1000.0,
                                 idle_threshold_minutes=15) is False
```

**Step 2:** FAIL (modulen finns inte).

**Step 3 (GREEN):** `should_stop_for_idle(last_activity_ts, now_ts, idle_threshold_minutes) ->
bool` — ren aritmetik, `(now_ts - last_activity_ts) >= idle_threshold_minutes * 60`.

**Step 4:** PASS.

**Step 5:** commit `feat(runtime): idle-detection pure function (Fas7 Beslut 8)`.

---

## Task 5 — `selfhosted_lifecycle.py`: `_VastAiControlAdapter` + `ensure_running()`

**Objective:** den enda I/O-gränsen mot Vast.ai:s `stop_instance`/`start_instance`-API, plus
`ensure_running()`-wrappern (Beslut 8) som gör kallstart transparent för anroparen. **Mockat i
denna task** — inget riktigt Vast.ai-konto/instans krävs (bekräftas i Fas B).

**Files:**
- Modify: `agent-platform/runtime/selfhosted_lifecycle.py`
- Test: `agent-platform/tests/runtime/test_selfhosted_lifecycle.py` (append)

**Step 1 (RED):**
```python
def test_ensure_running_starts_stopped_instance_then_waits_healthy(monkeypatch):
    calls = []
    class FakeControl:
        def status(self): return "stopped"
        def start(self): calls.append("start")
    class FakeProbe:
        def __init__(self):
            self._n = 0
        def check(self):
            self._n += 1
            return LivenessSample(alive=(self._n >= 2), vram_pct=None,
                                   queue_depth=None, tokens_per_sec=None, checked_at=0.0)
    ensure_running(control=FakeControl(), probe=FakeProbe(), poll_interval_s=0)
    assert calls == ["start"]

def test_ensure_running_noop_when_already_running(monkeypatch):
    calls = []
    class FakeControl:
        def status(self): return "running"
        def start(self): calls.append("start")
    class FakeProbe:
        def check(self):
            return LivenessSample(alive=True, vram_pct=None, queue_depth=None,
                                   tokens_per_sec=None, checked_at=0.0)
    ensure_running(control=FakeControl(), probe=FakeProbe(), poll_interval_s=0)
    assert calls == []

def test_ensure_running_raises_after_max_wait(monkeypatch):
    class FakeControl:
        def status(self): return "stopped"
        def start(self): pass
    class FakeProbe:
        def check(self):
            return LivenessSample(alive=False, vram_pct=None, queue_depth=None,
                                   tokens_per_sec=None, checked_at=0.0)
    with pytest.raises(SelfhostedLifecycleError):
        ensure_running(control=FakeControl(), probe=FakeProbe(), poll_interval_s=0,
                        max_wait_s=0)
```

**Step 2:** FAIL (`ensure_running`, `_VastAiControlAdapter`, `SelfhostedLifecycleError` saknas).

**Step 3 (GREEN):** `_VastAiControlAdapter(instance_id, api_key_env)` implementerar ett litet
Protocol (`status() -> "running"|"stopped"`, `start()`, `stop()`) mot Vast.ai:s REST-API (verklig
HTTP-kod, men testad via `FakeControl` i denna task — riktig integrationstest hör till Fas B).
`ensure_running(control, probe, poll_interval_s=5, max_wait_s=120)`: om `control.status() ==
"stopped"`, anropa `control.start()`, sedan polla `probe.check()` tills `alive=True` eller
`max_wait_s` överskrids (→ `SelfhostedLifecycleError`, fail-closed — hellre ett tydligt fel än
ett anrop mot en icke-redo server).

**Step 4:** alla tre PASS.

**Step 5:** commit `feat(runtime): ensure_running() + _VastAiControlAdapter (Fas7 Beslut 8)`.

---

## Task 6 — Provider-evidence + policy för den självhostade Vast.ai-routen (Beslut 3)

**Objective:** verifiera att `inference/provider_policy.py`s befintliga L0/L1-logik ger rätt
beslut för den nya routens `ProviderEvidence` — ingen ändring i `provider_policy.py` (redan
verifierat generellt), bara en testrad för den specifika evidensen (Beslut 3).

**Files:**
- Test: `agent-platform/tests/inference/test_provider_policy.py` (append)

**Step 1 (RED):**
```python
def test_vastai_selfhosted_route_allowed_at_l0():
    evidence = ProviderEvidence(provider_id="cortxt-selfhosted-vastai-qwen3-8b", approved=True)
    decision = evaluate_provider("L0", evidence)
    assert decision.allowed is True

def test_vastai_selfhosted_route_denied_at_l1_without_zdr():
    evidence = ProviderEvidence(
        provider_id="cortxt-selfhosted-vastai-qwen3-8b", approved=True,
        zero_data_retention=False,
    )
    decision = evaluate_provider("L1", evidence)
    assert decision.allowed is False
    assert "missing_zero_data_retention" in decision.reasons
```

**Step 2:** kör mot befintlig `provider_policy.py` → **förväntas redan PASS** (policyn är generell
och redan testad) — detta är en dokumenterande/regressionsskyddande task, inte en ny
implementation. Om den oväntat FAILar är det ett tecken på att policyn behöver ses över, inte att
denna task ska tvinga fram ett annat resultat.

**Step 3:** ingen produktionskodsändring förväntas.

**Step 4:** PASS.

**Step 5:** commit `test(inference): provider_policy decisions for Fas7 Vast.ai route (Beslut 3)`.

---

## Task 7 — Route-isoleringstest mot `BudgetGate` (Beslut 6)

**Objective:** bekräfta att `route_id`-parametriseringen (Task 1) faktiskt gör
`fas2a_inference_spend`-raderna route-särskiljbara, så `GROUP BY route_id`-kostnadsjämförelsen
(Beslut 6) är meningsfull.

**Files:**
- Test: `agent-platform/tests/runtime/test_text_inference_port.py` (append) eller
  `agent-platform/tests/adapters/test_budget_gate.py` om den existerar (kolla vid
  implementering — annars ny fil under `tests/runtime/`).

**Step 1 (RED):**
```python
def test_two_routes_produce_isolated_spend_rows(tmp_path, monkeypatch):
    monkeypatch.setattr("runtime.text_inference_port._resilient_execute",
                         lambda request, adapters: {"status": "succeeded", "response": {"content": "{}"}})
    monkeypatch.setattr("runtime.text_inference_port._RI_AVAILABLE", True)
    monkeypatch.setenv("CORTXT_INFERENCE_URL", "https://example.invalid")
    monkeypatch.setenv("CORTXT_INFERENCE_API_KEY", "k")
    monkeypatch.setenv("CORTXT_SELFHOSTED_URL", "https://example.invalid")
    monkeypatch.setenv("CORTXT_SELFHOSTED_API_KEY", "k")
    db_path = tmp_path / "spend.db"
    gate = BudgetGate(max_calls=10, db_path=db_path)

    inferx_port = TextInferencePort(model="m1", budget_gate=gate,
        provider_evidence={"approved": True, "provider_id": "inferx"}, data_class="L0")
    selfhosted_port = TextInferencePort(model="qwen3-8b-instruct", budget_gate=gate,
        provider_evidence={"approved": True, "provider_id": "vastai"}, data_class="L0",
        base_url_env="CORTXT_SELFHOSTED_URL", api_key_env="CORTXT_SELFHOSTED_API_KEY",
        route_id="selfhosted-qwen3-8b")

    inferx_port.invoke("x", output_schema={"type": "object"})
    selfhosted_port.invoke("y", output_schema={"type": "object"})

    import sqlite3
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT DISTINCT route_id FROM fas2a_inference_spend WHERE cost_status='success'"
        ).fetchall()
    route_ids = {r[0] for r in rows}
    assert route_ids == {"l0-default", "selfhosted-qwen3-8b"}
```

**Step 2:** FAIL innan Task 1 (route_id alltid `"l0-default"`); **förväntas PASS efter Task 1** —
denna task verifierar Task 1:s konsekvens end-to-end genom `BudgetGate`, inte en ny mekanism.

**Step 3:** ingen produktionskodsändring — detta är ett verifieringstest ovanpå Task 1.

**Step 4:** PASS.

**Step 5:** commit `test(runtime): route isolation across BudgetGate spend rows (Fas7 Beslut 6)`.

---

## Task 8 — L0-task-class-eval-harness (Beslut 4), deterministisk del

**Objective:** en liten, avgränsad eval-harness som kör en namngiven L0-fixture-uppsättning
genom valfri `TextInferencePort`-instans och rapporterar binär success + kostnad — samma roll som
Fas 5:s N=3-baseline-mönster, men **inte** en tvingad återanvändning av
`harness/eval/baseline_direct.py` (den är kodnings-/longcontext-specifik, fel task class för ett
avgränsat L0-bevis — se "Beslut om task-class-harness" nedan). Byggs och testas här helt mot en
fejkad `TextInferencePort` (0 GPU/nätverksanrop); den riktiga N=3-körningen mot en deployad modell
är Fas B.

**Beslut om task-class-harness (plan-nivå, löser specens öppna plan-detalj i Beslut 4):** en ny,
liten modul återanvänder *mönstret* (binär success, kostnad, N rundor) men bygger en egen,
enklare `TaskClassFixture`/`run_task_class_eval`-yta anpassad för en L0-lämplig, avgränsad
uppgift (t.ex. en kort klassificerings- eller extraktionsuppgift över syntetisk text) — inte
`CodingFixture`, som förutsätter long-context-kodrepos och inte är representativ för Fas 7:s
bevissyfte. Exakt fixture-innehåll väljs vid Fas B (kräver inget kodbeslut nu, bara harness-formen).

**Files:**
- Create: `agent-platform/harness/eval/selfhosted_task_class.py`
- Test: `agent-platform/tests/harness/eval/test_selfhosted_task_class.py` (ny)

**Step 1 (RED):**
```python
from harness.eval.selfhosted_task_class import TaskClassFixture, TaskClassResult, run_task_class_eval

def test_run_task_class_eval_reports_success_and_cost():
    fixture = TaskClassFixture(
        id="fx-1", prompt="Classify: is this text about cats? Text: 'My cat sleeps a lot.'",
        output_schema={"type": "object", "properties": {"answer": {"type": "string"}}},
        expected_answer="yes",
    )
    class FakePort:
        def invoke(self, prompt, output_schema):
            return {"answer": "yes"}
    result = run_task_class_eval(fixture, FakePort())
    assert isinstance(result, TaskClassResult)
    assert result.success is True

def test_run_task_class_eval_reports_failure_on_wrong_answer():
    fixture = TaskClassFixture(
        id="fx-2", prompt="...", output_schema={"type": "object"}, expected_answer="yes")
    class FakePort:
        def invoke(self, prompt, output_schema):
            return {"answer": "no"}
    result = run_task_class_eval(fixture, FakePort())
    assert result.success is False
```

**Step 2:** FAIL (modulen finns inte).

**Step 3 (GREEN):** `TaskClassFixture` (frozen dataclass: `id, prompt, output_schema,
expected_answer`), `TaskClassResult` (frozen dataclass: `fixture_id, success, output, error`).
`run_task_class_eval(fixture, port) -> TaskClassResult`: anropar `port.invoke(...)`,
jämför `result.get("answer") == fixture.expected_answer`, fångar `TextInferenceError`/
`BudgetExhausted` → `TaskClassResult(success=False, error=str(exc))` (fail-closed, aldrig en
okontrollerad exception ut).

**Step 4:** PASS.

**Step 5:** commit `feat(harness): selfhosted L0 task-class eval harness (Fas7 Beslut 4)`.

---

## Efter Task 8: verifiera hela kärnan

```
PYTHONPATH= python -m pytest agent-platform/ -m "not real_inference and not docker_required" -q
```
Förväntat: **345 + (nya tester från Task 1–8) passed, 3 skipped, 0 failed.** Ingen regression.

Räkna ut det nya totala talet innan commit av en ev. exit-checklista (samma provenance-disciplin
som Fas 6:s "308 + nya" — skriv aldrig ett antaget tal utan att faktiskt ha kört sviten).

---

## Pre-flight checklist innan Fas B (GPU-provisionering) — Kimi P2:er, inte löst av Task 1–8

Dessa kräver verifiering mot Vast.ai:s faktiska plattform vid provisioneringstillfället, inte
kod. **Blockerar Fas B, inte denna plans Task 1–8:**

1. **LÖST (spec v7):** kvantiseringsvalet är slutgiltigt beslutat — Qwen3-8B-Instruct AWQ/GPTQ
   int4 på ≥16GB Vast.ai-GPU (billigast tillgängliga), operatören bekräftade explicit att detta
   räcker. Ingen ytterligare bekräftelse behövs vid provisionering, bara att välja billigast
   tillgängliga ≥16GB-erbjudande.
2. **Värdstabilitet vid `stop`/`start` (Kimi P2 #3):** verifiera i Vast.ai:s dokumentation eller
   genom en testkörning att en stoppad instans faktiskt återupptas på **samma värd** med disken
   intakt — annars är "snabb återstart" i Beslut 8 optimistisk, och idle-tröskeln bör höjas eller
   `ensure_running()`s fallback-väg (acceptera en långsammare kallstart) blir förstahandsvägen.
3. **Max Duration satt till ett konkret värde** (Kimi P2 #4, spec föreslår 2–4h) vid faktisk
   provisionering — inte lämnat på plattformens default.
4. **Inga dolda avgifter för en stoppad instans** (Kimi P2 #5) utöver lagring — bekräftas mot det
   specifika Vast.ai-erbjudandet som accepteras.
5. **`CORTXT_SELFHOSTED_URL`/`CORTXT_SELFHOSTED_API_KEY`** satta av operatören i miljön som gör
   riktiga anrop — aldrig skrivna ut/committade.
6. **`FAS2A_INFERENCE_BUDGET_MAX`** satt av operatören för budgetgaten innan några riktiga anrop.

---

## Fas B — Empiriskt exit-bevis (separat, GPU-/budgetstyrt, EJ del av Task 1–8)

Görs endast efter pre-flight-checklistan ovan + operatörens go för faktisk provisionering
(kostnadstak ~10 USD, se spec Beslut 2):

1. Deploya Qwen3-8B-Instruct (AWQ eller GPTQ int4) på en Vast.ai ≥16GB-instans (billigast
   tillgängliga vid provisionering) bakom vLLM (`/chat/completions`, `/health`, `/metrics`).
2. Verifiera `_LivenessHttpProbe` (Task 3) mot den riktiga endpointen — första riktiga
   integrationspunkten.
3. Verifiera `_VastAiControlAdapter` (Task 5) mot det riktiga Vast.ai-API:t: stoppa, starta,
   mät faktisk kallstartstid (skriv ner den uppmätta siffran — se specens
   "Kallstartstid — INTE verifierad"-anteckning; ersätt gissningen med ett mätt värde).
4. Bygg de faktiska L0-fixturerna för `TaskClassFixture` (Task 8) — en avgränsad, namngiven
   uppgiftsklass (t.ex. kort klassificering/extraktion över syntetisk text).
5. Kör N=3 rundor av task-class-evalen mot den självhostade routen, jämför mot InferX-baslinjen
   (samma fixtures, olika `route_id`) — Beslut 6:s cost/quality-jämförelse.
6. Verifiera §23-exit-kriteriet operationellt: en fullständig eval-runda visar **noll**
   `attempt_started`-rader mot en extern-provider-`route_id` i `fas2a_inference_spend` (Beslut 4).
7. Skriv en exit-checklista (`2026-08-17-fas7-exit-criterion-checklist.md`, samma mall som Fas
   5/6) med de faktiska mätvärdena — inte antagna.
8. (Valfritt, kostnadskänsligt) Kimi-granskning av den sammanhållna Fas 7-sviten, endast om
   operatören explicit ber om det — samma disciplin som denna plans spec-fas.
