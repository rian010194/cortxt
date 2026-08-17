# Fas 8 — Kontrollerad learning loop — implementationsplan (TDD)

Status: **PLAN-DRAFT — REDO FÖR KIMI-REVIEW PÅ OPERATÖRENS BEGÄRAN (spec GODKÄND).** Bygger på GODKÄND spec
`docs/superpowers/specs/2026-08-18-fas8-controlled-learning-loop-v01-design.md` (Kimi re-review #2 → GODKÄND,
commit `34bdbec`). Branch `spec/fas8-controlled-learning-loop`. Planen går till Kimi för oberoende review innan
operatörsinspektion och exekvering (operatörens direktiv: spec→Kimi→plan→Kimi→operatörsinspektion→exekvera).

Goal: bygga den deterministiska kärnan av Fas 8 — en versionerad-kandidat-livscykel (CandidateRegistry →
offline EvidenceMatrix → rule-driven PromotionGate → rollback) med **stabila, typ-agnostiska kontrakt**
(Beslut 9), **geometric-genomsyrande** på selektionssidan + **policy-constraint-säkerhet** (Beslut 10a),
**Voyage-förcachad semantisk injektion** (Beslut 10b), **EvidenceClassifier i två faser** (Beslut 10c, P2.6) —
utan regression (328 befintliga pass + nya), 0 live-resurser i default-sviten.

Arbetsdisciplin: **TDD** (RED → verifiera fail → GREEN → verifiera pass) per task, vertikala skivor, frekventa
commits. Producer äger rework → hash-bind → re-review. Kör kommandon från
`C:\Users\rikar\Cortxt\projects\ai-workspace-control-plane\agent-platform`.

Testseam (pre-agreed): alla nya funktioner testas på den offentliga `learning`-paketets surface (importeras
via `agent-platform/learning/__init__.py`, aldrig mot privata `_`-medlemmar). Nya tester under
`agent-platform/tests/learning/test_*.py`. Fixtures: små deterministiska geometriska space med kända
path-scoring-egenskaper (återbruk av `tests/reasoning/geometric/`-mönstret) + mockade "Voyage-lika" embedders.

P2-adoptioner från Kimi re-review #2: **P2.4** `candidate_id = f"{type}@{name}@{version}"` (`Candidate.id` ≡
sammansatt nyckel); **P2.5** `promoted_by = "gate:<gate_name>"`/`"system:auto"` vid auto-promotion,
`"operator:<name>"` vid manuell; **P2.6** `EvidenceClassifier` två faser ((a) vid submit, (b) verifier-checks
av `EvidenceMatrix` före `PromotionGate.evaluate`).

Verifiering efter varje task: `python -m pytest agent-platform/tests/learning/ -q -m "not real_inference"` +
(slutet) hela default-sviten.

---

## Task 1 — `candidate.py`: typ-agnostisk Candidate-datamodell (immutabel, id ≡ type@name@version)

**Objective:** fastställ kandidatkontraktet (Beslut 9.1) med `candidate_id = f"{type}@{name}@{version}"` (P2.4)
och hash-låst `manifest_hash` över det **serialiserade payload-dict**:et (P0.1).

**Files:**
- Create: `agent-platform/learning/candidate.py`
- Create: `agent-platform/learning/__init__.py`
- Test: `agent-platform/tests/learning/test_candidate.py` (ny)

