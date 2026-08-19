# ADR-026: Engine adapter-registry (cordis-inspirerad DI) hålls separat från `route()`s selection

**Status:** Accepted (amended 2026-08-19 för service-broker-mönster per ADR-027)
**Date:** 2026-08-19
**Deciders:** Rikard (operatör), Claude Code (utkast)
**Technical Story:** Uppföljning på ADR-022 (capability manifest + `route()`), uppkommen ur en
diskussion om att lägga till Deepseeks harness som ytterligare engine och om cordis
(`cordiverse/cordis`, Koishijs-släktens plugin-/DI-ramverk) idéer bör ersätta
`agent-platform/routing/engine_manifest.py`

## Context

Operatören tittade på `cordiverse/cordis` (scoped `Context`/DI, plugin-lifecycle,
isolerad reload per plugin) och på Deepseeks agent-harness som kandidat för ytterligare
en engine i loopen (utöver Claude, Codex, Hermes). Frågan som uppstod: ska cordis-stilens
DI/plugin-modell ersätta `engine_manifest.py` helt?

Kodinventering (2026-08-19) visar att `engine_manifest.py` och invocation redan är
implicit tudelade, bara inte formaliserade:

- `routing/engine_manifest.py` — `route(task_tags, manifests) -> EngineChoice`, en ren
  funktion. Bara **selection**: givet taggar, vilket `engine_id` vinner. `DEFAULT_MANIFESTS`
  har idag två poster (`claude-direct`, `hermes`); ADR-022 §Alternatives avsåg redan att
  fler adaptrar (Pi, Codex, Copilot) läggs till som manifest-rader när de kopplas in.
- `routing/hermes_invoker.py` — vet *hur* hermes faktiskt körs (subprocess-wrapper).
  Filens egen docstring säger uttryckligen: "`route()` picks 'hermes' as an engine_id,
  but picking isn't invoking." Redan medveten separation, bara inte ett registrerat
  kontrakt.
- `cli/unified_cli.py:338–359` — hårdkodad `if choice.engine_id == "hermes": ... elif
  choice.engine_id == "claude-direct": ...`. Det är **den här grenen**, inte `route()`,
  som är den faktiska platsen där ett DI-/plugin-lager skulle ersätta något.

ADR-022 lovar redan en efterträdare till `route()`s roll: target-architecture.md §29
punkt 5 ("RLM och geometric reasoning ägs av Cortxt Agent Core") och Fas 5/6-arbetet i
`agent-platform/reasoning/geometric/`. Citat ur ADR-022: "when that engine is ready, it
replaces `route()`'s role; it does not extend it." Supervisor Daemon v1-specen
(`docs/superpowers/specs/2026-08-19-supervisor-daemon-v1-design.md`, Non-goals) upprepar
samma sak och pekar ut att daemonen ärver handoffen automatiskt utan egen kodändring.

Att låta cordis-DI ersätta `engine_manifest.py` helt skulle alltså introducera en **andra,
konkurrerande efterträdare** till samma bootstrap-funktion — en som inte är den redan
planerade RLM/Geometric Reasoning-vägen. Det vore att lösa upp ett arkitekturbeslut
(ADR-022) utan att formellt supersede:a det, och utan den evidens (Fas 6-exitkriterium)
som ADR-022/025 redan sätter som villkor för att röra `route()`s roll.

## Decision

Cordis-inspirerad DI ersätter **inte** `route()`/`engine_manifest.py`. Den införs som ett
separat lager som ersätter `unified_cli.py`s hårdkodade if/elif-dispatch:

1. **`route()` och `EngineManifest` rörs inte.** Selection-kontraktet (ADR-022) står fast
   orört; RLM/Geometric Reasoning förblir den enda avsedda efterträdaren till dess roll.

2. **Nytt lager: `EngineAdapter`-protokoll + `EngineContext`-registry**
   (`runtime/engine_adapter.py`, `runtime/engine_registry.py`). Varje engine (Claude,
   Hermes, Codex, framtida Deepseek) blir en adapter som registrerar sig i en root-context
   vid daemon-start — cordis idé om scoped `Context`/DI, portat som mönster, inte som
   TS/Koishi-beroende (Supervisor Daemon är Python).

