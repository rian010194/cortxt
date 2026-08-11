# Documentation authority map

Status: active
Authority: repository governance
Last verified: 2026-08-11

This is the only documentation index. When documents conflict, use the first
applicable authority below and stop for reconciliation rather than blending claims.

## Normative

1. [`AGENTS.md`](../AGENTS.md) — repository boundaries and required orientation.
2. [Current operating model](agents/current-operating-model.md) — verified present-day baseline.
3. [Dispatch contract](architecture/dispatch-contract.md) — request, run, result, and state contract.
4. [Runtime and evaluation harness](architecture/runtime-and-evaluation-harness.md) — platform/vertical boundary.
5. [Vertical package contract](architecture/vertical-package-contract.md) — vertical package boundary.
6. [Issue tracker](agents/issue-tracker.md) — GitHub workflow conventions.

## Operational

Operational procedures live in [`operations/`](operations/). They implement the
normative documents but cannot override them. The Hermes dispatch runbook is
[here](operations/hermes-dispatch-runbook.md).

## Decisions

Accepted and proposed architectural decisions live in [`decisions/`](decisions/).
Their status is local to each decision; proposed decisions are not operating facts.

## Reference

Stable terminology is in the [glossary](reference/glossary.md). Architecture and
skill inventories are reference material and must be reverified before use.

## Historical evidence

Audits, handoffs, superseded domain claims, and session records live in
[`archive/`](archive/). They are never source of truth. The canonical repository
cleanup record is [the reconciliation matrix](reconciliation/repository-cleanup-2026-08-11.md).
