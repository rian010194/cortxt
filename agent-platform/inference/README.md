# Inference Gateway

Status: scaffold

Defines the Cortxt-owned provider-neutral boundary for model invocations:

- exact provider/model identity;
- messages and structured output;
- tool-call representation;
- streaming and cancellation;
- usage, cost, latency, and confidence;
- timeout, retry, and error taxonomy;
- data-class eligibility.

Provider implementations belong under `adapters/inference/`. Agent Runtime and
Reasoning packages must not import a provider SDK directly.

