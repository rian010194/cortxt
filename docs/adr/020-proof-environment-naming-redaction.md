# ADR-020: Proof environment naming — redact product/partner name from public surface

**Status:** Accepted  \
**Date:** 2026-08-16  \
**Deciders:** Rikard (operator)  \
**Technical Story:** Repo publication (rian010194/cortxt going public); ADR-014/015 use an internal
proof-environment identifier for Wedge B that was not cleared for public exposure — it may become its own
internal/launched tool, not a third-party customer name.

## Context

ADR-014 (F0) and ADR-015 (F1) name the proof environment with an internal identifier
for the wedge B validation (T3). At repo publication this was flagged: the identifier is searchable in two approved
decision documents as well as in three GitHub issues (#101, #116, #124 — already edited 2026-08-16) and one merged
PR (#100 — handled separately).

The decision content in ADR-014/015 (F0 vision, Wedge B choice) is not questioned — it is still correct
and Accepted. The only problem is that a specific named identity appears on a surface that becomes public, before
the owner has decided whether the name should be internal or launched.

Per this repo's rule, decision documents (the record) are never rewritten retroactively — if something is wrong, a
new document that supersedes is written. This is not "the decision was wrong", but a bounded terminology redaction:
ADR-014/015 remain Accepted and normative for their substance; only the identifier's visibility changes
going forward.

## Decision

From this ADR onward, the proof environment for wedge B is referred to as **"proof environment B"** (short:
**PE-B**) in all new and future documents, issues, and communication — not the earlier name.

ADR-014 and ADR-015 remain unedited and Accepted for their decision. Each file gets a
STATUS-AMENDMENT notice (the same pattern as ADR-016/017) pointing here, so that a reader who encounters the
old name understands that it should be read as "proof environment B" going forward.

This document, GitHub issues #101/#116/#124 and PR #100 (if the owner decides) are the only places where a
historical reference to the former identifier remains in a controlled way; new artifacts use only PE-B.
(2026-08-22 public-readiness cleanup: the former identifier is removed from ADR-014/015/020/021 and the ADR
index so that no tracked public surface reproduces it; ADR-020's decision and record rule remain.)

## Consequences

### Positive
- The terminology is unambiguous going forward without breaking the record rule (ADR-014/015 untouched).
- The only product-name exposure that remains is in the two historical ADR files themselves (not
  issues/PRs, which have already been edited) — a reader who opens exactly those files sees the old name, but
  the README/issue surface and all searchable front surface do not.

### Negative
- The name is still technically readable by anyone who opens `docs/adr/014-*.md` or
  `docs/adr/015-*.md` directly, or `git log`/`git blame`. This is not a complete scrub — only
  editing the files in place (a deliberately considered alternative, not this one) would achieve that, at the cost
  of breaking the record rule.

### Risks
- If the name is later confirmed to be sensitive at a level requiring complete removal (e.g. a confidentiality
  agreement), this ADR is not enough — then an explicit decision to break the record rule for
  exactly ADR-014/015 is required, or BFG/git-filter-repo history cleaning before any publication.

## Alternatives Considered
1. **Edit ADR-014/015 directly** — rejected: breaks the record rule without the decision content
   actually being wrong.
2. **Leave the name visible in all documents** — rejected: exposes an undecided product name in public
   decision documents without the owner having taken a position.
3. **Terminology amendment via a new ADR (chosen).**

## Validation
- [x] ADR-014/015 received a STATUS-AMENDMENT notice pointing here.
- [x] docs/adr/README.md updated with ADR-020.
- [ ] PR #100 handled separately (waiting on owner decision).

## Expiry/Review Trigger
- Review by: 2026-11-16
- Trigger: the owner decides the name's final publicity status (launched tool vs. permanently internal),
  or the repo is flipped public without this decision being executed.
