---
title: Evidence Gate
description: The control point that verifies a result and its evidence are correlated, sufficient and valid before the result can reach a human decision.
---

This page is documentation, not research and not a decision. It summarises the
[dispatch contract](https://github.com/rian010194/cortxt/blob/main/docs/architecture/dispatch-contract.md)
and the [work launcher](https://github.com/rian010194/cortxt/blob/main/docs/agents/work-launcher.md).
Where this page and the repository disagree, the repository wins.

## What it is

The Evidence Gate is a control point between an execution and the human
decision it feeds. It verifies that a claimed result and its evidence are
**correlated** — provably about the same run — **sufficient** for the claimed
outcome, and **valid**, meaning checkable by someone other than the producer.
Its purpose is that self-reported status is never relayed onward as success.

The gate is not the human decision. It decides what is allowed to reach that
decision.

## What it checks

For a **mutating** run — one whose approved mandate expects it to change the
repository — the gate requires a landed commit that:

- exists in the repository;
- correlates to the run's `run_id`, `issue_id` and `request_id`, all three of
  which are required in the result envelope, so a check cannot be skipped by
  omitting a field;
- is reachable from the run's registered isolated `work/<run_id>` branch;
- was committed **strictly after** the second in which the run was claimed —
  git timestamps carry one-second resolution, so a commit inside the claim's own
  second cannot be ordered against it and is refused rather than assumed;
- carries a DCO `Signed-off-by:` trailer; and
- touches only what the approved artifact scope permits.

The approved artifact scope resolves **fail-closed**: a run carrying no usable
artifact policy is blocked rather than treated as permitting everything, and an
absolute path, a drive letter or a `..` segment is refused rather than silently
skipped.

## What happens when it refuses

A missing, unverifiable or non-correlating commit converts a claimed
`succeeded` into a structured `blocked`. It is never relayed onward as success.

A terminal worker status also never moves the workflow state by itself. The
order is: the worker reaches a terminal candidate status; the Evidence Gate
verifies the result; a complete and idempotent review submission is written to
the session store; and only then does review sync apply the state transition.
Missing or incorrect evidence blocks the transition.

## Documented versus in progress

The gate described above is contractually defined and implemented for the
mutating-delivery shape. The wider idea of a per-profile **evidence contract** —
a versioned rule binding a work shape to the proof it requires — is
[ADR-045](https://github.com/rian010194/cortxt/blob/main/docs/adr/045-execution-policy-profiles-and-evidence-contracts.md),
which is **Proposed, not Accepted**. Profile families beyond the proven
mutating-delivery shape are direction, not current capability.