**Step 1 (RED):** test att:
```python
from learning import Candidate

def test_candidate_id_equals_type_at_name_at_version():  # P2.4
    c = Candidate(type="policy", name="geometric-path-scoring", version="v2")
    assert c.id == "policy@geometric-path-scoring@v2"

def test_manifest_hash_binds_to_serialized_payload():     # P0.1
    payload = {"w1": 0.1, "w2": 0.4, ...}
    c1 = Candidate(type="policy", name="np", version="v1", payload=payload)
    c2 = Candidate(type="policy", name="np", version="v1", payload=dict(payload))
    assert c1.manifest_hash == c2.manifest_hash           # deterministic over serialized dict
    assert c1.payload is payload or c1.payload == payload  # immutable snapshot, not mutable ref
```
**Step 2:** kör → FAIL (modul saknas).
**Step 3 (GREEN):** implementera `Candidate` som `frozen=True` dataclass: fält `{id, type, name, version,
manifest_hash, status, payload_ref, proposed_at, promoted_by, promoted_at, rolled_back_at}`; `id` är property
`f"{type}@{name}@{version}"`; `manifest_hash = sha256(json.dumps(payload, sort_keys=True))`; `payload_ref`
pekar på en **låst kopia** (frozen payload-snapshot), inte på original-mutable-objektet.
**Step 4:** PASS. 
**Step 5:** commit `feat(learning): Candidate datamodel — immutable, id=type@name@version, hash over serialized payload`.

---

## Task 2 — `registry.py`: CandidateRegistry (SQLite, nycklad på type@name@version, aktiv-pekare)

**Objective:** persistent registry (Beslut 9.4) med `add`, `get(type,name,version)`, `get_active(type,name)`,
hash-idempotens, audit-kolumner; aktiv-pekare-tabell.

**Files:**
- Create: `agent-platform/learning/registry.py`
- Test: `agent-platform/tests/learning/test_registry.py`

**Step 1 (RED):** add/get round-trip; get_active efter promote; nyckelkonflikt (`add` med samma
`type@name@version` men olikt manifest → `RegistryError`; lika manifest → idempotent no-op); SQLite round-trip
över två registry-instanser (persistens); `set_active(type,name,version)` skriver aktiv-pekare.
**Step 3 (GREEN):** `CandidateRegistry` med `sqlite3`, `_ensure_table`-mönster (samma som `BudgetGate`),
tabeller `candidates(type,name,version,manifest_hash,status,payload_json,promoted_by,audit_timestamps)` +
`active_candidates(type,name,active_version,updated_at)`; hash-verifiering vid add.
**Step 5:** commit `feat(learning): CandidateRegistry — SQLite persist, type@name@version key, active-pointer`.

---

## Task 3 — `submit.py` + EvidenceClassifier fas (a): ingångsdörr + initial klassificering

**Objective:** `submit_candidate(type, name, payload, provenance)` (Beslut 9.5) validerar manifest-hash +
typregistrering, sätter `eval_pending`, och kör EvidenceClassifier **fas (a)** (initial klassificering i
facts/events/instructions/tasks) (Beslut 10c, P2.6).

**Files:**
- Create: `agent-platform/learning/submit.py`
- Modify: `agent-platform/learning/evidence.py` (fas (a)-del)
- Test: `agent-platform/tests/learning/test_submit.py`

**Step 1 (RED):** submit lägger en kandidat i `eval_pending` och klassificerar dess payload; submit med bruten
hash / okänd typ → `ValidationError`, ingen rad skriven.
**Step 3 (GREEN):** `submit_candidate` → registry.add + EvidenceClassifier.phase_a(payload) → typad evidens.
**Step 5:** commit `feat(learning): submit_candidate ingress + EvidenceClassifier phase (a)`.

---

## Task 4 — `promotion_gate.py`: PromotionRule + rule-driven exekutor (intern resolution, self-approval-säker)

**Objective:** Beslut 3/9.3 + P0.2/P0.3 + P2.5. `PromotionRule` (frozen, med candidate_type/kind/metric/threshold/
comparator/operator_scope); `PromotionGate.evaluate(matrix, candidate_id)` **resolverar regler internt** ur
registry + `MANDATORY_OPERATOR_GATES`-union; `promoted_by`-semantik (P2.5).

**Files:**
- Create: `agent-platform/learning/promotion_gate.py`
- Test: `agent-platform/tests/learning/test_promotion_gate.py`

