# ADR-012: Disaster Recovery for Profiles, Skills, and Memory

**Status:** Proposed — **SUPERSEDED (2026-08-14, ADR-017)**  
**Date:** 2026-08-03  
**Deciders:** Rikard  
**Technical Story:** Addresses W-10 (No disaster recovery/backup)

> **LEGACY NOTICE (2026-08-14):** This ADR predates F0/F1 and provided backup/restore of `~/.hermes/` but
> no export for interoperability/portability. Under the F0 ownership hypothesis (ADR-014) and the
> provider-neutral architecture, the portability question shifts toward Cortxt-owned ports/state
> (ADR-016/017). Its content is historical reference, not valid current authority.

## Context
No backup/export mechanism exists for:
- Hermes profiles (config, skills, memory)
- Skills (manifests, versions, interfaces)
- Shared memory (SQLite databases)
- Receptionist credentials (vault)

Loss of `~/.hermes/` = complete environment loss.

## Decision
Implement disaster recovery with:
1. **Profile Export/Import CLI** (`profile_cli.py export/import`)
2. **Skill Version Pinning** (manifest `version` + `compatibility` fields)
3. **Daily Memory Snapshots** (cron job → compressed archive)
4. **Credential Vault Backup** (encrypted export of credential-manager)

### Snapshot Schedule
| Data | Frequency | Retention | Location |
|------|-----------|-----------|----------|
| Profiles | Daily | 30 days | `~/.hermes/backups/profiles/` |
| Skills | On change | 90 days | `~/.hermes/backups/skills/` |
| Shared Memory | Daily | 7 days | `~/.hermes/backups/memory/` |
| Credentials | Weekly | 90 days | `~/.hermes/backups/credentials/` |

### Restore Procedure
```bash
# Full restore
hermes-profile import --from ~/.hermes/backups/profiles/2026-08-03.tar.gz
hermes-skill import --from ~/.hermes/backups/skills/2026-08-03.tar.gz
hermes-memory restore --from ~/.hermes/backups/memory/2026-08-03.db.gz
```

## Consequences

### Positive
- Recoverable from catastrophic `~/.hermes/` loss
- Versioned skills enable rollback
- Daily snapshots limit data loss to 24h

### Negative
- Storage overhead (~100MB/day)
- Encryption key management for credentials
- Restore procedures need regular testing

### Risks
- Credential backup encryption key loss = unrecoverable secrets
- Snapshot corruption undetected until restore needed

## Validation
- [ ] Profile export/import CLI works end-to-end
- [ ] Daily snapshot cron job configured
- [ ] Restore tested on clean environment
- [ ] Credential backup encryption verified

## Expiry/Review Trigger
- Review by: 2026-11-03
- Trigger: If `~/.hermes/` size > 5GB or restore test fails