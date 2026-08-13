# Supervisor

Status: scaffold

Owns lifecycle state for approved root and child runs:

- session creation and resume;
- child admission and parent correlation;
- budget allocation within the root ceiling;
- dependency joins;
- heartbeat, timeout, cancellation, and recovery;
- terminal result integration.

The Supervisor does not own task scope, operator approval, model execution, or
sandbox policy. Those remain in the control plane, Agent Runtime/Inference
Gateway, and execution harness respectively.

