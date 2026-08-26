# SkillOpt evaluation spike

Status: proposed
Date: 2026-08-23
Owner: operator / control-plane coordinator
Related: issue #294 (Prototype: SkillOpt evaluation spike)

## Purpose

Decide whether Microsoft's SkillOpt can serve as the skill-optimization
engine behind section 31 of the target architecture
(`docs/architecture/cortxt-agent-platform-target-architecture.md`), and if
so, in what form: imported as-is, wrapped behind an adapter/port, or not at
all. The spike is bounded: it produces a decision record and evidence, it
does not promote any skill, change permissions, or create new roadmap maps.

## What SkillOpt is (facts from the upstream repo, 2026-08-23)

- Text-space optimizer: the skill document (`best_skill.md`, typically
  300-2,000 tokens) is the trainable state of a frozen agent; model weights
  are untouched and inference-time cost is unchanged.
- Training loop: rollout -> reflect -> aggregate -> select -> update ->
  evaluate. A separate optimizer model applies bounded add/delete/replace
  edits; a candidate edit is accepted only when it strictly improves a
  held-out validation score. Includes a rejected-edit buffer, a textual
  learning-rate budget, and epoch-wise slow/meta updates.
- SkillOpt-Sleep (v0.2.0, preview): nightly offline self-evolution that
  harvests local transcripts (Claude Code, Codex, Cursor, VS Code Copilot,
  Pi, OpenCode), mines recurring tasks, replays them, consolidates, gates,
  stages proposals, and adopts only after human review. The `mock` and
  `handoff` backends make no network calls.
- MIT license, Python 3.10+, PyPI `skillopt`. Reported results: best or
  tied-best on all 52 evaluated (model, benchmark, harness) cells across six
  benchmarks, seven target models, and three execution harnesses; on GPT-5.5
  the average no-skill accuracy lifts by +23.5 points (direct chat), +24.8
  (Codex loop), +19.1 (Claude Code). Gains require recurring tasks with a
  checkable correctness signal; the effect is flat on saturated or noisy
  benchmarks (their own honest scope note).

## Fit analysis against our section 31.1 loop

Our documented pipeline:

```text
trajectory observation
  -> pattern detection
  -> skill candidate
  -> sandboxed evaluation
  -> regression and safety comparison
  -> promotion decision
  -> canary/active or rejected
```

| Dimension | Our mechanism today | SkillOpt contribution | Verdict |
|---|---|---|---|
| Candidate model | `agent-platform/learning/candidate.py` (`Candidate`, manifest hash, locked payload) | Bounded text edits on `best_skill.md` | Complementary: SkillOpt produces new `content_md`; our `Candidate` stays the carrier |
| Eval loop | `harness/eval/runner.py` (baseline vs candidate, budget multiplier) | Rollout/reflect/aggregate + held-out validation gate | SkillOpt adds the full loop we only sketched |
| Promotion rules | `promotion_gate.py` (strictly-better `gt`, tie -> AWAIT_OPERATOR, fail-closed, mandatory operator gates for tool/addon) | Strictly-improves validation gate | Same discipline; our gate remains the only promotion authority |
| Skill instruction eval | `skill_candidate.py` is mechanism-functional but NOT deep-verified for live skill-instruction eval | Ready-made, benchmarked skill-instruction optimization | Fills the recognized gap |
| Permissions/effect classes | Section 32 effect classes, operator gates, no self-approval | No concept of permissions | SkillOpt adds none; our invariants are unaffected |
| Licensing | Apache-2.0 (ADR-031), MIT-compatible skills | MIT | Compatible |

## Scope

In scope:

- Install and run SkillOpt-Sleep's deterministic experiment in an isolated
  venv outside the repository (lab/), mock/handoff backend, no API key.
- Map generated artifacts (`best_skill.md`, report files) onto
  `schemas/skill-manifest.schema.json` and `Candidate.payload`.
- Round-trip one generated document through `SkillCandidateAdapter` and
  `PromotionGate` (eval `baseline_delta` strictly greater than 0, safety
  `no_regression`), recording verdicts and confirming operator gates cannot
  be bypassed.
