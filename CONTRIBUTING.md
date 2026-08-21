# Contributing to Cortxt

Thanks for your interest in Cortxt. This project is built and maintained
solo, in the open, as a working portfolio. Contributions are welcome when
they respect the project's operating model.

## Before you start

Cortxt is a provider-neutral platform for creating, steering, resuming, and
verifying long-running AI work under **human mandate**. Two principles shape
everything here:

- **The operator is the source of truth for scope, evidence, and approval.**
  No agent, contributor, or automation approves, merges, deploys, publishes,
  or closes its own work.
- **No secrets, customer documents, prompts, or model reasoning** go into the
  repository or its GitHub issues. If you worked with a proof environment or
  a customer, keep that material out of the repository.

Read the following before proposing a change:

1. [`AGENTS.md`](AGENTS.md) — operating boundaries
2. [`docs/agents/current-operating-model.md`](docs/agents/current-operating-model.md)
3. [`docs/architecture/dispatch-contract.md`](docs/architecture/dispatch-contract.md)
4. [Accepted ADRs](docs/adr/README.md)

## Ways to contribute

- **Report a bug or suggest an idea** — open a GitHub issue with a clear
  title and a structured body.
- **Improve documentation** — typo fixes, clearer prose, better examples.
  All repository documentation is written in **English**.
- **Implement a change** — open a pull request. Keep the scope of each PR
  small and focused.

## Issue and PR conventions

- Use the issue templates when they apply.
- An issue carries exactly one `workflow:*` label at a time; `workflow:ready`
  on an issue is not execution approval unless scope, acceptance criteria,
  worker role, and runtime limits are present.
- Pull requests are not a request or triage surface; propose durable work as
  an issue first.
- Keep commit messages in the conventional-commits style used throughout this
  repository.

## Architecture Decision Records (ADRs)

Architecturally significant decisions are recorded in `docs/adr/` using the
[template](docs/adr/template.md). Accepted ADRs are append-only registers:
their **Status** line is normative, and later changes amend rather than
rewrite accepted decisions. When you change an Accepted ADR, add a row to
[`docs/architecture/REVIEW_LOG.md`](docs/architecture/REVIEW_LOG.md) in the
same pull request (the `adr-doc-currency` CI gate enforces this).

## Review process

- A maintainer (currently the solo operator) reviews pull requests.
- High-risk or architectural changes may receive an independent, read-only
  review before approval.
- Do not expect an automated bot to approve your work. Human review is the
  final gate.

## License

By contributing you agree that your contributions are licensed under the
[Apache License 2.0](LICENSE).
