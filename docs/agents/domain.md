# Domain Documentation — AI Workspace Control Plane

Status: legacy; unverified architecture inventory
Authority: historical only
Last verified: 2026-08-13 (classified obsolete)

> Do not use the component counts, model assignments, receptionist topology,
> cost tiers, or workflow diagram below as current operating authority. They
> describe an earlier target state. Use
> [the current operating model](current-operating-model.md),
> [the dispatch contract](../architecture/dispatch-contract.md), and the
> repository's accepted ADRs for current decisions.

Historical metadata: version 0.2; formerly marked "Living document"; last
updated 2026-08-03; owner Rikard.

---

## 1. Domänöversikt

AI Workspace Control Plane är en **multi-agent execution platform** där Rikard (operator) arbetar från Buzz, GitHub Issues/Projects är control plane, och specialistagenter körs via Hermes/Pi/Codex för att leverera vertical packages (domän-specifika leveranser).

### 1.1 Kärnkoncept

| Begrepp | Definition |
|---------|------------|
| **Vertical Package** | Versionerad domän-leverans (t.ex. `vertical-01-ai-act`) med workflows, schemas, evals, templates |
| **Agent** | Specialist med definierad roll, modell, skills, och ansvarsområde |
| **Profile** | Hermes-konfiguration: modell, skills, delegation limits, kanban settings |
| **Skill** | SOPs för agent — validerade, versionerade, med interface-kontrakt |
| **Receptionist** | System-specifik integration (Obsidian, Notion, Buzz, Hermes, Pi, Codex) |
| **Dispatch** | Från GitHub Issue → Runtime (Hermes/Pi) med kontrakt |
| **Result Envelope** | Standardiserat resultat från körning (evidence, cost, artifacts) |
| **BVC** | Behaviour Validation Contract — körs i produktion, validerar runtime-beteende |

---

## 2. Agent Profiler (13 st)

### 2.1 Orchestration Layer

| Profil | Modell | Core Skills | Syfte |
|--------|--------|-------------|-------|
| **coordinator** | Nemotron-3-ultra (OpenRouter) | credential-manager, plan, telemetry, receptionist-base, hermes-agent, hermes-model-routing | Routing, planering, synthesis, operator-liaison |
| **planner** | Nemotron-3-ultra (OpenRouter) | plan, test-driven-development, telemetry | Detaljerad task-brytning, sequencing, estimates |
| **workflowreconciler** | Nemotron-3-ultra (OpenRouter) | kanban-github-mirror, telemetry, hermes-kanban-multi-agent | Kanban↔GitHub sync, workflow state reconciliation |

### 2.2 Research & Analysis

| Profil | Modell | Core Skills | Syfte |
|--------|--------|-------------|-------|
| **researcher** | Kimi (Moonshot) | telemetry, arxiv, llm-wiki, ocr-and-documents, youtube-content | Deep research, fakta-sökning, syntes (research-only) |
| **plan-auditor** | Nemotron-3-ultra / Codex | telemetry, plan-auditor | Adversarial review 2-3 iterationer, fresh eyes |

### 2.3 Implementation & Review

| Profil | Modell | Core Skills | Syfte |
|--------|--------|-------------|-------|
| **builder** | Kimi (via Pi Builder) | test-driven-development, systematic-debugging, telemetry | Bounded writes i isolerad workspace |
| **reviewer** | Codex (read-only) | requesting-code-review, telemetry | Architecture/security/PR review |
| **ui-ux-designer** | Nemotron-3-ultra | telemetry, ui-ux-designer, architecture-diagram, design-md | Wireframes → design tokens → handoff |
| **writer** | Nemotron-3-ultra | telemetry, writer, humanizer | Docs, bloggar, PR-beskrivningar, decision briefs |

### 2.4 Operations

| Profil | Modell | Core Skills | Syfte |
|--------|--------|-------------|-------|
| **monitor** | Nemotron-3-nano | telemetry, behaviour-validator | Observability, BVC körning |
| **deploy** | Nemotron-3-ultra | telemetry, serving-llms-vllm | Deployment, serving |
| **credential-manager** | Nemotron-3-ultra | credential-manager, telemetry | Centraliserad secret-hantering |
| **receptionist-*** | Nemotron-3-ultra | receptionist-base, telemetry, respective | System integration (6 st) |

---

## 3. Receptionist Layer (6 System)

