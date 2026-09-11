---
title: Request digests
description: Why an approved execution configuration is identified by the digest of its content rather than by a name that points at it.
---

This page is documentation, not research and not a decision. It summarises
[ADR-046](https://github.com/rian010194/cortxt/blob/main/docs/adr/046-versioned-request-digest.md)
and the [dispatch contract](https://github.com/rian010194/cortxt/blob/main/docs/architecture/dispatch-contract.md).
Where this page and the repository disagree, the repository wins.

## What a request digest is

A request digest is an identifier for an approved execution configuration. It
is computed by the server over the *semantic content and immutable revision* of
that configuration — a fixed, versioned field set — rather than over a name
that points at it. The `request_id` carried by a dispatch request is such a
digest.

## Why it matters

**Binding.** A name survives every change to the thing it names. If a
confirmation bound a name, then repointing a model binding, changing a cost
class, or moving a binding from a pinned profile to an environment variable
could each occur without the confirmation noticing — and a mandate could end up
authorising something other than what the operator approved. Binding the digest
instead means the confirmation binds the configuration as it actually was when
the operator read it.

**Idempotence and staleness.** Identical content canonicalises to an identical
digest, and a material change produces a different one. A change to the
resolved execution configuration after preview — or after confirmation but
before the claim — therefore changes the digest, and it is refused as
**stale** before any claim, Run or worktree is created. A confirmation is never
silently spent on a different mandate than the one that was read.

**Independent review.** A digest derived from content can be recomputed by
someone who was not the producer. A reviewer can therefore check that the
configuration behind a result is the configuration that was approved, without
having to trust the producer's description of it.

## What is deliberately not bound

Binding cosmetic or post-hoc values would convert an irrelevant change into a
spurious re-confirmation, which trains operators to re-confirm without reading
— a worse failure than the one the binding exists to prevent. Display strings,
credential and endpoint values, environment-derived volatile fields, and
post-hoc observations such as timestamps, `run_id` and token counts are
therefore excluded. Only the **names** of the non-secret routing variables
cross into the bound binding-source field; never their values.

## Documented versus in progress

The `request_id` digest exists in the dispatch request today. ADR-046 adopts
the **versioned** digest (`dispatch.request.v2`) as the contract direction, and
since M2 the live OS confirm/launch path binds to v2; the v1 reader and builder
remain available for callers that select them explicitly. Worker-side
invocation enforcement — re-reading a mutable provider or model value at invoke
time — is tracked separately and is **not** part of that boundary. This page
does not claim it is closed.
