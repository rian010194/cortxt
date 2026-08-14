# ADR-016: Agent Platform bounded context, InferencePort and provider-assurance principle

**Status:** Accepted  \
**Date:** 2026-08-13  \
**Deciders:** Rikard (operatör)  \
**Technical Story:** CORTXT F0/F1 beslutspaket godkänd 2026-08-13; övergång av målarkitekturen mot ADR-process (Del K beslut 8)

> **STATUS-AMENDMENT (2026-08-14):** ADR-016 är **Accepted** — motiverat av F0/F1-godkännandet och
> Codex oberoende review GODKÄND (2026-08-13), redan noterat i dess Validation, och på basis av att
> dess kärnbeslut (bounded context, InferencePort, provider-assurance dataklass→gate) är normativt.
> **Partiellt upphävt för reasoning/ per ADR-017:** vertikala slicet DM1–4 (PR #113, commit `09f1d8a`)
> bevisar behovet, så `agent-platform/reasoning/` är nu tracked/Accepted (ADR-017). `adapters/` och
> övriga `agent-platform/`-paket förblir Proposal/Untracked tills egna vertical slices. Övriga beslut i
> denna ADR står fast.

## Context

F0 (ADR-014) etablerar Cortxt som en leverantörsneutral agentplattform där användaren äger tillstånd/ reasoning/minne/verktyg/evidens/utveckling, med modeller och providers utbytbara. F1 (ADR-015) väljer wedge B (provider-/dataklassstyrd långvarig analys) och kräver en minimal provider-assurance-policy samt en InferencePort som låter samma agentkod byta mellan ≥2 godkända endpoints (första tekniska milstolpen).

Den nuvarande målarkitekturen (`docs/architecture/cortxt-agent-platform-target-architecture.md`, UNTRACKED proposal) och routing-paketet (`docs/architecture/beslutspaket-routing-malarkitektur-2026-08-10.md`, UNTRACKED proposal) beskriver vart arkitekturen ska utvecklas, men är inte godkänd baseline. Denna ADR tar beslut som för målarkitekturen vidare mot en ADR-process utan att godkänna hela plattformsbygget.

## Decision

1. **Agent Platform = bounded context.** Cortxt bygger en egen agentplattform inom det befintliga kontrollplanet. `agent-platform/` (supervisor, runtime, reasoning, state, memory, skills, tools, inference, profiles) och `adapters/` (inference, agent-runtime, tools, storage) behandlas som en ny bounded context/proposal. Kärnpaket får endast bero på interna portar och kontrakt; de får inte importera Hermes/Pi/Prime/InferX eller en specifik provider (repoinvariant). Hermes/Pi används under migration som adaptrar/fallback/benchmark, aldrig som dolda kärnberoenden.

2. **InferencePort (första tekniska milstolpen).** En providerneutral model-invocation-port byggs tidigt. Den normaliserar provider/exakt modellversion, messages + structured outputs, tool-calling, reasoning-inställningar, tokenanvändning, latency/timeout/cancellation, kostnad + cost-confidence, retries/felklassificering och dataklass/provider-eligibility. Agentkärnan beror endast på `InferencePort`; concrete providers lever bakom `adapters/inference/`. Exitkriterium: samma agentkod kan byta mellan ≥2 godkända endpoints utan ändring i reasoning-kärnan.

3. **Provider-assurance-princip (dataklass → gate).** En minimal policy som betingar providerval på dataklass:
   - L0 (offentlig/syntetisk): vilken godkänd provider som helst.
   - L1 (intern, ej känslig): ZDR + kryptering.
   - L2 (konfidentiell): DPA + subprocessors + hostingregion + incidentprocess + **avslutad** oberoende assurance (t.ex. SOC 2/ISO).
   - L3+ (personuppgifter/kritisk): ytterligare krav per bedömning.
   - `In progress`-assurance beskrivs aldrig som avslutad compliance.

4. **Provider-praxis (InferX).** InferX (model.inferx.net) är för närvarande **experimentell och inte godkänd för konfidentiellt material** (issues #64/#73/#74; primärkälla: `inferx.net/security`, SOC 2 Type II in progress target Q3 2026; GDPR/HIPAA in progress; DPA/subprocessors/incident ej publicerat). Före avslutad assurance får endast dataklass L0 användas hos InferX (t.ex. #74:s syntetiska pilot, 10 USD-tak). Övriga providers konsumeras bakom `adapters/inference/` med samma dataklassprövning.

## Consequences

### Positive
- Målarkitekturen får en föreslagen riktning (bounded context + InferencePort) som formellt kan antas via denna ADR-process, utan att åta sig hela plattformsbygget på en gång.
- Leverantörsneutralitet blir operativ: en port, många utbytbara adapters.
- Dataklass→gate-policyn skyddar konfidentiella data (InferX avvisas för L2+ tills avslutad assurance) och ger wedge B en förutsättning.

### Negative
- `agent-platform/` + `adapters/` förblir untracked scaffold tills ett vertikalt slice bevisar behovet (inga stabila interfaces före det).
- InferencePort + providerpolicy-policy är ett reellt bygge (Fas 1 i målarkitekturen); det är den första tekniska milstolpen, inte wedge-leverans i sig.

### Risks
- Att ADR:erna (014-016) smyger in ny/utökad scope — motverkas genom att varje ADR begränsas till just sitt beslut.
- Att gitignored lokalt evidens (`.hermes/codex/f0f1-*`) misstas för normativ källa — det är bevis, inte norm; normativt är dessa ADR:er + befintliga normativa kontrakt.
- Att frysta Project 4 återanvänds som aktiv roadmap — det görs inte; kommande Cortxt-arbete bör använda en ny planeringsyta.

## Alternatives Considered
1. **Ingen egen platform (enbart kontrollplan ovanpå Hermes/Pi)** — förkastad: motsäger F0-ägarhypotesen och providerneutralitet.
2. **Bygg hela Agent Platform först (Fas 0-8)** — förkastad: för stor, visionsteaterrisk; wedge B-bevis behöver inte hela plattformen.
3. **Bounded context + InferencePort först, wedge B som validering** — vald: minsta korrekta framsteg som förankrar beslut och ger första tekniska milstolpen.

## Validation
- [x] F0/F1 godkänt; Codex oberoende review GODKÄND (runda 2, 2026-08-13).
- [ ] InferencePort-adapter med ≥2 godkända endpoints (Exitkriterium Fas 1) verifierad.
- [ ] Provider-assurance-policyn (dataklass→gate) versionslåst och granskad.
- [x] `agent-platform/` och `adapters/` scaffold motiveras av ett vertikalt slice innan stabila interfaces. **AMENDMENT (2026-08-14, ADR-017):** vertikala slicet reasoning-kärnan DM1–4 är i `main` via PR #113 (commit `09f1d8a`); `agent-platform/reasoning/` är därmed **tracked/Accepted** per ADR-017. `adapters/` och övriga `agent-platform/`-paket förblir untracked/Proposal tills egna vertical slices. Originalbeslutet raderas inte — det upphävs partiellt genom ADR-017.
- [ ] Dokumentation (docs/authority-map) uppdaterad så ADR:erna är normativa.

## Expiry/Review Trigger
- Review by: 2026-11-13
- Trigger: en andra inferenceprovider godkänns, InferX återvärderas efter färdig assurance, eller wedge B-validering ändrar providerbehovet.
