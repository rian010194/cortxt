# Contracts

This directory will contain versioned, domain-neutral schemas exchanged among
the control plane, harness, vertical packages, and reviewers.

Candidate contracts include task, run, artifact, review, and approval records.
They are intentionally not created yet: fields and lifecycle rules must first
be validated by real runs. Contracts must never contain provider credentials,
customer documents, or vertical-specific conclusions.

See [Vertical package contract](../docs/architecture/vertical-package-contract.md).
