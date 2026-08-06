# ADR-013: Skill Composition Model

**Status:** Proposed  
**Date:** 2026-08-03  
**Deciders:** Rikard  
**Technical Story:** Addresses W-04 (No skill composition model)

## Context
Skills are currently a flat list loaded per profile. Issues:
- **Context bloat:** Profiles load 10-15 skills, most unused per task
- **Redundant auth:** Each receptionist independently manages auth
- **No reuse:** Common patterns (receptionist + credential-manager) not composable
- **Version conflicts:** Flat namespace makes dependency resolution hard

## Decision
Introduce **Skill Packs** — composable, versioned bundles of skills with shared dependencies:

### Skill Pack Structure
```yaml
# skill-pack.yaml
name: "receptionist-pack"
version: "0.1.0"
description: "All 6 receptionists + credential-manager + telemetry"
skills:
  - receptionist-base
  - receptionist-obsidian
  - receptionist-notion
  - receptionist-buzz
  - receptionist-hermes
  - receptionist-pi
  - receptionist-codex
  - credential-manager
  - telemetry
shared_dependencies:
  - credential-manager  # Single instance shared
  - telemetry          # Single instance shared
```

### Profile References Packs
```yaml
# profile manifest
skills:
  - pack:receptionist-pack@0.1.0
  - plan
  - github
  - hermes-agent
individual_skills: []  # Override specific skills if needed
```

### Composition Rules
1. **Shared deps instantiated once** per profile (singleton pattern)
2. **Pack version pins** all contained skill versions
3. **Pack inheritance:** `receptionist-pack` extends `base-pack` (credential-manager + telemetry)
4. **Conflict resolution:** Individual skill overrides pack skill (explicit wins)

## Consequences

### Positive
- Reduced context: Load only needed packs
- Single auth/telemetry instance per profile
- Atomic version updates via pack version
- Clear dependency graph

### Negative
- New abstraction layer (packs)
- Migration from flat skills required
- Pack registry management

### Risks
- Pack version conflicts if multiple packs share skills
- Circular pack dependencies possible

## Validation
- [ ] Skill pack manifest schema defined
- [ ] Pack loader implemented in Hermes
- [ ] Profile manifest updated to support packs
- [ ] Migration script for existing profiles

## Expiry/Review Trigger
- Review by: 2026-11-03
- Trigger: If profile skill count >20 or context window issues reported