# Handoff: Buzz return channel + automatic Kanban→cron→Buzz status push

Date: 2026-08-05
Repository: C:\Users\rikar\Cortxt\projects\ai-workspace-control-plane
Branch: agent/separate-harness-verticals
Next-session prompt: copy the fenced block below into a fresh session.

---

## Next-session prompt (self-contained)

```markdown
# Prompt: Buzz-returkanal + automatisk status-push

Du är i repot: C:\Users\rikar\Cortxt\projects\ai-workspace-control-plane
(obligatorisk orientering först: docs/agents/current-operating-model.md →
docs/architecture/dispatch-contract.md → docs/operations/buzz-boundaries.md)

## Kontext (2026-08-05)

Meta-systemets Buzz-koppling är delvis verifierad. Två work-paket ska fortsätta.
Läs harness/scripts/buzz-return.py och harness/scripts/mirror-kanban-to-github.py
innan du ändrar något.

Viktiga fakta:
- Buzz är operator-dialog + approval-yta, INTE diskatcher. GitHub = source of truth.
- Hermes→Buzz-returkanal finns NU: `harness/scripts/buzz-return.py` postar status
  direkt till hosted Vertical 01-kanal via installerad `buzz.exe`
  (C:\Users\rikar\AppData\Local\Buzz\buzz.exe).
- Returkanalen är live-verifierad 2026-08-05 (event f44d6e1c…, accepted:true) —
  ändra inte dess grundmekanism utan att tala om det.
- Buzz-nyckeln är `BUZZ_PRIVATE_KEY`: satt med `setx` i Windows user-scope.
  Scriptet läser den från env ELLER via user-scope-fallback (PowerShell).
  NYCKELN FÅR ALDRIG printas, loggas, committas, eller hamna i chat. Verifiera att
  --dry-run läcker inget värde efter varje ändring.
- Kanban-bräda "cortxt-cp", och `harness/scripts/mirror-kanban-to-github.py` +
  .bat existerar (den gamla cron-mirrorn 10 min). Observera: `hermes cron list`
  visar för närvarande INGA schemalagda jobb — cron-mirrorn verkar inte köra.

## Uppgift 1 — Fortsätt/verifiera buzz-return.py

1. Granska `harness/scripts/buzz-return.py` och bekräfta att det är rent
   (KISS/DRY, matchar omgivande stil). Rapportera ev. förbättringar utan att bränna
   onödiga tokens.
2. Ad-hoc-verifiera med ett temp-skript hermes-verify-*.py (tempfile):
   - no-key → exit 3, säkert blockerad; --dry-run → exit 0 utan nyckel-läckage
   - nyckel löses (user-scope-fallback) men printas aldrig
   - injektion av nyckel till buzz.exe-subprocess finns
3. Efter valfri ändring: run manuellt mindre, committa med tydlig commit-msg.
   Om du inte ändrar något: säg att det redan är verifierat, gör inget redundant.

## Uppgift 2 — Automatisk status-push Kanban→cron→Buzz (huvudmålet)

Bygg ett sätt att automatiskt publicera run-slut-status till Buzz när ett
Kanban-kort avslutas, utan att koppla på obevakad dispatch eller andra backlog.

Föreslagen design (verifiera/flera mot befintliga script innan du bygger):
a) Bygg ett kombinerat skript (t.ex. harness/scripts/kanban-buzz-push.py) som:
   - läser Kanban-bräda cortxt-cp och hittar kort som nyligen gått till "done"/
     fått ny status (delta-baserat, håll koll på senast pushade status),
   - för varje nytt slutresultat anropar samma logik som buzz-return.py för att
     posta en kompakt statusrad till Vertical 01-kanalen (uppge run_id, issue,
     status, kostnad om tillgänglig),
   - gör inget nätverksanrop om inget nytt att pusha.
b) Återanvänd buzz-return.py:s nyckelhantering/CLI-kommandot — duplicera INTE
   logiken; importera eller calla snarare än kopiera.
c) Utgå från hur mirror-kanban-to-github.py gör delta/tillståndshållning och
   anpassa; matcha dess konventioner.
d) Registrera som cron-job (hermes cron create) som kört ex 5 min; dokumentera
   att jobbet är aktivt (kontrollera med hermes cron list efter).
e) Testa med en riktig men testmärkt statusrad (t.ex. "[TEST-PUSH]") och
   verifiera att den dyker upp i kanalen (relay accepterar). Gör INTE en massa
   test-sändningar — en kontrollerad räcker.

## Säkerhetsregler (obligatoriskt)
- Inga secrets/prompts/kunddokument i git, commits, chat eller kanal.
- Buzz är inte en andra backlog; pusha STATUS, skapa inte tasks.
- Verifiera nyckel-läckage efter varje ändring (grep på --dry-run-output).
- Inget obevakat dispatch; detta är statusdisplay/återkoppling bara.
- Commits kräver tydlig kontext; repo är på branch agent/separate-harness-verticals.
- Om något är oklart kring cirkeln (cron→buzz→github) — fråga operatören, antag
  inte. "As complex as necessary, as simply as possible."

## Definition of done
- buzz-return.py granskad och (vid behov) verifierad/committad.
- kanban-buzz-push.py byggt, committat, registrerat som cron, och en
  kontrollerad test-statusrad bekräftad live i Vertical 01-kanalen.
- Kort sammanfattning av vad som körs och exakta nästa steg.
```

---

## Commit-referens för returkanalen (2026-08-05)
- `a86267b` feat(buzz): add Hermes->Buzz return channel script
- `5a07989` feat(buzz): read BUZZ_PRIVATE_KEY from user-scope env fallback
- `5bb342e` fix(buzz): inject resolved key into buzz.exe subprocess env
- `5b968ea` docs(buzz): mark return channel verified after live test

## Relaterade öppna punkter
- Issue #24: paketnivå-punkter från Codex (manifest 44 vs 47, additionalProperties,
  format: uri, output-schema-constraints) — finns som separat work-paket.
- Verifiera att den gamla Kanban→GitHub mirror-cron faktiskt körs (`hermes cron
  list` visade inga jobb 2026-08-05).
