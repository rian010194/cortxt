# Fas 6 — Geometric Reasoning v1 — implementationsplan (TDD)

Status: **PLAN — SKICKAD till Kimi-review (2026-08-17).** Bygger på GODKÄND spec
`docs/superpowers/specs/2026-08-17-fas6-geometric-reasoning-v01-design.md` (Kimi re-review #2 →
GODKÄND, commit `0275ec1`). Branch `ci/adr-doc-currency-gate-clean`. Task 1–2 redan exekverade
och gröna (314 passed totalt). Planen granskas av Kimi innan resterande TDD-task exekveras.
Goal: implementera den deterministiska kärnan av Fas 6 — typat Problem State + reasoning
graph, contradiction-detektering, tre operatorer, path scoring (versionsstyrd policy,
hash-embedding default), TrajectoryReport — utan regression (308 passed + nya), 0 modellanrop.

Arbetsdisciplin: **TDD** (RED → verifiera fail → GREEN → verifiera pass) per task, vertikala
skivor, frekventa commits. Producer äger rework → hash-bind → re-review vid behov.
Kör kommandon från `C:\Users\rikar\Cortxt\projects\ai-workspace-control-plane`.

Testseam (pre-agreed): alla nya funktioner testas på den offentliga surface som importeras via
`reasoning.geometric`-paketet (inte mot privata `_`-medlemmar). Nya tester placeras under
`agent-platform/tests/reasoning/geometric/test_*.py`.

Verifiering efter varje task: `python -m pytest agent-platform/tests/reasoning/geometric/ -q -m "not real_inference"`.

---

## Task 1 — ReasoningNode-utökning (node_type + metadata), bakåt-kompatibel

**Objective:** lägg till §9.1-nodtyp + §9.3-minsta-metadata på `ReasoningNode` utan att bryta
befintliga konstruktioner.

**Files:**
- Modify: `agent-platform/reasoning/geometric/graph_space.py`
- Test: `agent-platform/tests/reasoning/geometric/test_graph_types.py` (ny)

**Step 1 (RED):** test att en nod kan skapas med `node_type` och `metadata`, med defaultvärden
`None`; att `metadata`-fältet bär en dict.

```python
from reasoning.geometric import ReasoningNode

def test_reasoning_node_has_type_and_metadata_defaults():
    n = ReasoningNode(id="a")
    assert n.node_type is None
    assert n.metadata is None

def test_reasoning_node_type_and_metadata_roundtrip():
    n = ReasoningNode(id="a", node_type="claim", metadata={"provenance": "p1", "data_class": "L0"})
    assert n.node_type == "claim"
    assert n.metadata["data_class"] == "L0"
```

**Step 2:** `pytest tests/reasoning/geometric/test_graph_types.py -v` → FAIL (fält saknas).

**Step 3 (GREEN):** lägg `node_type: Optional[str] = None` och `metadata: Optional[dict] = None`
(respektive `field(default=None)`) som dataclass-fält (efter befintliga; nya fält sist så
positionskonstruktioner `ReasoningNode(id=...)` förblir giltiga).

**Step 4:** test PASS. Kör hela geometric-sviten grön.

**Step 5:** commit `test(geometric): ReasoningNode node_type+metadata fields`.

---

## Task 2 — ProblemSpace relationstyper (rel_type) + accessorer, bakåt-kompatibel

**Objective:** typade kanter enligt §9.2; default otypad behåller dagens beteende; sekundär
nodtyps-indexering härledd ur nodfält (P2.1: `ReasoningNode.node_type` är master).

**Files:**
- Modify: `agent-platform/reasoning/geometric/graph_space.py`
- Test: `agent-platform/tests/reasoning/geometric/test_graph_types.py`

**Step 1 (RED):**
```python
from reasoning.geometric import ProblemSpace, ReasoningNode

def test_add_edge_with_rel_type_stores_type():
    s = ProblemSpace()
    s.add_edge("a", "b", rel_type="contradicts")
    assert s.edge_types("a", "b") == ["contradicts"]

def test_add_edge_default_opaque_keeps_behavior():
    s = ProblemSpace()
    s.add_edge("a", "b")  # otypad
    assert s.edge_types("a", "b") == []
    assert "b" in s.successors("a")  # orörd

def test_node_type_index_derives_from_nodes():
    s = ProblemSpace()
    s.add_node(ReasoningNode(id="c", node_type="claim"))
    assert s.node_type("c") == "claim"
```

**Step 2:** pytest → FAIL (edge_types/node_type saknas).

**Step 3 (GREEN):** `ProblemSpace` får `_edge_types: dict[tuple[str,str], set[str]]`; `add_edge`
får valfri `rel_type: str|None=None` (appendar till setet); `edge_types(src,dst) -> list[str]`
returnerar sorterad lista; `node_type(nid)` hämtar från `self._nodes[nid].node_type` (härlett ur
noden — P2.1). Lägg `iter_edges()` → iterator över (src, dst, list[types]).

**Step 4:** pass; hela geometric-sviten grön.