| Receptionist | System | Auth | Resources | Special Operations |
|--------------|--------|------|-----------|-------------------|
| **receptionist-obsidian** | Obsidian Vault | File access | file, folder, frontmatter, link, tag, dataview-query | `dataview.query()`, `template.render()`, `link.graph()` |
| **receptionist-notion** | Notion Workspace | Bearer (Integration Token) | page, database, block, comment, user, search | `database.query()`, `page.create_from_template()` |
| **receptionist-buzz** | Buzz.xyz | Bearer (API Key) | message, thread, topic, user, workflow, marker, approval | `marker.filter()`, `workflow.trigger()`, `approval.request()` |
| **receptionist-hermes** | Hermes Agent | File access | profile, skill, kanban-board, kanban-task, cron-job, memory, delegation | `profile.switch()`, `kanban.dispatch()`, `delegation.spawn()` |
| **receptionist-pi** | Pi Builder | Bearer (Registry + API) | container, workspace, egress-rule, volume, network-policy | `workspace.create(bounded)`, `container.run()`, `egress.allowlist()` |
| **receptionist-codex** | Codex App Server | None (localhost) | chat, message, session, file, review | `chat.create()`, `review.request(read_only=true)` |

**Princip:** *Agenter pratar aldrig direkt med externa API:er — de går genom receptionisten.*

---

## 4. Minnesarkitektur

| Minne | Scope | Lagring | TTL | Sensitivity | Auditability |
|-------|-------|---------|-----|-------------|--------------|
| **Session memory** | Enkel agent-körning | Hermes context window | Körning | internal | log-only |
| **Profile memory** | Profil-specifikt | `~/.hermes/profiles/<name>/memories/` (JSONL + SQLite) | Persistent | internal | full-trace |
| **Shared workspace memory** | Flertalet agenter i samma run | `run_workspace/.shared_memory/` (SQLite WAL) | Run-livslängd | internal | full-trace |
| **Global knowledge base** | Alla agenter, alla runs | `docs/knowledge/` + LLM Wiki (git) | Versionerad | public | signed-attestation |
| **Skill memory (SOPs)** | Per skill | Skill directory + version (git) | Versionerad | public | full-trace |

**Shared Memory Implementation:** SQLite WAL + optimistic locking + TTL reaper cron (var 5 min).

---

## 5. Arbetsflöde: Issue → Done

```
Buzz (operator dialog)
    ↓
GitHub Issue (source of truth, Ready)
    ↓
Manual Dispatch (claim, run_id, profile, lease)
    ↓
Runtime (Hermes Coordinator → Specialist agents → Pi Builder)
    ↓
Result Envelope (evidence, cost, artifacts, status)
    ↓
Codex Review (read-only, architecture/security)
    ↓
Operator Approval (Buzz)
    ↓
Done
```

### 5.1 Dispatch Contract (JSON Schema)
```json
{
  "issue_id": "owner/repo#123",
  "workflow": "vertical-01-ai-act",
  "worker_role": "researcher|builder|planner|reviewer|monitor",
  "scope": "Immutable task statement",
  "acceptance_criteria": ["criterion1", "criterion2"],
  "max_runtime_seconds": 1800,
  "max_cost_usd": 2.00,
  "max_parallel_workers": 2,
  "delegation_depth": 1,
  "artifact_policy": "workspace_only|github_artifacts|external_refs",
  "approval_ref": "github.com/owner/repo/issues/123#comment-456"
}
```

### 5.2 Result Envelope (JSON Schema)
```json
{
  "issue_id": "owner/repo#123",
  "run_id": "uuid",
  "status": "succeeded|failed|timed_out|budget_exceeded|blocked|cancelled",
  "runtime": "Hermes|Pi",
  "worker_role": "researcher",
  "started_at": "2026-08-03T10:00:00Z",
  "finished_at": "2026-08-03T10:30:00Z",
  "model": "kimi-k2.5",
  "usage": {"input_tokens": 10000, "output_tokens": 5000, "cache_tokens": 1000, "reasoning_tokens": 2000},
  "cost": {"amount": 0.42, "confidence": "actual"},
  "artifacts": [{"ref": "path/to/artifact", "hash": "sha256...", "size": 1024}],
  "evidence": ["tests passed", "sources cited"],
  "error": {"category": "validation_error", "recovery_suggestion": "fix input schema"}
}
```

---

## 6. Vertical Packages

### 6.1 Strukturt
```
verticals/<vertical-id>/
├── vertical.yaml          # Package metadata
├── README.md              # Overview
├── workflows/             # Domain workflows
├── schemas/               # Input/output JSON Schemas
├── instructions/          # Domain instructions (SOPs)
├── evals/
│   └── synthetic/         # Synthetic test fixtures
└── templates/             # Document templates
```

### 6.2 Vertical-01: AI Act (Nuvarande)
- **Scope:** EU AI Act applicability & obligations
- **Articles:** 2-3, 5, 6 (6.3-6.4), Annex I, III (v0.1); 9-12, Annex IV (v0.1); 14-15 deferred to v0.2
- **Output:** Validated structured JSON + Swedish decision brief + domain evals
- **Status:** v0.1 design phase

---

