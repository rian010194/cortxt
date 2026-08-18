# Fas 8 integration points (V01 close-out)

Status: DRAFT — dokumentation, ingen implementationskod. Skapad som del av Fas 8 close-out
(Kimi V01-rekommendation, operand 2026-08-18 "knyt ihop säcken").

Dessa integrationer är INSTALLERADE men inte implementerade i v1 — de dokumenteras här så att V01 läses
som en sammanhållen plattform och integrationspunkterna är synliga för v1.x/v.02. Båda är icke-delegerbara
operator-gatade i praktiken (policy förblir default tills verifierad promotion; tool är alltid AWAIT_OPERATOR).

## 1. Supervisor (Fas 4) → aktiv policy

- **Nuvarande:** `learning.resolve_active_policy(registry, "policy", "geo")` returnerar den aktiva
  `CandidatePathScore` (eller None → default), men Supervisor (Fas 4) läser inte den vid session-start.
- **Integrationsteg (v1.x):** dokumentera/implementera att `Supervisor` (som har `agent_profile` och
  `reasoning_policy` i dispatch-kontraktet) hämtar aktiv policy via `resolve_active_policy()` vid
  session-start, så den versionerade policyn är synlig för dispatch (inte bara internt i `score_path`).
- **Varför v1.x:** V01 kräver att mekanismen finns (kvittat); att koppla Supervisor-läsningen är en
  integrationsändring i Fas 4-lagret, inte i Fas 8-kärnan.

## 2. ToolGate (Fas 3) → tool-kandidat

- **Nuvarande:** `ToolCandidateAdapter` registrerar tool-kandidater och gate:ar dem per effektklass
  (external-mutation/credential → alltid AWAIT_OPERATOR). Fas 3:s `ToolGate` (path-sandboxing) använder
  dock inte en promotad tool-version.
- **Integrationsteg (v1.x):** dokumentera var en framtida promotad tool-version ersätter `ToolGate`-logik.
  Tool-promotion är alltid operator-gated (§32.2), så ingen tool-version kan aktiveras utan människa.
- **Varför v1.x:** full §32.3-säkerhetschecklista (credential-/nätverksisolering, dependency-scanning) är
  en separat v1.x-säkerhetsleverans (P1.6).

## 3. Close-out: `docs/superpowers/V01-exit-report.md`

- Samlad evidens-tabell (varje fas → exit-kriterium → bevis → caveat).
- Fas 8-rader markerade (64 learning-tester gröna; exit-criterion N=3 grön; spec/plan GODKÄND).
