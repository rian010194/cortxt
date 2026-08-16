# Fas 3 exit-criterion checklist

> **Register, not description.** This file is filled in once, at the point
> Fas 3 is called proven, and is never edited afterward — if a later change
> invalidates a row, a NEW checklist is written that supersedes this one,
> per this repo's register/description discipline. It records evidence, one
> row per proving test, for the two-part exit criterion in the design spec's
> Purpose section (`docs/superpowers/specs/2026-08-16-fas3-coding-agent-v01-design.md`).

**Framing, taken from the spec's own words (Purpose section):** "Fas 2's exit
criterion was a capability claim... Fas 3's is a capability claim *plus a
containment claim*. This checklist proves a CAPABILITY — that the mechanism
built in Tasks 1-12 can solve and verify a real code fixture under machine-
proven ceilings. It is not a claim that Pi or Hermes become unnecessary: per
the spec's own "Out of scope" section, "Nothing in
`docs/agents/current-operating-model.md` changes as a result of this phase;
Pi Builder remains the bounded-write experiment it is today until a separate
operator decision says otherwise." Fas 3 runs from tests only (and, for
Task 14, one manual run) — it is not wired into any live dispatch path.

## Part 1 — "a simple code fixture can be solved and verified without Pi or Hermes"

| Evidence | Test | Status |
|---|---|---|
| The fixture is real and really broken as shipped | `tests/runtime/test_vertical_02_fixture.py::test_the_fixture_workspace_really_is_broken` | [ ] |
| The mechanism solves it end-to-end with zero model calls (proves the PLUMBING) | `tests/runtime/test_coding_loop.py::test_coding_loop_succeeds_end_to_end_against_the_real_fixture` | [ ] |
| The mechanism refuses a non-fix (wrong patch) rather than reporting false success | `tests/runtime/test_coding_loop.py::test_blocked_on_falsification_failure_when_the_patch_does_not_fix_the_bug` | [ ] |
| **The fixture is solved by a REAL model call** (the actual criterion — Task 14) | `tests/runtime/test_coding_loop_real_inference.py::test_off_by_one_fixture_solved_without_pi_or_hermes` | [ ] — run manually, report result to Rikard |
| No dispatch/Hermes/Pi Builder code path is touched by any of the above | Manual grep confirmation: `grep -rn "hermes\|pi_builder\|dispatcher" agent-platform/runtime/coding/` returns nothing | [ ] |

## Part 2 — "workspace, network and budget ceilings are machine-proven"

| Ceiling | Evidence | Test | Status |
|---|---|---|---|
| Workspace | Real escape attempts (traversal, absolute path, symlink) against a real file; attempt raises AND target bytes unchanged | `tests/runtime/test_write_gate.py` (7 cases) | [ ] |
| Workspace | The disposable copy-in workspace is removed on every exit path, including exceptions | `tests/runtime/test_run_workspace.py::test_root_is_removed_when_the_body_raises` | [ ] |
| Network | Outbound TCP connect refused at the OS level from inside the container (`--network none`) — **requires this task's Docker CI job green**, not merely written | `tests/runtime/test_sandbox_boundaries_docker.py::test_outbound_tcp_connect_fails_at_the_os_level` | [ ] |
| Network | DNS resolution fails inside the sandbox | `tests/runtime/test_sandbox_boundaries_docker.py::test_dns_resolution_fails_inside_the_sandbox` | [ ] |
| Network | Host credentials structurally absent from the child process (both the client env and the container env) | `tests/runtime/test_subprocess_sandbox.py::test_child_env_is_allowlist_built_and_carries_no_credentials`, `tests/runtime/test_sandbox_boundaries_docker.py::test_host_credentials_are_absent_from_the_child_environment` | [ ] |
| Budget (call-count) | `BudgetExhausted` before any HTTP call; run blocked, no partial result | `tests/runtime/test_coding_loop.py::test_blocked_on_budget_exhausted_without_a_partial_success` | [ ] |
| Budget (sandbox executions) | Max sandbox executions per run refused past the cap | `tests/runtime/test_subprocess_sandbox.py::test_run_refuses_past_the_execution_cap` | [ ] |
| Budget (money) | **Not proven** — `BudgetGate` counts calls, not USD (spec's open assumption A3). Recorded here as a known gap, not silently closed. | — | N/A — gap, not a failure |

## Sign-off

- [ ] Every `[ ]` row above independently verified green by the plan owner — not trusted from an executor's own summary (per this repo's dispatch-verification rule).
- [ ] Task 14's manual `real_inference` run reported to Rikard, with the resulting diff, test output, and cost.
- [ ] This file's rows, once all checked, are never edited again — a later regression gets a NEW checklist that supersedes this one.
