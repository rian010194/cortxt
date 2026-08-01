# AI Workspace control plane

Private control plane, harness experiments, and vertical-package testbed for
the AI Workspace.

## Repository boundaries

- `control plane` owns task state, routing, approvals, and operator-visible
  status. GitHub Issues and Projects currently provide this layer.
- [`harness/`](harness/README.md) defines how approved work is isolated,
  executed, observed, and evaluated.
- [`verticals/`](verticals/README.md) contains domain packages that declare
  what work should be done, without owning runtime infrastructure.
- [`experiments/`](experiments/) contains runtime candidates that have not yet
  been promoted into the harness.
- [`contracts/`](contracts/README.md) is reserved for versioned interface
  schemas once real execution data has stabilized their fields.

Architecture:

- [Runtime and evaluation harness](docs/architecture/runtime-and-evaluation-harness.md)
- [Vertical package contract](docs/architecture/vertical-package-contract.md)

Real customer inputs and run outputs must remain outside Git history in an
explicitly approved, isolated run workspace.
