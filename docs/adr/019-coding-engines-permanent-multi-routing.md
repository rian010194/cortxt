# ADR-019: Coding execution — permanent multi-engine routing, not Pi/Hermes replacement

**Status:** Accepted
**Date:** 2026-08-16
**Deciders:** Rikard (operatör)
**Technical Story:** Operatörsdiskussion 2026-08-16 (ingen GitHub-issue upprättad före detta ADR)

## Context

`docs/architecture/cortxt-agent-platform-target-architecture.md` §22.3 beskriver Hermes,
Pi och Prime Agent som roller **under migrationen** (benchmark, fallback, adapter), och
§24.2 definierar explicita "ersättningskriterier" för när "Pi kan lämna huvudvägen".
Fas 3 (Coding Agent v0.1) är skriven mot exit-kriteriet att en kodfixture ska lösas
**utan** Pi eller Hermes — dvs som ett steg mot att göra dem onödiga.

Operatören klargjorde 2026-08-16 att detta inte är avsikten: målet är att fortsätta
använda Pi, Hermes och Codex, och lägga till GitHub Copilot, samtidigt som Cortxt bygger
egen kodningskapacitet för vissa uppgiftsklasser. Ombedd att välja mellan (a) egen Coding
Agent ersätter externa motorer, (b) Cortxt blir enbart en orkestrator utan egen
kodningsruntime, eller (c) båda parallellt, valde operatören **(c)**.

Detta är ett faktiskt vägval som `target-architecture.md` (en beskrivningsfil) i sin
nuvarande lydelse motsäger, och behöver ett register enligt repots egen regel för
beslutsnotiser innan beskrivningsfilen rättas.

## Decision

**Cortxts egen Coding Agent (Fas 3 och framåt) är ett permanent tillägg till
routingpolicyn, inte en ersättningsväg.** Pi, Hermes och Codex förblir permanenta
routingval; GitHub Copilot läggs till som framtida adapterkandidat. Ingen extern
coding-motor är på väg att fasas ut som en konsekvens av Fas 3.

Routingpolicyn väljer motor per uppgiftsklass (kostnad, kapabilitet, dataklass,
tillgänglighet) — inte enligt en migrationsplan där externa motorer blir onödiga.
`target-architecture.md` §24 ("ersättningskriterier för Hermes/Pi") gäller inte
kodningsmotorer efter detta beslut; den kvarstår oförändrad för Hermes koordinerande
roll (Supervisor, §24.1), som inte omfattas av detta ADR.

## Consequences

### Positive
- Bevarar tillgång till bästa tillgängliga externa verktyg (Copilot, Codex) utan att
  Fas 3 tvingas bli "tillräckligt bra för att ersätta Pi" innan den får användas.
- Minskar tidspress och scope-risk på Fas 3 — den behöver bevisa egen förmåga för
  avgränsade uppgiftsklasser, inte generell paritet med Pi.
- Öppnar för Copilot som ytterligare adapter utan att det tolkas som avsteg från planen.

### Negative
- Två parallella underhållslinjer: en egen coding-runtime (Fas 3+) och adaptrar för
  flera externa motorer (Pi, Hermes, Codex, framtida Copilot).
- Routingpolicyn blir mer komplex — kräver explicit beslutslogik för vilken
  uppgiftsklass som går till egen Coding Agent kontra extern motor.

### Risks
- Utan tydliga urvalskriterier kan egen Coding Agent-utveckling sakna riktning
  (ingen "done"-linje motsvarande det tidigare ersättningskriteriet).
- Adapterunderhåll för flera externa motorer (särskilt en framtida Copilot-adapter)
  är oprövat och kan bli en dold kostnad.

## Alternatives Considered
1. **Fullständig ersättning (ursprunglig §24.2-lydelse)** — förkastad: matchar inte
   längre operatörens avsikt, och skulle innebära att avstå bästa tillgängliga externa
   verktyg i onödan.
2. **Enbart orkestrering, ingen egen Coding Agent** — förkastad: operatören vill ha
   båda; vissa uppgiftsklasser kan dra nytta av tät integration med Cortxts egna
   Problem State, reasoning och evidenslager på ett sätt externa motorer inte kan ge.

## Validation
- [x] Operatörsgodkännande registrerat (2026-08-16, denna konversation).
- [ ] `target-architecture.md` §22.3 och §24.2 uppdaterade i samma commit som detta ADR.
- [ ] Urvalskriterier (vilken uppgiftsklass → egen Coding Agent vs extern motor)
      definierade — spåras som öppet beslut, inte avgjort av detta ADR.
- [ ] Copilot-adapter utvärderad och tillagd i `adapters/`-strukturen när prioriterad.

## Expiry/Review Trigger
- Review by: 2026-11-16
- Trigger: urvalskriterier för motor-per-uppgiftsklass implementeras, eller
  underhållskostnaden för parallella coding-adaptrar visar sig oproportionerlig mot
  nyttan av egen Coding Agent-kapacitet.
