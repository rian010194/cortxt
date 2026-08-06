# Cortxt Style Guide

**Version:** 0.1  
**Status:** Draft  
**Language:** Swedish (primär), English (sekundär)  
**Last updated:** 2026-08-03

---

## 1. Språk & Ton

### 1.1 Primärt språk
- **Interna samtal, dokumentation, handoffs:** Svenska
- **GitHub issues, PR-beskrivningar, extern dokumentation:** Engelska
- **Bilinguala dokument (decision briefs, handoffs):** Svenska + Engelska parallellt

### 1.2 Ton per dokumenttyp

| Dokumenttyp | Ton | Exempel |
|-------------|-----|---------|
| **Teknisk dokumentation** | Precis, aktiv röst, inget hedging | "Systemet validerar input" inte "Systemet bör validera input" |
| **Blogg/artikel** | Konversationell, auktoritativ | "Vi upptäckte att..." inte "Det upptäcktes att..." |
| **PR-beskrivning** | Teknisk, koncis | "Fixar bug i auth flow" inte "Denna PR fixar en bug..." |
| **Decision brief** | Formell, avgörande | "Beslut: Vi väljer X. Bakgrund: Y. Konsekvens: Z." |
| **Handoff** | Fullständig, odubbeltydlig | "Klarat: X. Kvar: Y. Blockers: Z." |
| **E-post** | Professionell, handlingsorienterad | "Ärende: X. Fråga: Y. Deadline: Z." |

### 1.3 Svenska specifika regler
- **Du-reform** internt, **Ni** externt (legacy)
- **Sammansatta ord:** "agentarkitektur", "färdplan", "uppföljning", "dispatchkontrakt"
- **Engelska termer OK** när standard: "API", "CLI", "JSON", "YAML", "HTTP", "REST", "GraphQL", "WebSocket", "OAuth", "JWT", "SQL", "NoSQL", "CI/CD", "PR", "Issue", "Deploy"
- **Ingen "AI" som substantiv** — använd "agent", "modell", "system"

---

## 2. Formattering

### 2.1 Rubriker
- **Sentence case:** "Skapa ny agent" (inte "Skapa Ny Agent")
- **Ingen punkt** efter rubrik
- **Max 3 nivåer** (H1, H2, H3)

