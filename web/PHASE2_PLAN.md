# AI Workspace Control Plane — Phase 2 Plan

## ✅ Phase 1 Complete (2026-08-04)

### Delivered
- **8-page web prototype** (Vite + React + TypeScript + Tailwind + Recharts)
- **Overview** — Interactive architecture diagram
- **Flow** — Step-by-step Buzz → Approval
- **Agents** — 11 profiles + 6 receptionists
- **Skills** — 34 skills with filters
- **Kanban** — Board, swarm graph, mirror
- **Dispatch** — Form + Result Envelope + cost estimation + fallback chains
- **Verticals** — AI Act, BVC
- **Telemetry** — Cost Calculator + pricing table + free quota dashboard

### Cost Telemetry (NEW)
- Lookup table: provider+model → USD/token
- Live Cost Calculator
- Cost estimation in Dispatch
- Cost-ceiling warnings
- Free-tier quota tracking (kimi-k2.6:free 300/day, qwen3-coder:free 200/day)
- Fallback chains

---

## ⚡ Phase 2 Plan

### Session A: SSSF Adoption (Researcher — nemotron-3-ultra FREE)
- [ ] Sessions/Runs grid page (SSSF-style cards)
- [ ] Waterfall timeline per run (request → plan → build → test)
- [ ] Gates visualization
- [ ] Model tier list (S+, S, A, B, C)

### Session B: Live Integration (Builder — kimi-k2.6)
- [ ] Connect to real Hermes API
- [ ] Connect to GitHub API for Kanban
- [ ] Real-time cost tracking
- [ ] Deploy to GitHub Pages/Vercel

### Session C: Polish (Reviewer — Codex)
- [ ] Code review
- [ ] Accessibility audit
- [ ] Mobile responsiveness

---

## 💰 Cost-First Model Routing

| Task | Model | Provider | Cost |
|---|---|---|---|
| Planning | nemotron-3-ultra | OpenRouter | **FREE** |
| Implementation | kimi-k2.6 | Moonshot | $0.55/$2.65 |
| Review | codex | OpenAI | $1.75/$14.00 |

**Rule:** Free tier first. Escalate only when quota exhausted.
