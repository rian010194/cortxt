# ADR-011: Model Router for Coordinator Fallback

Status: proposed
Authority: architecture decision process
Last verified: 2026-08-11

**Status:** Proposed  
**Date:** 2026-08-03  
**Deciders:** Rikard  
**Technical Story:** Addresses W-01 (Coordinator model lock-in)

## Context
The `coordinator` profile is hardcoded to Nemotron-3-ultra via OpenRouter (free tier). This creates:
- Single point of failure if model unavailable
- No cost guardrails (free tier ≠ zero cost forever)
- No model diversity for different task types

## Decision
Implement a `model-router` skill that:
1. Provides fallback chain: Nemotron-3-ultra → Kimi (Moonshot) → GPT-4o-mini → local
2. Enforces per-dispatch cost ceiling from dispatch contract
3. Routes based on task classification (planning vs research vs synthesis)
4. Exposes model selection via receptionist-hermes config

## Consequences

### Positive
- Resilience: Automatic fallback on model failure
- Cost control: Per-dispatch ceiling enforced
- Flexibility: Right model for right task

### Negative
- Added complexity in coordinator dispatch logic
- Need to maintain model capability matrix
- Free tier models may have rate limits

### Risks
- Fallback model may produce lower quality plans
- Cost tracking across providers inconsistent

## Validation
- [ ] Model router skill implemented
- [ ] Fallback chain tested with simulated failures
- [ ] Cost ceiling enforcement verified
- [ ] Documentation updated

## Expiry/Review Trigger
- Review by: 2026-11-03
- Trigger: If any fallback used >10% of dispatches in 30 days
