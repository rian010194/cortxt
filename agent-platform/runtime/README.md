# Agent Runtime

Status: scaffold

The Agent Runtime is Cortxt's future provider-neutral agent harness. It owns:

- the agent loop;
- context assembly and compaction;
- profile loading;
- model invocation through the inference port;
- tool requests through the tool port;
- session persistence;
- structured outputs and trajectory events.

It must not execute arbitrary commands in its own process or approve its own
external effects.

