# 2026-08-03: Kanban, Swarm, GitHub Mirror och Gateway Dispatch

## Session snapshot

**Datum:** 2026-08-03  
**Fokus:** Setup av GitHub Projects Kanban, Hermes Kanban execution ledger, manuell dispatch-rutin, gateway obevakad dispatch, swarm-mode, och Kanban→GitHub mirror.  
**Utfall:** Alla tre deliverables färdiga och bevisade. Operations-docs skapade.  

## Vad som levererats

### A) GitHub Projects Kanban (endast planering)

- **Dokument:** `docs/operations/github-project-kanban-setup.md`
- **Board:** "AI Workspace Delivery" finns redan i GitHub (PVT_kwHOBcHJy84BfFfW)
- **Kolumner:** Backlog → Triage → Ready → In progress → Review → Blocked → Done
- **Regel:** Ingen andra Kanban någon annanstans. GitHub är enda masterregistret.

### B) Manuell dispatch-rutin

- **Dokument:** `docs/operations/manual-dispatch-routine.md`
- Checklista för att gå från `Ready`-issue till körning och tillbaka
- Inkluderar `run_id`-generering, runtime-val, resultat-envelope, review, operator approval
- One-liner dispatch exempel

### C) Hermes Kanban execution ledger

- **Dokument:** `docs/operations/hermes-kanban-execution-ledger.md`
- **Board:** `cortxt-cp` skapad och kopplad till projekt
- **Projekt:** Hermes project "Cortxt CP" bundet till boarden med korrekt Windows-path (`cygpath -w`)
- Demo med tre parallella research-tasks + synthesis med parent-bereenden
- Gateway dispatch testad och bevisad (Test 2: scratch workspace, 36s, `ready → running → done`)

### D) Gateway dispatch test

- **Dokument:** `docs/operations/gateway-dispatch-test-results.md`
- Konfiguration: `kanban.dispatch_in_gateway: true`, `dispatch_interval_seconds: 30`
- **Test 1 (worktree):** Blocked på grund av felaktig Windows-path (`C:\c\Users` istället för `C:\Users`)
- **Test 2 (scratch):** ✅ Lyckades — dispatcher claim, spawn, heartbeat, complete — allt automatiskt
- **Lärdom:** På Windows (git-bash), använd alltid `cygpath -w` för projekt-paths

### E) Swarm-mode

- **Dokument:** `docs/operations/swarm-mode-guide.md`
- Swarm skapad och bevisad: `t_8b1fdd9c` med 3 workers → verifier → synthesizer
- Root-card sparar topologi som kommentar (shared blackboard)
- Automatiska beroenden: verifier `todo` tills alla workers `done`; synthesizer `todo` tills verifier `done`

### F) Kanban → GitHub mirror

- **Skript:** `harness/scripts/mirror-kanban-to-github.py` (+ `.bat` wrapper)
- **Cron-jobb:** `mirror-kanban-to-github` — kör var 10:e minut
- Funktion: Pollar `done`-tasks, extraherar GitHub-issue från body, postar resultat-envelope som kommentar
- **Dokument:** `docs/operations/kanban-github-mirror.md`

### G) Cost-telemetry

- **Dokument:** `docs/operations/cost-telemetry-setup.md`
- `display.show_cost: true` satt i coordinator-profilens config
- Worker bör rapportera kostnad i resultat-envelopen (metadata)
- Auto-kalkylation från tokens → USD är ej implementerad

## Uppdaterad operativ modell

```text
Buzz (dialog och approval surface)
  -> GitHub Issue/Project (scope och workflow source of truth)
  -> MANUELL dispatch ELLER Gateway obevakad dispatch
     -> Hermes Kanban board 'cortxt-cp' (execution ledger)
        -> Enstaka task: claim → kör → complete
        -> Swarm: auto-graf med workers → verifier → synthesizer
     -> Cron var 10:e min: mirror-kanban-to-github
        -> GitHub issue-kommentar med resultat-envelope
  -> GitHub evidence eller pull request
  -> Codex read-only review när det krävs
  -> Operator approval
```

## Filer skapade/uppdaterade

| Fil | Status |
|-----|--------|
| `docs/operations/github-project-kanban-setup.md` | 🆕 Ny |
| `docs/operations/manual-dispatch-routine.md` | 🆕 Ny |
| `docs/operations/hermes-kanban-execution-ledger.md` | 🆕 Ny |
| `docs/operations/gateway-dispatch-test-results.md` | 🆕 Ny |
| `docs/operations/swarm-mode-guide.md` | 🆕 Ny |
| `docs/operations/kanban-github-mirror.md` | 🆕 Ny |
| `docs/operations/cost-telemetry-setup.md` | 🆕 Ny |
| `harness/scripts/mirror-kanban-to-github.py` | 🆕 Ny |
| `harness/scripts/mirror-kanban-to-github.bat` | 🆕 Ny |
| `docs/wayfinder/handoffs/2026-08-03-kanban-setup-session.md` | 🆕 Ny |

## Nästa steg

1. **Swarm gateway-test:** Starta gateway och låt den köra hela swarm-grafen obevakat.
2. **GitHub mirror live-test:** Skapa en task med referens till en riktig issue, låt den bli `done`, verifiera att mirror-skriptet postar kommentar.
3. **Cost-kalkylator:** Bygg en lookup-tabell provider+model → USD/token för auto-rapportering.
4. **n8n/VPS:** Planera hur den senare automationen ska ersätta manuell dispatch.

## Buzz / Hermes runtime-avgränsning (tillagt 2026-08-03)

Förberedelserna i detta dokument (Buzz-workflows, Kanban, mirror, gateway) har
ibland blivit lästa som att Buzz **ska** vara dispatch-hubben. Det är fel.

| Vad som är sant | Vad som är förhoppning |
|---|---|
| Buzz är **operatorns dialog- och approval-yta** | Buzz ska automatiskt väcka Builder via workflow-mention |
| GitHub är **enda masterregistret** | Buzz ska ersätta manuell dispatch |
| Versionskontrollerade Buzz-workflows är **policy-gated tillgångar** | Buzz-native delegation ska ge pollbar status |
| Routing-markers (`[BUILD_READY]`) är **framåtkompatibel semantik** | Automatisk handoff utan operator är verifierad |

**Verklighet:** Endast Hermes Kanban gateway-dispatch är bevisad obevakad
(`ready → running → done`, 36 s, scratch workspace). Buzz-workflows ligger
kvar som **disabled-by-default** tillgångar och aktiveras endast när blockers
är lösta. Detta är inte ett designfel — det är en korrekt separation mellan
"vad vi tror på" och "vad vi kör idag".

## Blockers kvar

- Buzz-native delegation är fortfarande "discovery only" — polling saknas.
- Buzz Builder är stoppad (terminal-output saknas, idle_timeout).
- General dispatcher från `Ready`-issue till fullständig resultat-envelope finns ej än.
- Cost telemetry är `unknown` för automatiska körningar.
- **Windows-path i worktree-mode:** `C:\c\Users` istället för `C:\Users`; kräver
  `cygpath -w` vid konfiguration. Scratch-mode fungerar.