**Step 1 (RED) — kritiska säkerhetstester (P0.2):**
- (a) en adapter som försöker `register_rule` med en `operator_gate` borttagen, eller `evaluate` med en
  `rules`-param → `TypeError` (signaturen tar ingen `rules`) — bypass via signatur omöjlig;
- (b) `MANDATORY_OPERATOR_GATES` union:as alltid in: en tool-kandidat ger `AWAIT_OPERATOR` oavsett eval;
- (c) `promoted_by`-initiering: auto-promotion sätter `"gate:<gate_name>"` (P2.5).
- Och: försämrad policy-kandidat → `REJECT`; strikt-bättre + no-regression → `PROMOTE`; neutral → `AWAIT_OPERATOR`
  (P1.7).
**Step 3 (GREEN):** `PromoteRule` frozen dataclass; `PromotionGate.evaluate(matrix, candidate_id)` slår upp typ
i registry, hämtar registrerade regler, union MANDATORY_OPERATOR_GATES, evaluerar datadrivet (metric/threshold/
comparator), returnerar `{PROMOTE, AWAIT_OPERATOR, REJECT}`.
**Step 5:** commit `feat(learning): PromotionGate rule-executor — internal rule resolution, self-approval safe`.

---

## Task 5 — `evidence.py` fas (b): verifier-checks på EvidenceMatrix före gate (P2.6)

**Objective:** Beslut 10c fas (b): klassificerings + **verifier-checks** (manifest-form, hash-integritet,
fixture-täckning, no-regression) körs på `EvidenceMatrix` **innan** `PromotionGate.evaluate`; evidens som
inte klarar → fail-closed (ingen promotionsvikt).

**Files:**
- Modify: `agent-platform/learning/evidence.py`
- Modify: `agent-platform/learning/promotion_gate.py` (anrop fas (b) före evaluate — i en orkestrerande
  wrapper, t.ex. `learning/pipeline.py`)
- Test: `agent-platform/tests/learning/test_evidence.py`

**Step 1 (RED):** matris med bruten hash / ofullständig fixture-täckning / regresserande rad → verifier fail → gate
blir `REJECT` (aldrig `PROMOTE` på overifierad evidens); giltig matris → gate normal.
**Step 3 (GREEN):** `EvidenceClassifier.verify(matrix, candidate)` checks + gate-orkestrerare som kör fas (b)
innan evaluate.
**Step 5:** commit `feat(learning): EvidenceClassifier phase (b) — verifier-checks gate evidens fail-closed`.

---

## Task 6 — `evaluator.py`: EvidenceMatrix (multi-kandidat + no-regression) + Voyage-förcachad injektion

**Objective:** Beslut 2/9.2 + P1.2: `Evaluator` kör flera kandidater mot baseline → `EvidenceMatrix`
(success-rate, cost, latency, no-regression); kandidat-ranking via `score_path`/`CandidatePathScore`; vid
live-eval **pre-computar/förcachar** alla embeddings (nodes+goal) så `embedder` är lookup (P1.2).

**Files:**
- Create: `agent-platform/learning/evaluator.py`
- Test: `agent-platform/tests/learning/test_evaluator.py`

**Step 1 (RED):** EvidenceMatrix med 2 kandidater + baseline; no-regression-flagga korrekt; en mockad
"Voyage-lik" embedder ändrar ranking (semantiskt nära) medan `hash_embedding`-default är deterministisk; test
att **embedder anropas ≤ #unika texter** (pre-cache, P1.2) med en räknande mock.
**Step 3 (GREEN):** `Evaluator` använder geometriska fixtures + `score_path`; pre-cache-wrapper runt `EmbeddingFn`.
**Step 5:** commit `feat(learning): Evaluator — multi-candidate EvidenceMatrix, embedding pre-cache (P1.2)`.

---

## Task 7 — `rollback.py`: rollback(type, name) atomär pekaråterställning + audit (P1.5)