**Step 5:** commit `feat(geometric): typed relations + node_type index`.

---

## Task 3 — semantic_closeness embedder-injektion (P1.1-fix)

**Objective:** migrera `GraphMetrics.semantic_closeness` till `embedder`-injektion
(`EmbeddingFn = hash_embedding` default), så path scoring + det diagnostiska närhetsmåttet
delar en injicerbar källa. (Åtgärdar Kimi P1.1.)

**Files:**
- Modify: `agent-platform/reasoning/geometric/metrics.py`
- Test: `agent-platform/tests/reasoning/geometric/test_metrics.py` (append)

**Step 1 (RED):**
```python
from reasoning.geometric.metrics import GraphMetrics
from reasoning.geometric import ProblemSpace, ReasoningNode

def test_semantic_closeness_accepts_injected_embedder():
    s = ProblemSpace()
    s.add_node(ReasoningNode(id="a", evidence=0.9)); s.add_node(ReasoningNode(id="b"))
    custom = lambda nid: [1.0, 0.0]
    # identisk nod mot samma injector → 1.0
    assert GraphMetrics.semantic_closeness(s, "a", "a", embedder=custom) == 1.0
```

**Step 2:** pytest → FAIL (semantic_closeness tar inte embedder).

**Step 3 (GREEN):** ändra signatur till
`semantic_closeness(space, a, b, embedder=hash_embedding)` och
`return cosine(embedder(a), embedder(b))`. Importera `hash_embedding` redan finns i metrics.py.

**Step 4:** pass (befintliga test_metrics förblir gröna — default `hash_embedding`).

**Step 5:** commit `refactor(geometric): semantic_closeness embedder injection (P1.1)`.

---

## Task 4 — Contradiction-enhet + ContradictionDetector + find_contradiction

**Objective:** förstklassig contradiction-detektering: explicit `contradicts`-kant eller
tröskelbaserad `contradiction_degree`; `find_contradiction`-operatorn.

**Files:**
- Create: `agent-platform/reasoning/geometric/contradiction.py`
- Modify: `agent-platform/reasoning/geometric/__init__.py`
- Test: `agent-platform/tests/reasoning/geometric/test_contradiction.py` (ny)

**Design (kontrakt):**
```python
@dataclass
class Contradiction:
    a: str
    b: str
    source: str  # "edge" | "degree"
    degree: float

class ContradictionDetector:
    def __init__(self, degree_threshold: float = 0.7): ...
    def detect(self, space, node_id) -> list[Contradiction]: ...

def find_contradiction(space, node_id, threshold=0.7) -> list[Contradiction]: ...
```

**Step 1 (RED):** explicit kant detekteras med source="edge"; tröskelöverskridande nodhittas
med source="degree"; nod utan motstycke → tom lista.

**Step 3 (GREEN):** implementera enligt kontrakt ovan (kollar `edge_types(a,nid)` för
"contradicts", plus noder vars `contradiction_degree >= threshold`).

**Step 4:** pass. Re-export i `__init__.py` (`Contradiction`, `ContradictionDetector`,
`find_contradiction`).

**Step 5:** commit `feat(geometric): contradiction detection + operator`.

---

## Task 5 — Operatorer: change_perspective + compare_paths

**Objective:** `change_perspective` (subgraf från alternativ vy via alternative_to/analogous_to;
degraderar till tom/identisk + flagga) och `compare_paths` (rankar två kandidatbanor med path
scoring).

**Files:**
- Create: `agent-platform/reasoning/geometric/operators.py`
- Modify: `agent-platform/reasoning/geometric/__init__.py`
- Test: `agent-platform/tests/reasoning/geometric/test_operators.py` (ny)

**Kontrakt (design, plan-nivå):**
```python
@dataclass
class PerspectiveResult:
    subgraph: ProblemSpace
    changed: bool

def change_perspective(space, nid, target) -> PerspectiveResult: ...
def compare_paths(space, path_a, path_b, goal, policy) -> tuple[list[str], float]:  # bättre path, score
```

(compare_paths beror på Task 6:s `score_path` — sekvensera Task 6 före den sista delen av
Task 5 om nödvändigt, eller definiera compare_paths i Task 6. Se not.)

**Step 1–5:** TDD per funktion. `change_perspective` testas först (oberoende), commit.
`compare_paths` implementeras och committas EFTER att `score_path` finns (Task 6).

**Commit:** `feat(geometric): change_perspective + compare_paths operators`.

---

## Task 6 — Path scoring: CandidatePathScore + score_path (versionsstyrd policy)

**Objective:** §12.4:s sökfunktion som versionsstyrd policydataclass; `score_path` beräknar
formeln med `CandidatePathScore`-vikter och en `embedder` (default hash_embedding).

**Files:**
- Create: `agent-platform/reasoning/geometric/path_scoring.py`
- Modify: `agent-platform/reasoning/geometric/__init__.py`
- Test: `agent-platform/tests/reasoning/geometric/test_path_scoring.py` (ny)

