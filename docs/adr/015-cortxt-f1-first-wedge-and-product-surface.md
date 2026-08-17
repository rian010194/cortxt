# ADR-015: Cortxt First Wedge and Product Surface (F1)

**Status:** Accepted  \
**Date:** 2026-08-13  \
**Deciders:** Rikard (operatör)  \
**Technical Story:** CORTXT F0/F1 beslutspaket, godkänd 2026-08-13 efter oberoende Codex-review (runda 2 GODKÄND); evidens `.hermes/codex/f0f1-decision-packet-2026-08-13.md` (gitignored lokalt)

> **STATUS-AMENDMENT (2026-08-16, ADR-020):** proof environment-namnet nedan ("Norcom/CSL") ska läsas
> som **"proof environment B"** i alla nya referenser — terminologiredaktion inför repo-publicering,
> sakbeslutet (Wedge B) nedan är oförändrat och kvar Accepted.

## Context

F0 (ADR-014) är godkänd. Nästa beslut är den första wedge: den minsta sammanhängande produktupplevelsen som löser ett verkligt problem, kan användas av Rikard, kan lämnas över till en andra användare, demonstrerar en del av den större visionen, inte kräver att hela Agent Platform byggs först, och producerar evidens som avgör nästa investering.

Fyra tydligt skilda kandidater jämfördes (Del F i beslutspaketet):
- A: developer coding workflow
- B: provider-/dataklassstyrd långvarig research- och analysesession (granskbar "förmåga")
- C: compliance/gap-analysis workflow
- D: kombinerad developer workflow (coding + research + policy)

## Decision

**F1 — Bästa balans: Wedge B.** Den första wedge är en provider-/dataklassstyrd långvarig research- och analysesession som en granskbar "förmåga", levererad genom en **repository-native + CLI hybrid**, med **Norcom/CSL som proof environment**.

**Produktyta:** repository-native + CLI (primärt); webb/cockpit används inte som första yta (pausad legacy, se premiss 11).

**Distinktioner (första produkt ≠ wedge ≠ resa ≠ milstolpe):**
- Första produkt (F0/F1-beslut): avgränsat värdeerbjudande (Balanserad vision + wedge B).
- Första wedge: provider-/dataklassstyrd långvarig analys (denna ADR).
- Första användarresa: 12-steg (trigger → … → levererat resultat) i beslutspaketet Del G.
- Första tekniska milstolpen (ej produkt): Inference Gateway / Fas 1 i målarkitekturen — se ADR-016.

**Rekommendationen baserades på kvalitativa avvägningar (inte enbart poäng):** wedge B demonstrerar ägarhypotesen (providerneutralitet, återupptagbarhet, evidens, mänskligt mandat) utan att reducera Cortxt till coding (A) eller compliance (C), och är den minsta sammanhängande upplösning som inte kräver hela Agent Platform. Wedge A ger snabbast signal men coding-marknaden är mättad (hypotes, kräver separat validering) och reducerar Cortxt till en coding-agent. Wedge C är strategiskt differentierande men riskerar domänlåsning och långsam reglerad säljcykel; det är ett naturligt andra steg (via Norcom/CSL-bevis), inte det första.

## Consequences

### Positive
- Bevisar kärnvärdet (ägt tillstånd + providerneutralitet + evidens + verifiering) innan plattformsbygge.
- Norcom/CSL används som verklig proof-miljö utan att bli hela produkten.
- Valideringsplanen (Del H) är definierad: T1 (Rikard), T2 (annan dev), T3 (Norcom/CSL-generaliserbarhet), T4 (providerneutralitet), T5 (provider-assurance). Inga kunddata.

### Negative
- Provider-assurance-policyn är ännu ofullständig — wedge B är beroende av en minimal dataklass→assurance-policy.
- Långvarig research/analyse kräver supervisor/resume som idag saknas i baseline (proposal).

### Risks
- Providerpolicy och dataklassgrupper blir flaskhals; InferX är inte godkänd för konfidentiellt material före färdig assurance (ADR-016).
- Att wedge B överlappar A/C och blir för stor — motverkas av tydliga AC och den minsta sammanhängande definitionen.

## Alternatives Considered
1. **Wedge A (developer coding)** — ej vald som första: hypotes om mättad marknad (kräver separat validering), lägst differentiering, reducerar Cortxt till coding-agent.
2. **Wedge C (compliance/gap)** — ej vald som första: stark differentiering men domänlåsnings- och säljcykelrisk; bättre som andra steg via Norcom/CSL.
3. **Wedge D (kombinerad)** — ej vald: för komplext och för stort för v0.1.
4. **Wedge B** — vald: bästa balans mellan signal, differentiering och bevis av ägarhypotesen.

## Validation
- [x] Codex oberoende review GODKÄND (runda 2, 2026-08-13).
- [x] Rikards godkännande registrerat (2026-08-13).
- [ ] Wedge B-validering T1–T5 genomförd (Del H) innan produktkod.
- [ ] Provider-assurance-policyn (minimal, dataklass→gate) etablerad som förutsättning.

## Expiry/Review Trigger
- Review by: 2026-11-13
- Trigger: någon av T1–T5 falsifieras, eller en observerad användarefterfrågan pekar på en annan wedge.
