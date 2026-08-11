---
title: "Operator Cockpit UI/UX Planning — Stage 1 Handoff to Stage 2 Codex Review"
date: 2026-08-11
from: Hermes Coordinator (kimi-k2.6 / kimi-coding)
to: Next Hermes session
status: WAITING_FOR_CODEX_REVIEW
---

# Kontext

Denna handoff är resultatet av en fullständig Stage 1-planeringskörning för Operator Cockpit UI/UX. Koordinatorn har:

1. Läst alla obligatoriska filer (AGENTS.md, kontrakt, V2-arkitektur, webbkod, GitHub-issues).
2. Utfört visuell verifiering av alla 9 routes (desktop 1264×569; tablet/mobil VISUALLY_UNVERIFIED).
3. Sammanställt en andra revision av CODEX_REVIEW_PACKET som adresserar alla fyra Codex-fynd från första granskningen.
4. Skrivit paketet till fil och beräknat SHA-256.

## Aktuellt tillstånd

| Fil | Sökväg |
|---|---|
| CODEX_REVIEW_PACKET_REVISION_2 | `docs/wayfinder/handoffs/CODEX_REVIEW_PACKET_REVISION_2.md` |
| Verifierad SHA-256 | `9961c7a900f2dbba9191d5173fcbd14d24253b6d51cf245e6cc74d9e0c94a336` |
| Git branch | `agent/fix-85-utf8-runner` (clean tracked, 7 untracked docs) |
| GitHub Project 4 | `AI Workspace Delivery` — #22, #54, #57, #58, #71 i Inbox |

## Vad som är klart

- Stage 1A: Strukturell UI-inventering färdig.
- Stage 1B: Visuell verifiering partiellt klar (desktop); tablet/mobil VISUALLY_UNVERIFIED.
- Stage 1C: Mål-IA definierad (Decision Queue, Work, Runs, Routes, Evidence, Economics, Policy, Capabilities, Verticals).
- Alla fyra Codex-fynd från första granskningen adresserade i andra revisionen.

## Vad som är kvar

- **Oberoende Codex-granskning av andra revisionen** — detta är nästa sessions ENDA uppgift.
- Inga kodändringar, GitHub-mutationer eller deployment får ske förrän Codex returnerar GODKÄND.

---

# Exekveringsprompt för nästa Hermes-session

## Roll och modell

- **Primär roll:** Hermes Coordinator
- **Primär modell:** Nemotron-3-ultra (FREE via OpenRouter) för läsning/verifiering; byt till Kimi endast om analys kräver betald modell
- **Max runtime:** 900 sekunder
- **Max kostnad:** $1.00 USD
- **Delegation:** 0 (inga subagenter)

## Uppgift

Utför en färsk, oberoende Codex-granskning av `CODEX_REVIEW_PACKET_REVISION_2.md`.

### Steg 1: Verifiera filen

1. Läs `docs/wayfinder/handoffs/CODEX_REVIEW_PACKET_REVISION_2.md`.
2. Beräkna SHA-256.
3. Bekräfta att filen börjar med exakt:
   ```
   REVISION 2 — FINAL FOR CODEX VERIFICATION
   ```
   och innehåller:
   ```
   PLANNING RESULT: READY_FOR_CODEX_REVIEW (second revision)
   ```
4. Om hash eller rubrik inte stämmer: returnera `UNVERIFIABLE` och stoppa.

### Steg 2: Förbered Codex-prompten

Sammanställ EN enda prompt till Codex med följande struktur:

```
Du är en oberoende läsåtkomstgranskare. Granska ENDAST det bifogade paketet.

Verifiera först:
- Attachment-ID: [använd filens faktiska SHA-256]
- Rubrik: "REVISION 2 — FINAL FOR CODEX VERIFICATION"
- Inledande rad: "PLANNING RESULT: READY_FOR_CODEX_REVIEW (second revision)"

Om dessa inte stämmer: returnera UNVERIFIABLE och stoppa.

Om de stämmer: granska enbart detta paket. Ignorera alla tidigare revisioner.

Returnera exakt ett utslag: GODKÄND eller KRÄVER ÄNDRINGAR.
Rapportera endast nya, kvarstående P0/P1/P2-fynd med:
- Evidens (fil + rad eller GitHub-issue + read-back-tid)
- Påverkan
- Minsta korrigering

Kontrollera särskilt:
- Leverantörsneutralitet
- Källornas auktoritet
- Kontraktsfidelity (AGENTS.md, dispatch-contract.md, issue-tracker.md)
- Säkerhetsgränser (inga credentials i klienten)
- Tillgänglighet och visuell verifiering
- Hostingantaganden
- Issue-dubletter
- Om Release 1 är genuint avgränsad
```

### Steg 3: Skicka till Codex

Använd Codex CLI (eller operatörens godkända Codex-anslutning) för att skicka prompten med filinnehållet bifogat.

**Viktigt:**
- Inkludera INTE sessionhistorik, credentials eller kunddata i prompten.
- Bifoga ENDAST filinnehållet + reviewer instructions.
- Sätt max_tokens eller motsvarande gräns för att hålla kostnaden under $1.00.

### Steg 4: Ta emot och rapportera utslaget

1. Vänta på Codex svar.
2. Rapportera exakt utslag: GODKÄND eller KRÄVER ÄNDRINGAR.
3. Om KRÄVER ÄNDRINGAR: lista varje finding med evidens, påverkan, minsta korrigering.
4. Om GODKÄND: rapportera detta och stoppa — nästa steg är operatörens beslut att godkänna Builder Run 1.

## Hårda begränsningar

- INGA repository-edits.
- INGA GitHub-mutationer.
- INGA builds, installationer, eller deployment.
- INGA subagenter eller ytterligare modellkörningar.
- Max en Codex-anrop.
- Stoppa direkt efter utslaget.

## Godkännanden som saknas (operatörsgrindar)

Följande kräver explicit operatörsbeslut EFTER Codex-granskning:

1. Godkännande av Builder Run 1 (UI-002 + #54 + false liveness).
2. Godkännande av #22-rescope och skapande av UI-001–UI-006.
3. Beslut om publik/privat audience och hosting.
4. Eventuell tredje omarbetning om Codex returnerar ändringar.

## Output-format

```
CODEX REVIEW RESULT: [GODKÄND | KRÄVER ÄNDRINGAR | UNVERIFIABLE]

## Sammanfattning
[Max 5 rader]

## Detaljerade fynd (om ändringar krävs)
| # | Allvarlighet | Evidens | Påverkan | Minsta korrigering |
|---|---|---|---|---|

## Nästa steg
[Exakt rekommendation]
```
