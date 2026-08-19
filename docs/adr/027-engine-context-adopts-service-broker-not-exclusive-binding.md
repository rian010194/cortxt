# ADR-027: `EngineContext` antar service-broker-mönstret (Cordis §6.2), inte exclusive binding

**Status:** Accepted
**Date:** 2026-08-19
**Deciders:** Rikard (operatör), Claude Code (utkast)
**Technical Story:** Amenderar ADR-026 efter läsning av Cordis v4-papret "A Programming
Paradigm for Spatiotemporal Composability" (Shi, Zhang, Cui — Peking University / DeepSeek-AI),
nedladdat 2026-08-19 (`~/Downloads/paper.pdf`)

## Context

ADR-026 beslutade att ett nytt `EngineAdapter`/`EngineContext`-lager ska ersätta
`unified_cli.py`s hårdkodade if/elif-dispatch (rad 338–359), medan `route()`/
`engine_manifest.py` förblir orört. Skissen i ADR-026 beskrev registret informellt: en
`engine_id` mappar till exakt en registrerad adapter, och att byta implementation
innebär att avregistrera den gamla och registrera en ny.

Cordis-papret (§6.2, "Service Multiplexing") namnger och formaliserar precis den
skärningspunkt ADR-026 skissade — en coeffect-nyckel (hos oss: `engine_id`) som en eller
flera komponenter (adaptrar) kan binda till — och beskriver **två** mönster för det, inte
ett:

1. **Exclusive binding** — högst en implementation bunden åt gången; byte kräver
   unload+load av providern, vilket momentant stör varje konsument av nyckeln. Det är
   mönstret ADR-026 skissade implicit.
2. **Service broker** — en central broker injiceras av både providers *och* konsumenter.
   Flera providers samexisterar bakom samma nyckel; brokern routar varje anrop mellan
   dem. Konsumenten ser aldrig ett byte av bindning, bara brokern, så providerbyten
   stör inte konsumenten. Papret namnger tre kapabiliteter brokern ger "gratis": load
   balancing (flera providers, en routningspolicy), rolling updates (ny provider laddas
   parallellt, trafik flyttas gradvis, gamla unloadas när inga in-flight-anrop kvar) och
   cross-process invocation (varje process egen context, en RPC-brygga länkar dem).

Skillnaden är inte kosmetisk för vårt fall. `hermes_invoker.py`s docstring säger redan
att "route() picks 'hermes' as an engine_id, but picking isn't invoking" — och
`DEFAULT_MANIFESTS` (ADR-022) förväntar sig uttryckligen fler poster per motor-*familj*
över tid: flera Deepseek-profiler (t.ex. en snabb/billig och en verified/dyrare), eller en
primär motor med en explicit fallback när den förra är `degraded`. Med exclusive binding
blir varje sådant tillägg en ombindning av samma `engine_id`-nyckel — konsumenten
(`unified_cli.py` eller senare `route()`-anroparen) märker ett hack varje gång. Med en
broker registrerar sig flera adaptrar under samma nyckel utan att konsumenten någonsin
ser skarven.

## Decision

`EngineContext` (ADR-026) implementeras enligt broker-mönstret, inte exclusive binding —
men **v1 bygger bara brokerns skelett, inte dess policylager**:

1. **`engine_id` är en broker-nyckel, inte en direkt-bunden slot.** `EngineContext.get
   (engine_id)` returnerar alltid en broker-referens (`EngineBroker`), aldrig en adapter
   direkt. Konsumentkoden (`unified_cli.py`) anropar
   `engine_context.get(choice.engine_id).invoke(...)` — samma anropsyta som ADR-026
   redan skissade, ingen skillnad för konsumenten.

2. **v1-policy: exakt en provider per broker, passthrough.** Brokern implementerar i v1
   ingen routningspolicy (ingen round-robin, ingen viktning) — det vore att bygga
   spekulativt för providers som inte finns än, samma regel ADR-022 §Alternatives redan
   tillämpade på inlärd routing. En broker med en enda registrerad provider degraderar
   till ren passthrough: `invoke()` anropar den enda providerns `invoke()` direkt. Detta
   är funktionellt identiskt med exclusive binding för dagens två adaptrar
   (`claude-direct`, `hermes`) — skillnaden är bara var gränsytan sitter.

3. **Multipel-provider-policy byggs när ett verkligt behov uppstår** — t.ex. en andra
   Deepseek-profil, eller en explicit fallback-provider för en `degraded`-flaggad motor
   (ADR-022s `reliability_class`-fält). Det datumet, inte idag, är när load
   balancing/rolling-updates-policyn faktiskt skrivs.