3. **Befintlig invocation-kod paketeras om, skrivs inte om.**
   `hermes_invoker.invoke_hermes()` blir `invoke()`-metoden på en `HermesAdapter`. Samma
   mönster fyller `unified_cli.py:299`s dokumenterade lucka ("'claude-direct' has no
   headless invocation here") med en `ClaudeAdapter` när/om den byggs, och ger en tydlig
   registreringsplats för en framtida `DeepseekAdapter` — en manifest-rad i
   `engine_manifest.py` plus en adapterfil, inget annat.

4. **`unified_cli.py`s if/elif-kedja (rad 338–359) ersätts** med
   `engine_context.get(choice.engine_id).invoke(...)`. Det är den enda platsen som
   faktiskt tas bort.

**Explicit inte del av detta beslut:**
- Att bygga eller registrera en `DeepseekAdapter` nu — sker som egen ADR-022-manifestrad
  när Deepseek faktiskt kopplas in och har körd evidens (samma regel ADR-022 redan satte
  för Pi/Codex/Copilot).
- Att röra `route()`s selection-algoritm eller `reliability_class`-semantik.
- Hot-reload/isolerad krasch-återhämtning per adapter i v1 — registryt möjliggör det
  senare, men Supervisor Daemon v1-specen bygger inte den funktionaliteten nu.

## Consequences

### Positive
- `route()` förblir orört och ärver RLM-handoffen exakt som ADR-022 redan lovade — inget
  nytt beroende introduceras på selection-sidan.
- Att lägga till en engine (Deepseek eller annan) blir: en manifest-rad + en adapterfil,
  ingen ändring i `unified_cli.py` eller i selection-logiken.
- `hermes_invoker.py`s befintliga, redan testade subprocess-logik återanvänds rakt av —
  ingen omskrivning av fungerande kod.

### Negative
- Ett nytt litet abstraktionslager (`EngineAdapter`/`EngineContext`) tillkommer som inte
  fanns förut — mer kod att underhålla för ett problem (fyra hårdkodade rader i
  `unified_cli.py`) som idag är litet.
- Cordis-mönstret (scoped Context, DI) portas konceptuellt från ett TS/Koishi-ramverk;
  ingen kod eller paket importeras, vilket betyder att detaljer (fork-semantik,
  service-scoping) måste designas om för Python, inte kopieras.

### Risks
- Om registret byggs med mer generalitet än vad tre-fyra adaptrar faktiskt kräver
  (hot-reload, dependency-graf mellan adaptrar) uppstår samma "bygg inte spekulativt"-fälla
  som ADR-022 §Alternatives redan varnade för på selection-sidan.
- Två nya arkitekturbegrepp (`route()`s selection och `EngineContext`s DI) måste hållas
  isär i framtida dokumentation — risk att någon av misstag lägger selection-logik i en
  adapter eller invocation-logik i `route()`.

## Alternatives Considered
1. **Låt cordis-DI ersätta `engine_manifest.py` helt** — förkastad: skulle introducera en
   konkurrerande efterträdare till `route()`s roll vid sidan av den redan planerade
   RLM/Geometric Reasoning-vägen (ADR-022, target-architecture.md §29.5), utan att formellt
   supersede:a ADR-022 och utan Fas 6-exitkriteriets evidens.
2. **Gör inget — behåll `unified_cli.py`s if/elif** — förkastad: skalar inte förbi tre-fyra
   engines utan att bli en växande hårdkodad kedja; ger heller ingen isoleringspunkt för
   framtida per-adapter-krasch/reload.
3. **Importera cordis (TS-paketet) direkt via ett Node-sidecar-lager** — förkastad: Supervisor
   Daemon och hela agent-platform-paketet är Python; ett Node-beroende för ett rent
   arkitekturmönster är oproportionerlig komplexitet.

## Validation
- [ ] `EngineAdapter`-protokoll och `EngineContext`-registry implementerade och testade
- [ ] `HermesAdapter` paketerar om `invoke_hermes()` utan att ändra dess testade beteende
- [ ] `unified_cli.py:338–359`s if/elif-kedja borttagen, ersatt av
      `engine_context.get(...).invoke(...)`
- [ ] `route()`/`engine_manifest.py` oförändrade (diff visar noll ändringar i den filen)

## Expiry/Review Trigger
- Review by: 2026-09-19
- Trigger: en tredje/fjärde adapter (Deepseek, Codex, eller Pi) registreras och avslöjar
  att protokollet är fel format (t.ex. behöver streaming eller multi-turn-state
  registryt inte förutsåg), ELLER RLM/Geometric Reasoning tar över `route()`s roll (Fas
  6-exitkriteriet, se ADR-025) och gränsytan mellan selection och registry behöver
  omprövas, ELLER Supervisor Daemon v1 faktiskt implementerar per-adapter hot-reload och
  det visar att `EngineContext` designades för smalt.