**Objective:** Beslut 7: `rollback(type, name)` (P1.5) återställer aktiv-pekaren till `promoted_from`, atomärt,
skriver audit-rad; idempotent (rollback av redan rullad-back = no-op/tydligt fel, inte korruption).

**Files:**
- Create: `agent-platform/learning/rollback.py`
- Test: `agent-platform/tests/learning/test_rollback.py`

**Step 1 (RED):** promote v2 → rollback → aktiv vänd tillbaka till v1 + audit-rad; `rollback` med `name` väljer
rätt kandidat bland flera `name` under samma `type` (P1.5); dubbel-rollback → no-op utan korruption; promotion
efter rollback fungerar.
**Step 3 (GREEN):** transaktionslogik över `active_candidates` + `candidates.audit`.
**Step 5:** commit `feat(learning): rollback(type,name) atomic pointer restore + audit`.

---

## Task 8 — policy-kandidatadapter + policy-constraint safety-regler (P1.1)

**Objective:** Beslut 1 + P1.1: `PolicyCandidate`-adapter (`CandidatePathScore`-payload → kandidat) + de tre
konkreta `safety`-reglerna `normalized_weights`/`non_negative_weights`/`bounded_weights` som dataregler →
bryter constraint = `REJECT`.

**Files:**
- Create: `agent-platform/adapters/learning/policy_candidate.py`
- Test: `agent-platform/tests/learning/test_policy_candidate.py`

**Step 1 (RED):** en viktuppsättning med summa ≠ 1.0 (additiv eller subtraktiv) → `REJECT`; en negativ vikt →
`REJECT`; vikt >1 → `REJECT`; giltiga vikter → passerar constraint-skiktet. (0 live-resurser; mock fixtures.)
**Step 3 (GREEN):** adapter + constraint-regler registrerade som `PromotionRule`s (data).
**Step 5:** commit `feat(learning): policy-candidate adapter + concrete policy-constraint safety rules (P1.1)`.

---

## Task 9 — `active_policy`-injektion in `score_path` (minimal, default oförändrad)

**Objective:** Beslut 8 + P2.1: `learning.active_policy("policy", "geometric-path-scoring") ->
CandidatePathScore | None`; `score_path`-anropsplatsen kan hämta aktiv policy; **default = None = befintlig
`CandidatePathScore()`** så alla befintliga anrop/tester är oförändrade. (P2.1: fail-open till default vid
saknad rad, DB-läsningsmönster.)

**Files:**
- Create: `agent-platform/learning/active.py`
- Modify: `agent-platform/reasoning/geometric/path_scoring.py` (punkten där aktiv policy kan läsas — INGEN
  beteendeändring; default oförändrad)
- Test: `agent-platform/tests/learning/test_active_policy.py`

**Step 1 (RED):** `active_policy` returnerar `None` när ingen promotad version finns (default oförändrad); efter
promotion av v2 → returnerar v2:s `CandidatePathScore`; `score_path` med default-policy ger identiskt resultat
före/efter (produktion ostörd).
**Step 3 (GREEN):** tunn injektionsfunktion; ingen ändring av befintliga default-värden.
**Step 5:** commit `feat(learning): active_policy injection into score_path — default unchanged (Beslut 8)`.

---

## Task 10 — exit-tester: produktion ostörd + dubbelriktning (strikt-bättre promotas, sämre avvisas)

**Objective:** verifiera Fas 8:s exit-kriterium (Beslut 8, Spec Testing) deterministiskt: (a) en medvetet bättre
policy-kandidat kan promotas; (b) en medvetet sämre avvisas och produktionen berörs aldrig; (c) `score_path`/
`Engine.solve` returnerar EXAKT samma resultat före/efter under en evaluering/promotion/rollback.

**Files:**
- Test: `agent-platform/tests/harness/eval/test_fas8_exit_criterion.py` (ny, mönster från Fas 6:s exit-test)