### 2.2 Kod
- **Inline kod:** backticks `` `code` ``
- **Kodblock:** med språk-tag (` ```python `, ` ```yaml `, ` ```bash `)
- **Ingen kod** i löptext utan backticks

### 2.3 Listor
- **Parallel struktur** — alla punkter samma grammatik
- **Oxford-komma** (seriell komma) — "A, B, och C"
- **Punktlista** för oordnade, **numrerad** för sekventiella steg

### 2.4 Länkar
- **Beskrivande text** — inte "här", "here", "länk"
- **Exempel:** `[GitHub Issues API](https://docs.github.com/en/rest/issues)` inte `[här](...)`

### 2.5 Tabeller
- **Header-rad** alltid
- **Alignment** för numeriska kolumner (right)
- **Ingen tomma celler** — använd "N/A" eller "—"

---

## 3. Terminologi (Ordlista)

| Term | Använd | Undvik |
|------|--------|--------|
| Agent | ✅ | bot, AI, assistent |
| Skill | ✅ | plugin, module, extension |
| Profil | ✅ | persona, mode, role |
| Dispatch | ✅ | trigger, invoke, launch |
| Vertical | ✅ | domain package, domain |
| Receptionist | ✅ | gateway, proxy, adapter |
| Dispatch kontrakt | ✅ | dispatch contract |
| Result envelope | ✅ | result envelope |
| BVC | ✅ | behaviour validation contract |
| Shared memory | ✅ | workspace memory |
| Pi Builder | ✅ | Pi, builder container |
| Coordinator | ✅ | orchestrator (endast i arkitektur-sammanhang) |

---

## 4. Skrivprocess (Writer Skill Pipeline)

1. **Analyze** — målgrupp, syfte, nyckelbudskap
2. **Outline** — struktur, rubriker, evidens-mappning
3. **Draft** — första version, fullständighet över polish
4. **Edit** — aktiv röst, konkreta substantiv, korta meningar, ton-matchning, faktakoll
5. **Polish** — formatering, länkar, metadata, SEO (om blogg)
6. **Review** — self-check + valfri extern review

### 4.1 Redigeringsregler (Humanizer)
- **Ta bort hedging:** "Det är viktigt att notera att" → (ta bort)
- **Passiv → Aktiv:** "Felet upptäcktes av systemet" → "Systemet upptäckte felet"
- **Variera ordval:** inte "använda" 3 gånger i rad
- **Variera meningsstruktur:** fråga, kort mening, ledande sats
- **Ta bort AI-isms:** "det är viktigt att notera", "i och med att", "vid detta tillfälle"

---

## 5. Dokumenttyper & Mallar

| Typ | Mall | Målgrupp | Längd |
|-----|------|----------|-------|
| **Docs** | `templates/docs.md` | Utvecklare/Operatörer | Medium |
| **Blogg** | `templates/blog.md` | Publiken/Teknisk | Long |
| **PR-beskrivning** | `templates/pr-description.md` | Reviewers | Short |
| **Release notes** | `templates/release-notes.md` | Användare/Operatörer | Medium |
| **Changelog** | `templates/changelog.md` | Utvecklare | Medium |
| **Decision brief** | `templates/decision-brief.md` | Stakeholders | Short |
| **Handoff** | `templates/handoff.md` | Nästa agent/Operatör | Medium |
| **E-post** | `templates/email.md` | Mottagare | Short |
| **Social** | `templates/social.md` | Publiken | Short |

---

## 6. Kvalitetskrav (Quality Gates)

- [ ] **Ordantal** inom ±20% av mål
- [ ] **Läsbarhet** (Flesch-Kincaid) lämplig för målgrupp
- [ ] **Alla länkar** fungerar (200 OK)
- [ ] **Inga overifierade påståenden** (fact-check = passed)
- [ ] **Ton-match** ≥ 80% vs begärd ton
- [ ] **Stilguide-kompatibilitet** ≥ 90%
- [ ] **Inga AI-isms** (humanizer pass)

---

## 7. Exempel

### 7.1 Decision Brief (Bilingual)
```markdown
# Beslut: Agentarkitektur — Receptionist-mönster / Decision: Agent Architecture — Receptionist Pattern

## Beslut / Decision
Vi använder receptionist-mönster för alla externa systemintegrationer.

## Bakgrund / Background
Nuvarande arkitektur har direkta API-anrop från agenter → svårt att underhålla.

## Konsekvenser / Consequences
+ Enstaka ändringspunkt vid API-brott
+ Centraliserad auth/token-hantering
- Extra abstraktionslager

## Nästa steg / Next Steps
1. Implementera credential-manager
2. Migrera 6 receptionists
```

### 7.2 PR-beskrivning
```markdown
## Sammanfattning
Fixar auth token refresh i receptionist-base.

## Motivering
Token förnyades inte proaktivt → 401-fel vid långa körningar.

## Ändringar
- Lade till proaktiv refresh vid 80% TTL
- Lade till retry-logik på 401

## Testning
- Enhetstester: pass
- Integrationstest mot Notion: pass

## Relaterade
- Issue #42
- Docs uppdaterade
```

---

## 8. Verktyg & Validering

| Verktyg | Syfte |
|---------|-------|
| `humanizer` skill | Strip AI-isms, lägg till mänsklig röst |
| `writer` skill | Full pipeline: analyze → outline → draft → edit → polish → review |
| Länkvalidering | Alla externa länkar 200 OK |
| Faktakoll | Alla påståenden verifierade mot källor |

---

## 9. Versionshistorik

| Version | Datum | Ändringar |
|---------|-------|-----------|
| 0.1 | 2026-08-03 | Initial version |

---

*Denna stilguide är levande — uppdatera när arkitektur eller processer förändras.*