**Kontrakt (design, plan-nivå):**
```python
@dataclass
class CandidatePathScore:
    version: str = "v1"
    w1: float = 0.2  # expected_information_gain
    w2: float = 0.3  # goal_relevance
    w3: float = 0.3  # evidence_coverage
    w4: float = 0.1  # path_novelty
    w5: float = 0.2  # contradiction_risk (subtract)
    w6: float = 0.1  # expected_cost (subtract)
    w7: float = 0.1  # policy_risk (subtract)
    embedder: EmbeddingFn = hash_embedding

def score_path(space, path, goal, policy: CandidatePathScore = CandidatePathScore()) -> float: ...
```

**Step 1 (RED):** score med kända handräknade värden (inte tautologi — väntevärde från
policydata + fixturens kända metrics); högre evidens/novelty → högre score; contradiction →
lägre.

**Step 3 (GREEN):** implementera formeln (Beslut 5) med aggregering över path-noder; använd
`GraphMetrics` för termerna + `policy.embedder` för expected_information_gain (cosine mot
goal-embedding). `policy_risk` sätts via en policyregel (t.ex. subtrahera
`contradiction_degree`-andel) — v1-standardvärden per spec.

**Step 4:** pass.

**Step 5:** commit `feat(geometric): versioned path scoring (CandidatePathScore + score_path)`.

---

## Task 7 — TrajectoryReport (datakontrakt + rapport), JSON + text-renderare

**Objective:** `TrajectoryReport`-builder som serialiserar en ProblemSpace + path + scoring +
attractor/contradiction-flaggor till ett granskningsbart, versionerat datakontrakt (JSON) + en
text-renderare. GUI-viewer är DEFERRAD (inte i denna v1).

**Files:**
- Create: `agent-platform/reasoning/geometric/trajectory.py`
- Modify: `agent-platform/reasoning/geometric/__init__.py`
- Test: `agent-platform/tests/reasoning/geometric/test_trajectory.py` (ny)

**Kontrakt (design, plan-nivå):**
```python
@dataclass
class TrajectoryReport:
    version: str = "v1"
    space: ProblemSpace = field(default_factory=ProblemSpace)
    path: list[str] = field(default_factory=list)
    goal: str | None = None
    path_score: float | None = None
    policy_version: str | None = None
    attractor_nodes: list[str] = field(default_factory=list)
    contradictions: list[dict] = field(default_factory=list)

    def to_json(self) -> str: ...
    def render_text(self) -> str: ...
```

**Step 1 (RED):** samma space+path+scoring → identisk `to_json()` (renhet/determinism);
metadata (node_type, evidence, contradiction), attraktorer, contradictions, policy-version
inkluderas; `render_text()` innehåller path + score.

**Step 3 (GREEN):** implementera (ren funktion från space; `to_json` använder `json.dumps` med
kanoniskt/stable-ordning — t.ex. `sort_keys=True` — för determinism; inga modellanrop).

**Step 4:** pass.

**Step 5:** commit `feat(geometric): TrajectoryReport datakontrakt + text/JSON render`.

---

## Task 8 — Integration + full regression + dokumentation

**Objective:** säkerställ att allt nytt är exporterat, att `pipeline.py` förblir oförändrad och
grön, och att hela default-sviten är grön (308 + nya), 0 modellanrop.

**Files:**
- Modify: `agent-platform/reasoning/geometric/__init__.py` (säkerställ exporthélsa)
- Modify: `docs/superpowers/plans/2026-08-17-fas6-exit-criterion-checklist.md` (ny checklist —
  se nedan)

**Steg:**
1. Kör hela geometric-sviten: `pytest agent-platform/tests/reasoning/geometric/ -q -m "not real_inference"` → alla gröna.
2. Kör hela default-sviten: `pytest agent-platform/ -q -m "not real_inference and not docker_required"` → **308 + nya gröna, 0 regressions**.
3. Bekräfta 0 modellanrop (inga nya `real_inference`-tester; kärnan körs i default).
4. Skriv `docs/superpowers/plans/2026-08-17-fas6-exit-criterion-checklist.md` (vad som är
   strukturellt bevisat i denna v1 vs vad som kräver §27#10 + budget för det empiriska
   exit-stegest). Commit.

**Commit:** `docs: Fas 6 structural exit checklist + full regression green`.

---

## Noter / risker

- **compare_paths (Task 5) beror på score_path (Task 6)** — sekvensera: Task 5 gör
  `change_perspective` först (oberoende), och `compare_paths` slutförs efter Task 6. Alternativt
  slå ihop Task 5:s `compare_paths` med Task 6. Planen håller dem separata för tydlighet; en
  committing-enhet kan kombinera dem.
- **Backard-kompatibilitet** är hård: nya fält/parametrar har defaultvärden; befintliga 13
  geometric-tester + pipeline återstår gröna efter varje task (Test i Step 4 körs alltid).
- **Embedding-stub kvar**: `hash_embedding` är default; §27 #10-providern byts in senare via
  samma yta (drop-in).
