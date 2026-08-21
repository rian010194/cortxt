# Cortxt Style Guide

**Version:** 0.1  
**Status:** Draft  
**Language:** English (primary)  
**Last updated:** 2026-08-03

---

## 1. Language & Tone

### 1.1 Primary language
- **Internal conversations, documentation, handoffs:** English
- **GitHub issues, PR descriptions, external documentation:** English
- **Bilingual documents (decision briefs, handoffs):** English only — translate any legacy Swedish content as it is touched

### 1.2 Tone by document type

| Document type | Tone | Example |
|---------------|------|---------|
| **Technical documentation** | Precise, active voice, no hedging | "The system validates input", not "The system should validate input" |
| **Blog/article** | Conversational, authoritative | "We discovered that..." not "It was discovered that..." |
| **PR description** | Technical, concise | "Fix bug in auth flow", not "This PR fixes a bug..." |
| **Decision brief** | Formal, decisive | "Decision: We choose X. Background: Y. Consequence: Z." |
| **Handoff** | Complete, unambiguous | "Done: X. Remaining: Y. Blockers: Z." |
| **Email** | Professional, action-oriented | "Subject: X. Question: Y. Deadline: Z." |

### 1.3 English-specific rules
- **Use "you" (second person) consistently** — no formal/informal address distinction
- **Compound terms:** write established English compounds consistently, e.g. "agent architecture", "roadmap", "follow-up", "dispatch contract"
- **English technical terms used as-is** when they are standard: "API", "CLI", "JSON", "YAML", "HTTP", "REST", "GraphQL", "WebSocket", "OAuth", "JWT", "SQL", "NoSQL", "CI/CD", "PR", "Issue", "Deploy"
- **No "AI" as a noun** — use "agent", "model", "system"

---

## 2. Formatting

### 2.1 Headings
- **Sentence case:** "Create new agent" (not "Create New Agent")
- **No trailing period** after a heading
- **Maximum 3 levels** (H1, H2, H3)

### 2.2 Code
- **Inline code:** backticks `` `code` ``
- **Code blocks:** with language tag (` ```python `, ` ```yaml `, ` ```bash `)
- **No code** in running text without backticks

### 2.3 Lists
- **Parallel structure** — all items share the same grammar
- **Oxford comma** (serial comma) — "A, B, and C"
- **Bulleted list** for unordered items, **numbered** for sequential steps

### 2.4 Links
- **Descriptive text** — not "here", "this link"
- **Example:** `[GitHub Issues API](https://docs.github.com/en/rest/issues)` not `[here](...)`

### 2.5 Tables
- **Header row** always
- **Alignment** for numeric columns (right)
- **No empty cells** — use "N/A" or "—"

---

## 3. Terminology (Glossary)

| Term | Use | Avoid |
|------|-----|-------|
| Agent | ✅ | bot, AI, assistant |
| Skill | ✅ | plugin, module, extension |
| Profile | ✅ | persona, mode, role |
| Dispatch | ✅ | trigger, invoke, launch |
| Vertical | ✅ | domain package, domain |
| Receptionist | ✅ | gateway, proxy, adapter |
| Dispatch contract | ✅ | — |
| Result envelope | ✅ | — |
| BVC | ✅ | behaviour validation contract |
| Shared memory | ✅ | workspace memory |
| Pi Builder | ✅ | Pi, builder container |
| Coordinator | ✅ | orchestrator (architecture context only) |

---

## 4. Writing Process (Writer Skill Pipeline)

1. **Analyze** — audience, purpose, key message
2. **Outline** — structure, headings, evidence mapping
3. **Draft** — first version, completeness over polish
4. **Edit** — active voice, concrete nouns, short sentences, tone matching, fact-check
5. **Polish** — formatting, links, metadata, SEO (if blog)
6. **Review** — self-check + optional external review

### 4.1 Editing rules (Humanizer)
- **Remove hedging:** "It is important to note that" → (remove)
- **Passive → Active:** "The error was detected by the system" → "The system detected the error"
- **Vary word choice:** do not use "use" three times in a row
- **Vary sentence structure:** question, short sentence, leading clause
- **Remove AI-isms:** "it is important to note", "in light of the fact that", "at this juncture"

---

## 5. Document Types & Templates

| Type | Template | Audience | Length |
|------|----------|----------|--------|
| **Docs** | `templates/docs.md` | Developers/Operators | Medium |
| **Blog** | `templates/blog.md` | Public/Technical | Long |
| **PR description** | `templates/pr-description.md` | Reviewers | Short |
| **Release notes** | `templates/release-notes.md` | Users/Operators | Medium |
| **Changelog** | `templates/changelog.md` | Developers | Medium |
| **Decision brief** | `templates/decision-brief.md` | Stakeholders | Short |
| **Handoff** | `templates/handoff.md` | Next agent/Operator | Medium |
| **Email** | `templates/email.md` | Recipient | Short |
| **Social** | `templates/social.md` | Public | Short |

---

## 6. Quality Requirements (Quality Gates)

- [ ] **Word count** within ±20% of target
- [ ] **Readability** (Flesch-Kincaid) appropriate for the audience
- [ ] **All links** work (200 OK)
- [ ] **No unverified claims** (fact-check = passed)
- [ ] **Tone match** ≥ 80% vs. requested tone
- [ ] **Style-guide compliance** ≥ 90%
- [ ] **No AI-isms** (humanizer pass)

---

## 7. Examples

### 7.1 Decision Brief
```markdown
# Decision: Agent Architecture — Receptionist Pattern

## Decision
We use the receptionist pattern for all external system integrations.

## Background
The current architecture has direct API calls from agents → hard to maintain.

## Consequences
+ Single point of change at API breaks
+ Centralized auth/token handling
- Extra abstraction layer

## Next Steps
1. Implement credential manager
2. Migrate 6 receptionists
```

### 7.2 PR description
```markdown
## Summary
Fix auth token refresh in receptionist-base.

## Motivation
Tokens were not renewed proactively → 401 errors during long runs.

## Changes
- Added proactive refresh at 80% TTL
- Added retry logic on 401

## Testing
- Unit tests: pass
- Integration test against Notion: pass

## Related
- Issue #42
- Docs updated
```

---

## 8. Tools & Validation

| Tool | Purpose |
|------|---------|
| `humanizer` skill | Strip AI-isms, add a human voice |
| `writer` skill | Full pipeline: analyze → outline → draft → edit → polish → review |
| Link validation | All external links return 200 OK |
| Fact-check | All claims verified against sources |

---

## 9. Version History

| Version | Date | Changes |
|---------|------|---------|
| 0.1 | 2026-08-03 | Initial version |

---

*This style guide is a living document — update it when the architecture or processes change.*