## 7. Behaviour Validation Contracts (BVC)

Kontinuerlig validering av runtime-beteende i produktion.

### 7.1 BVC Spec (YAML)
```yaml
contract:
  name: "api-latency-p95"
  version: "1.0.0"
  expectation: "p95 latency < 500ms for /api/v1/*"
  measurement:
    source: "prometheus"
    query: "histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket{job=\"api\",handler=~\"/api/v1/.*\"}[5m])) by (le))"
    unit: "seconds"
    sample_window: "5m"
    evaluation_interval: "1m"
  thresholds:
    warn: 0.4
    fail: 0.5
    critical: 1.0
  labels:
    service: "api"
    team: "platform"
    severity: "high"
  alerting:
    on: "fail"
    channels: ["buzz", "github"]
    cooldown: "15m"
    escalation:
      - after: "30m"
        channel: "buzz"
        message: "ESCALATION: API p95 latency > 500ms for 30min"
  remediation:
    runbook: "https://wiki.cortxt.io/runbooks/api-latency"
    auto_mitigation: false
  validity:
    starts_at: "2026-08-01T00:00:00Z"
    expires_at: null
    environments: ["production", "staging"]
```

### 7.2 Inbyggda Kontrakt (5 st)
| Kontrakt | Källkälla | Schedule | Threshold (fail) |
|----------|-----------|----------|------------------|
| Service Availability | Prometheus `up` | `*/1 * * * *` | < 99.9% |
| API Error Rate | Prometheus 5xx rate | `*/1 * * * *` | > 0.1% |
| API Latency P95 | Prometheus histogram | `*/1 * * * *` | > 500ms |
| Daily LLM Cost | Custom (OpenRouter API) | `0 * * * *` | > $50 |
| Deployment Success Rate | GitHub Deployments API | `0 * * * *` | < 90% |

**Alerting:** Buzz (marker `bvc-alert`) + GitHub Issues + Webhook

---

## 8. Skill Framework

### 8.1 Skill Manifest (`skill.yaml`)
```yaml
name: "skill-name"
version: "0.1.0"
maturity: "experimental|stable|deprecated"
category: "software-development|creative|research|productivity"
depends_on:
  - name: "dependency-skill"
    version: ">=0.1.0"
    required: true
interface:
  input_schema: "skill.input.schema.json"
  output_schema: "skill.output.schema.json"
  error_codes: "skill.errors.schema.json"
  openapi: "skill.openapi.yaml"
error_taxonomy:
  transient: ["RATE_LIMITED", "UPSTREAM_ERROR", "TIMEOUT", "AUTH_EXPIRED"]
  permanent: ["VALIDATION_ERROR", "PERMISSION_DENIED", "NOT_FOUND"]
  retry_policy:
    transient: {max_attempts: 3, base_delay_ms: 500, max_delay_ms: 10000, backoff: "exponential"}
    permanent: {max_attempts: 0}
compatibility:
  breaking_changes: []
  deprecated_in: null
  removed_in: null
observability:
  metrics: ["request.total", "request.duration_ms", "request.success", "request.error"]
  traces: true
  logs: "structured-json"
interface_files:
  typescript: "interfaces/skill.ts"
  openapi: "openapi/skill.yaml"
  json_schemas: ["schemas/skill.input.schema.json", ...]
  python_stubs: "stubs/skill.pyi"
```

### 8.2 Livscykel
| Stage | Krav | Gate |
|-------|------|------|
| `experimental` | Skapad, basic tests | Skill curator review |
| `stable` | Integration tests pass, ≥3 runs, inga breaking changes 30d | CI gate + Codex review |
| `deprecated` | Ersättare finns, migrationsguide skriven | 90d varsel |

---

## 9. Profiler & Modell-Routing

| Profil | Modell | Provider | Cost Tier | Latency Budget | Parallelism |
|--------|--------|----------|-----------|----------------|-------------|
| coordinator | Nemotron-3-ultra | OpenRouter | free | interactive (<2s) | sequential |
| planner | Nemotron-3-ultra | OpenRouter | free | batch (<5m) | parallel-2 |
| researcher | Kimi | Moonshot | low | batch (<5m) | parallel-2 |
| builder | Kimi (Pi) | Moonshot | medium | async | sequential |
| reviewer | Codex | OpenAI | premium | async | fan-out |
| workflowreconciler | Nemotron-3-ultra | OpenRouter | free | batch | sequential |
| monitor | Nemotron-3-nano | OpenRouter | free | async | parallel-N |
| deploy | Nemotron-3-ultra | OpenRouter | free | batch | sequential |
| credential-manager | Nemotron-3-ultra | OpenRouter | free | interactive | sequential |
| ui-ux-designer | Nemotron-3-ultra | OpenRouter | free | batch | sequential |
| writer | Nemotron-3-ultra | OpenRouter | free | batch | sequential |
| plan-auditor | Nemotron-3-ultra/Codex | OpenRouter/OpenAI | medium | batch | fan-out |
| behaviour-validator | Nemotron-3-ultra | OpenRouter | free | batch | parallel-N |

