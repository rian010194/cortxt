# Security Policy

## Reporting a vulnerability

Cortxt is a small, solo-maintained open-source project. If you find a
security vulnerability, please report it privately so it can be fixed before
it is disclosed.

- **Preferred:** email the maintainer at the address listed on the GitHub
  profile, or open a **private advisory** via
  *Security → Report a vulnerability* on the repository.
- Do **not** open a public issue for a vulnerability.
- Include a description of the issue, affected versions/files, and a minimal
  reproduction if possible.

You should receive an acknowledgment within a few days. Please allow time for
a fix before public disclosure.

## Scope

This policy covers the repository contents (source, scripts, and documented
deployment surfaces). It does **not** cover third-party services or runtimes
that Cortxt talks to (model providers, agent runtimes, cloud hosts), which
have their own security reporting processes.

## What Cortxt does not store

Cortxt is designed so that **secrets, customer documents, prompts, and model
reasoning never enter the repository or its GitHub issues**. If you encounter
any committed secret, token, key, or private document in this repository,
report it as a vulnerability so it can be removed from history.

## Expectations

- Secrets are read only from the environment or the operating system's
  credential manager, never printed or committed.
- Real customer inputs and run outputs live in isolated, explicitly approved
  workspaces outside Git history.
- The threat model for the centralized credential broker is documented in
  [`docs/security/credential-broker-threat-model.md`](docs/security/credential-broker-threat-model.md).