- Write the decision record into this document.

Out of scope (needs separate operator approval):

- Any live backend (provider calls with transcript-derived content).
- Any import of `skillopt` into `agent-platform/` core packages (ADR-016).
- Promoting, activating, or canarying any skill.
- Creating a new `atlas:map` issue (map wiring is coordinator work).
- Containerization, CI wiring, or packaging.

## Method

Phase 0 - environment probe (free, local):

```bash
python -m venv lab/venv-skillopt   # or pipx; outside the repository
lab/venv-skillopt/Scripts/pip install skillopt
lab/venv-skillopt/Scripts/python -m skillopt_sleep.experiments.run_experiment \
  --persona researcher --assert-improves
```

Record the output log under lab/ (never GitHub). Confirm the mock backend
made no network calls (e.g. run with network disabled and observe identical
behavior).

Phase 1 - artifact mapping:

- Inspect the generated `best_skill.md` / proposal structure.
- Build the mapping table: which fields map to
  `schemas/skill-manifest.schema.json` (manifest, identity, version,
  instructions, examples, input/output schemas, dependencies, fixtures,
  declared tools, highest allowed effect class, provenance) and which are
  missing or structurally incompatible.

Phase 2 - PromotionGate round-trip (pure Python, no model calls):

- Wrap the generated document as `content_md` in `SkillCandidateAdapter`
  (`change_type` = instruction/example/source, the auto-promotable kinds).
- Evaluate with `PromotionGate`: matrix `baseline_delta` > 0 and
  `no_regression` true -> expect PROMOTE; tie -> AWAIT_OPERATOR; regression
  -> REJECT.
- Repeat with an executable-helper candidate and a tool candidate to confirm
  the mandatory operator gate still returns AWAIT_OPERATOR regardless of
  eval scores.

Phase 3 - recommendation (operator-gated):

- Only if phases 0-2 pass: draft a bounded live-backend replay proposal
  (fixture set, budget cap, provider, retention review) for a separate
  operator decision. Do not run it in this spike.

## Data boundary and security

- Deterministic phase: mock/handoff backends only; no transcript-derived
  content leaves the machine.
- A live backend sends truncated, best-effort-redacted transcript excerpts
  to the chosen provider; outbound prompts are not guaranteed secret-free
  upstream. Any live phase requires its own data-boundary review and
  operator approval.
- Nothing secret, no private documents, no full prompts, no model reasoning
  in GitHub issues, PRs, or committed artifacts.

## Governance constraints

- ADR-016: core packages depend only on internal ports/contracts. SkillOpt
  may at most appear behind an adapter or port, never as a core import.
- Section 31 promotion table and `PromotionGate` mandatory operator gates
  remain the sole promotion authority; a candidate can never grant itself
  new rights.
- Workers may not approve, merge, or close their own work.

## Acceptance criteria (mirrors issue #294)

- [ ] Deterministic proof runs with mock/handoff backend, no API key; log recorded under lab/
- [ ] Mapping table present (SkillOpt artifact fields vs skill-manifest schema / Candidate payload)
- [ ] PromotionGate round-trip verdicts recorded; no operator gate bypassed
- [ ] Data-boundary check recorded
- [ ] Decision record below completed

## Decision record (to be filled by this spike)

| Question | Answer |
|---|---|
| Does the deterministic proof pass? | TBD |
| Which artifact fields map cleanly? | TBD |
| Which fields are missing or incompatible? | TBD |
| Gate round-trip: expected verdicts observed? | TBD |
| Recommendation (adopt / adopt-as-adapter / reject) | TBD |
| Rationale tied to the section 31 promotion table | TBD |

## References

- https://github.com/microsoft/skillopt (README, docs/index.md, docs/sleep/README.md)
- Paper: arXiv:2605.23904
- `docs/architecture/cortxt-agent-platform-target-architecture.md` sections 31-32
- `docs/architecture/runtime-and-evaluation-harness.md`
- `agent-platform/learning/skill_candidate.py`, `promotion_gate.py`, `candidate.py`
- `agent-platform/harness/eval/runner.py`
- `schemas/skill-manifest.schema.json`