---

## 10. Dispatch & Execution Constraints

| Parameter | Värde | Källkälla |
|-----------|-------|-----------|
| `max_parallel_workers` | 2 | Dispatch contract |
| `delegation_depth` | 1 | Dispatch contract |
| `max_runtime_seconds` | Per dispatch (max 86400) | Dispatch contract |
| `max_cost_usd` | Per dispatch (max 1000) | Dispatch contract |
| Kanban dispatch interval | 30s | Profile config |
| Kanban WIP limits | Per column | Board config |

---

## 11. ADR Log (Architecture Decision Records)

| ADR | Titel | Status | Review Trigger |
|-----|-------|--------|----------------|
| ADR-001 | Receptionist pattern vs direct API | Accepted | If >3 receptionists added |
| ADR-002 | Shared memory = SQLite WAL | Accepted | If >10 concurrent agents |
| ADR-003 | Builder vault access via Pi volume | Accepted | If Pi moves to remote host |
| ADR-004 | Skill versioning = semver + compat matrix | Accepted | If breaking change needed |
| ADR-005 | Plan-auditor fresh-eyes = auditor registry | Accepted | If auditor pool <4 |
| ADR-006 | Credential manager = OS Keychain default | Accepted | If secrets >100 or multi-host |
| ADR-007 | Telemetry = OpenTelemetry + W3C traceparent | Accepted | If vendor lock-in risk |
| ADR-008 | Writer style guide = Swedish primary | Proposed | — |
| ADR-009 | Plan-auditor models = Kimi/Codex | Proposed | If cost >$5/run |
| ADR-010 | BVC scheduling = cron + event-driven | Proposed | If alert fatigue >5/day |
| ADR-011 | Model Router for Coordinator | Proposed | If fallback used >10%/30d |
| ADR-012 | Disaster Recovery | Proposed | If ~/.hermes/ >5GB or restore fails |
| ADR-013 | Skill Composition (Packs) | Proposed | If profile skills >20 |

---

## 12. Risk Register

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| R-01: Builder vault access | High | Critical | Pi volume mount `/host/vault` + egress rules |
| R-02: Shared memory corruption | High | High | SQLite WAL + optimistic locking + TTL reaper |
| R-03: Credential fragmentation | High | High | `credential-manager` skill + vault integration |
| R-04: Skill version cascade | Medium | High | Semver + compat matrix + CI gate |
| R-05: Fresh-eyes unenforceable | Medium | High | Auditor registry in shared memory |
| R-06: Missing tool skills | Medium | Medium | 6 wrapper skills created |
| R-07: No observability | Medium | Medium | `telemetry` skill loaded by all profiles |
| R-08: Coordinator model lock-in | Low | Critical | Model router skill + fallback chain |
| R-09: No disaster recovery | Low | High | Profile export/import + daily snapshots |

---

## 13. Glossary

| Term | Definition |
|------|------------|
| **ACP** | Agent Communication Protocol (Hermes) |
| **BVC** | Behaviour Validation Contract |
| **CDP** | Chrome DevTools Protocol |
| **CNI** | Container Network Interface |
| **DAG** | Directed Acyclic Graph |
| **LLM** | Large Language Model |
| **OTel** | OpenTelemetry |
| **Pi** | Pi Builder — containerized Kimi runtime |
| **PR** | Pull Request |
| **RAG** | Retrieval-Augmented Generation |
| **SLA** | Service Level Agreement |
| **SLO** | Service Level Objective |
| **SOPs** | Standard Operating Procedures |
| **TTL** | Time To Live |
| **WAL** | Write-Ahead Logging |
| **WIP** | Work In Progress |

---

## 14. Referenser

- `docs/architecture/AGENT_ARCHITECTURE.md` — Full arkitektur
- `docs/architecture/SKILL_PROFILE_MAPPING.md` — 101 skills → 13 profiler
- `docs/architecture/dispatch-contract.md` — Dispatch/Result kontrakt
- `docs/architecture/runtime-and-evaluation-harness.md` — Runtime gränser
- `docs/architecture/vertical-package-contract.md` — Vertical packages
- `docs/wayfinder/handoffs/shared-context.md` — Destination & decisions
- `docs/adr/` — Architecture Decision Records
- `contracts/` — JSON Schemas & BVC contracts
- `scripts/` — Validation & generation scripts

---

*Historical note from the former living document: session history was recorded
under `docs/wayfinder/handoffs/`; this note is not a current maintenance claim.*