**Step 1 (RED):** dubbelriktnings-tester mot geometriska fixtures; produktion-ostörd-assertion (kör `score_path`
innan/under/efter, jämför exakt).
**Step 3 (GREEN):** inga nya produktionsmoduler — enbart test-harness som kör Task 1–9-loopen.
**Step 4:** **N=3-gröna körningar** (V01-rek #5): exit-sviten helt grön i tre konsekutiva körningar.
**Step 5:** commit `test(learning): Fas 8 exit — better promotes, worse rejects, production untouched (N=3)`.

---

## Task 11 — skill-/tool-kandidatadapter (mekanism-kopplade, ärlig v1.x-scopegräns) (P1.6)

**Objective:** Beslut 5/P1.6-ärlighet: `SkillCandidate`-adapter registrerar `SkillManifest` och kör §31-regel-gate
(instruktion/exempel → `[eval,safety]`; executable-helper/tool → `AWAIT_OPERATOR`); `ToolCandidate`-adapter
registrerar tool + `external-mutation`/`credential` → alltid `AWAIT_OPERATOR`. **Enbart mekanism-koppling** —
ingen live-skill-eval, ingen full tool-security i v1 (deklarerat).

**Files:**
- Create: `agent-platform/adapters/learning/skill_candidate.py`, `tool_candidate.py`
- Test: `agent-platform/tests/learning/test_candidate_adapters.py`

**Step 1 (RED):** en skill-instruktionskandidat med giltig eval → `PROMOTE`-väg möjlig (gate mekanisk); en
skill-executable-helper → `AWAIT_OPERATOR`; en tool med external-mutation → `AWAIT_OPERATOR` oavsett eval (P0.2/Beslut 5).
**Step 3 (GREEN):** adaptrarna registrerar + gate-resolverar korrekt via det redan byggda registret/promotion_gate.
**Step 5:** commit `feat(learning): skill/tool candidate adapters — mechanism-hooked, honest v1.x scope (P1.6)`.

---

## Task 12 — V01-close-out (dokumentation + integrationsnoteringar) (Kimi V01-recs)

**Objective:** Kimi V01-rekommendationer (Spec "V01-close-out"): skapa `docs/superpowers/V01-exit-report.md`
(mall: varje fas 0–8, exit-kriterium, commit-hash, testresultat, caveats); dokumentera integrationspunkterna
Supervisor→`active_policy` (Fas 4) och ToolGate→tool-kandidat (Fas 3). Inga produktionskodsändringar — dokumentation.

**Files:**
- Create: `docs/superpowers/V01-exit-report.md` (skiss för Fas 8-raden; övriga faser fylls vid V01-slutet)
- Create: `docs/superpowers/2026-08-18-fas8-integration-points.md` (Supervisor/ToolGate-noteringar)

**Step 1:** skriv mall + integrationsnoteringar. **Step 2:** commit `docs(learning): V01-close-out — exit-report template + integration points`.

---

## Verifiering & leverans

- Efter Task 11: hela default-sviten
  `pytest agent-platform/ -m "not real_inference and not docker_required"` grön (328 befintliga pass + ~20–30
  nya learning-tester; de 3 `test_text_inference_port`-route_id-testerna är ett förexisterande env-caveat —
  `cortxt_resilient_inference`-paket ej installerat — och är INTE Fas 8-introducerat).
- **0 modellanrop i default-sviten**; Voyage live-arm är en separat `real_inference`-körning (budgetgated,
  operatörsgodkänd — inte del av TDD-kärnan).
- Exit-kriteriet bevisas i Task 10 (N=3 gröna körningar).
- Planen skickas till Kimi för review innan operatörsinspektion; producer äger rework vid KRÄVER.
- **Hårda gränser (från specen):** ingen kandidat promotas i en riktig produktionsväg; merge/deploy = operator;
  verkligt skarpt live-Voyage-steg = operatörsgodkänd budget + operatörsatt `CORTXT_EMBEDDING_URL/API_KEY`; ingen
  självapproval av plan.
