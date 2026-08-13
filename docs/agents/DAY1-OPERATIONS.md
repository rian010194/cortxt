# Day 1 Operations — Så här kör du ett jobb

Status: legacy; obsolete operational snapshot
Authority: historical only
Last verified: 2026-08-13 (classified obsolete)

> Do not use this file to dispatch current work. Its automated coordinator,
> mirror-cron, model, cost, heartbeat, and shutdown claims are not supported by
> the current verified baseline. Use
> [the current operating model](current-operating-model.md) and
> [the manual dispatch routine](../operations/manual-dispatch-routine.md).

> Historical claim recorded 2026-08-04; no longer current.
> Med `operator-receptionist` skill laddad: agenten sköter GitHub, du pratar bara.

---

## Förutsättningar (kontrollera en gång)

| Komponent | Kommando | Ska visa |
|---|---|---|
| Hermes profiler | `hermes profile list` | `builder`, `coordinator`, `researcher`, `workflowreconciler` |
| GitHub CLI | `gh auth status` | `Logged in to github.com account rian010194` |
| Kanban board | `hermes kanban list` | `cortxt-cp` |
| Kanban mirror | `hermes cron list` | `kanban-github-mirror` (var 10:e minut) |
| Operator skill | `hermes skills list` | `operator-receptionist` |

---

## Den nya loopen (med operator-receptionist)

```
[Du] Prata med coordinator: "Jag vill ha X"
   ↓
[Coordinator] Skapar GitHub-issue + budget + väljer modell
   ↓
[Coordinator] Sätter Ready och dispatchar rätt worker
   ↓
[Worker] Kör → rapporterar evidence till GitHub
   ↓
[Coordinator] Meddelar dig: "Klart. Godkänn?"
   ↓
[Du] Svara ja/nej/återsänd
   ↓
[Coordinator] Uppdaterar GitHub-status
```

**Du öppnar aldrig GitHub.** Du pratar bara med coordinator.

---

## Steg-för-steg

### 1. Starta coordinator

```bash
hermes --profile coordinator
```

Skillen `operator-receptionist` laddas automatiskt (eller kör `/skill operator-receptionist`).

---

### 2. Säg vad du vill ha

Svenska eller engelska. Naturligt språk.

> *"Jag vill ha en SSSF waterfall-timeline i webbappen."*  
> *"Researcha vilka timeline-bibliotek som finns."*  
> *"Fixa bugg #47."*  
> *"Reviewa PR #12."*

---

### 3. Coordinator gör resten

Agenten ska nu automatiskt:

1. **Tolka** din intent
2. **Skapa** GitHub-issue med scope, acceptance criteria, budget
3. **Välja** modell enligt cost-first routing:

| Uppgiftstyp | Modell | Kostnad |
|---|---|---|
| Planering, research | **nemotron-3-ultra** | FREE |
| Research med kod | **kimi-k2.5** | $0.38/M |
| Implementation | **kimi-k2.6** | $0.55/M |
| Säkerhetsgranskning | **codex** | $1.75/M |

4. **Sätta** label `ready`
5. **Dispatcha** till rätt worker

**Innan dispatch ska coordinator alltid fråga dig:**
> *"Issue #N skapad. Budget: 15 min, $0.00 (nemotron free). Skicka till researcher?"*

Svara **ja** eller justera budget/modell.

---

### 4. Du väntar (eller gör annat)

För långa jobb (>5 min) får du en heartbeat:
> *"Issue #N pågår. 8 minuter kvar. Ingen åtgärd krävs."*

---

### 5. Coordinator rapporterar

När worker är klar:
> *"Issue #N är klart. Rekommendation: [X]. Kostnad: $0.00. Läs resultat: [länk]. Godkänn?"*

---

### 6. Du godkänner

| Du säger | Händer |
|---|---|
| "Ja" / "Godkänn" | Issue stängs som Done |
| "Nej, gör om [feedback]" | Issue flyttas till Ready med din kommentar |
| "Blockerad — [orsak]" | Issue får label `blocked` |

**Regel:** Ingen agent får godkänna sitt eget arbete. Alltid du.

---

## När coordinator INTE ska auto-dispatcha

Coordinator frågar dig alltid först om:
- Kostnaden är > $2
- Modellen är codex (dyr review)
- Uppgiften är irreversibel (push till main, deploy, radera data)
- Free-quota är nästan slut

---

## Nödstop

Säg något av dessa i vilken session som helst:
> *"Stopp"* / *"Avbryt"* / *"Cancel"*

Alla background-processer dödas. Du måste starta om flödet.

---

## Fallback: Manuell dispatch

Om `operator-receptionist` inte är laddad eller om du vill styra själv:

```bash
# Research (billigt)
hermes --profile researcher -m nemotron-3-ultra

# Kodning
hermes --profile builder -m kimi-k2.6

# Review
codex --review-only
```

Skapa fortfarande alltid GitHub-issue först. Ingen agent utan issue-nummer.

---

## Vanliga misstag att undvika

1. **Startar samma session för allt** → Använd coordinator för önskemål, byt aldrig modell i samma session.
2. **Godkänner utan att läsa evidence** → Klicka alltid länken och kolla kommentaren.
3. **Glömmer cost-first** → Om coordinator föreslår dyr modell, fråga "Varför inte nemotron?"
4. **Lämnar sessionen utan att svara** → Coordinator väntar på ditt ja/nej. Timeout efter 30 min.

---

## Nästa steg när detta flyter

- **Kanban-gateway:** Låt `hermes kanban dispatch` auto-claima Ready-uppgifter
- **Buzz-integration:** När Buzz delegation polling är fixat, starta där istället för terminal
- **Pi Builder:** Experimentera med container-isolerade skrivningar via coordinator
