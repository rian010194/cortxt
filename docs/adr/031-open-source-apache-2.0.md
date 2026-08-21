# ADR-031: Open-source license — Apache-2.0

**Status:** Accepted
**Date:** 2026-08-21
**Deciders:** Rikard (operatör)
**Technical Story:** GitHub issue rian010194/cortxt#182

## Context

Repot har sedan start varit "viewable, not open source" (all rights reserved;
visning och fork för personlig, icke-distribuerad referens tillåten, all annan
användning kräver skriftligt tillstånd). Inför produktpaketeringen — Cortxt som
en produkt andra utvecklare kan använda och bidra till — beslutade operatören
2026-08-21 att öppna källkoden. Licensvalet är utgångspunkten för all
distribution och för bidragsmodellen.

## Decision

**Cortxt licensieras under Apache License 2.0.** `LICENSE` ersätts med den
verbatim Apache-2.0-texten (copyright: Rikard Andersson). Alla spår av
"viewable, not open source" tas bort ur repo-dokumentationen.

Apache-2.0 valdes framför MIT för dess explicita patent-grant (§3) och
patent-retaliation-klausul — relevant för en plattform med routing- och
inference-kontrakt — samtidigt som den är kompatibel med de MIT-licensierade
skills som redan adopterats.

## Consequences

### Positive
- Andra utvecklare kan använda, modifiera och bidra; grund för distribution.
- Explicit patent-grant minskar bidragsgivares och användares patentrisk.
- Standardlicens med brett ekosystemstöd.

### Negative
- Copyright hålls hos en person; framtida bidrag kräver en tydlig
  DCO/CLA-policy (ej beslutad här).

### Risks
- Bidragsmodell (DCO/CLA) är ännu ospecificerad — följs upp separat innan
  externt bidrag tas emot i någon större skala.

## Alternatives Considered
1. **MIT** — enklast, men ingen uttrycklig patent-grant; vald bort till förmån
   för Apache-2.0:s patentskydd.
2. **AGPL-3.0** — copyleft som omfattar nätverksanvändning; för stark för en
   plattform som ska konsumeras bottom-up (ADR-023) utan att tvinga consumers
   till copyleft.
3. **Behålla "viewable, not open source"** — blockerar användning och bidrag;
   vald bort som oförenlig med produktmålet.

## Validation
- [x] `LICENSE` är verbatim Apache-2.0 (med copyright-rad).
- [x] Inga "viewable, not open source"-rester kvar i repo-dokumentationen.
- [x] ADR-index (`docs/adr/README.md`) uppdaterat med 031.

## Expiry/Review Trigger
- Review by: 2026-11-21
- Trigger: en bidrags-/CLA-policy införs, eller ett distributionsbeslut
  (packaging) kräver omprövning av licensformen.