4. **Cross-process invocation (RPC-bryggan i §6.2) är explicit inte del av detta beslut.**
   `hermes_invoker.py`s subprocess-modell täcker dagens behov (en process anropar en
   annan engines CLI och väntar på resultatet); en distribuerad broker över flera
   Cortxt-processer är en helt annan skalfråga utan känt behov idag.

**Vad detta ändrar i ADR-026:** bara var gränsytan mellan "en `engine_id`" och "en
adapter-instans" sitter (via brokern istället för direkt), och att registret från start
tillåter flera providers per nyckel utan omdesign. `EngineAdapter`-protokollet,
`HermesAdapter`-ompaketeringen, och att `route()`/`engine_manifest.py` förblir orörda
står fast oförändrade.

## Consequences

### Positive
- Att lägga till en andra provider för en befintlig `engine_id` (ny Deepseek-profil,
  fallback-motor) blir en registrering till, inte en ombindning som stör konsumenter —
  precis den egenskap ADR-026 saknade.
- v1-implementationen är trivial (broker med en provider = passthrough), så ingen
  komplexitet läggs till för fall som inte finns än — brokerns *skelett* köper
  framtiden, inte dess policylogik.
- Terminologin (`broker`, `provider`, `exclusive binding` vs `service broker`) är nu
  delad med Cordis-papret, vilket gör framtida jämförelser och eventuell vidare
  låning av mönster (rolling updates, load balancing) billigare att resonera om.

### Negative
- Ett extra indirektionslager (`EngineBroker` mellan `EngineContext` och
  `EngineAdapter`) jämfört med ADR-026s enklare skiss, för ett problem (en provider per
  nyckel) som idag inte kräver det.
- Broker-abstraktionen är, precis som papret själv flaggar (§5.3 "Threats to validity"),
  validerad i en TypeScript/Koishi-kontext över fyra års produktionsdrift — ingen
  motsvarande evidens finns för en Python-portning i den här kodbasen. Mönstret lånas
  som design-vokabulär, inte som bevisad implementation.

### Risks
- Om ingen andra provider någonsin registreras per nyckel var indirektionen bortkastad
  komplexitet — mildras av att v1-policyn (passthrough) håller kostnaden till en extra
  metodanrop, inte en ny subsystemklass.
- Broker-mönstret kan lockas att växa routningspolicy (viktning, latensbaserad
  balansering) innan data finns för att motivera det — samma spekulativ-byggnad-fälla
  ADR-022 och ADR-026 redan flaggat. Explicit non-goal ovan (punkt 3) är tänkt att
  förhindra det.

## Alternatives Considered
1. **Behåll exclusive binding som ADR-026 skissade** — förkastad: löser inte det
   konkreta scenariot (flera Deepseek-profiler, fallback-motor för `degraded`) utan att
   konsumenten märker ett providerbyte; broker-skelettet kostar nästan inget extra i v1
   för att undvika det.
2. **Bygg hela broker-policylagret nu (load balancing, rolling updates)** — förkastad:
   ingen av dagens två providers (`claude-direct`, `hermes`) har mer än en instans;
   samma bygg-inte-spekulativt-regel som redan styr `route()`s scope (ADR-022).
3. **Cross-process/RPC-broker från start** — förkastad: `hermes_invoker.py`s
   subprocess-modell räcker för dagens en-process-daemon; ingen känd multi-process-
   skalfråga finns att lösa för.

## Validation
- [ ] `EngineContext.get(engine_id)` returnerar en `EngineBroker`, inte en adapter direkt
- [ ] Broker med en registrerad provider beter sig identiskt med direkt anrop (inga
      extra sido-effekter, ingen mätbar overhead utöver ett metodhopp)
- [ ] `unified_cli.py`s anropsyta (`engine_context.get(...).invoke(...)`) oförändrad från
      ADR-026s skiss
- [ ] Ingen routningspolicy (round-robin/viktning) implementerad förrän en andra
      provider faktiskt registreras under samma nyckel

## Expiry/Review Trigger
- Review by: 2026-09-19 (samma horisont som ADR-026)
- Trigger: en andra provider registreras under samma `engine_id` (t.ex. en andra
  Deepseek-profil eller en fallback-motor för en `degraded`-flaggad engine) och kräver
  att routningspolicyn faktiskt skrivs, ELLER cross-process-behov uppstår (Supervisor
  Daemon splittas över flera processer) och §6.2s RPC-brygga blir relevant, ELLER
  ADR-026s egen review-trigger (RLM tar över `route()`s roll, eller registryt visar sig
  fel format) infaller först och tar detta beslut med sig i omprövningen.
