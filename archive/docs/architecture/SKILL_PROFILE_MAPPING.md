# Skill-to-Profile Mapping — AI Workspace Control Plane

**Generated:** 2026-08-03  
**Source:** 101 installed Hermes skills at `/c/Users/rikar/AppData/Local/hermes/skills/`  
**Profiles:** 12 agent profiles from `AGENT_ARCHITECTURE.md`

---

## Legend

| Load Strategy | Meaning |
|---------------|---------|
| `core` | Always loaded by the profile (auto-load on profile activation) |
| `specialist` | Loaded on demand when the profile's task requires it |
| `conditional` | Loaded only when specific conditions are met (e.g., platform, task type) |

| Gap/Redundancy | Meaning |
|----------------|---------|
| ✅ Fills gap | Skill provides capability missing from our custom architecture |
| ⚠️ Partial overlap | Skill overlaps with custom skills but adds distinct value |
| 🔄 Redundant | Skill duplicates custom skill functionality — prefer custom |
| 📦 Available | Installed but not yet mapped to architecture |

---

## Mapping Table

| Skill | Category | Primary Profile | Secondary Profiles | Load Strategy | Notes |
|-------|----------|-----------------|-------------------|---------------|-------|
| **credential-manager** | software-development | credential-manager | coordinator, all receptionists | core | ✅ Fills gap: Centralized vault abstraction required by all receptionists |
| **kanban-github-mirror** | software-development | workflowreconciler | coordinator, deploy | specialist | ✅ Fills gap: Kanban↔GitHub sync for workflow state reconciliation |
| **plan** | software-development | planner | coordinator, builder | core | ✅ Fills gap: TDD-compliant implementation planning with bite-sized tasks |
| **plan-auditor** | software-development | plan-auditor | coordinator, reviewer | specialist | ✅ Fills gap: Adversarial multi-iteration plan audit with fresh-eyes protocol |
| **behaviour-validator** | software-development | behaviour-validator | monitor, reviewer | specialist | ✅ Fills gap: BVC contract runner for production validation |
| **telemetry** | software-development | monitor | all profiles | core | ✅ Fills gap: OpenTelemetry observability — required by ALL profiles |
| **receptionist-base** | software-development | coordinator | all receptionists | core | ✅ Fills gap: Generic base for all 6 receptionists (Obsidian, Notion, Buzz, Hermes, Pi, Codex) |
| **receptionist-obsidian** | software-development | receptionist-obsidian | researcher, writer, coordinator | specialist | ✅ Fills gap: Obsidian vault CRUD, dataview, frontmatter, links |
| **receptionist-notion** | software-development | receptionist-notion | researcher, writer, coordinator | specialist | ✅ Fills gap: Notion API — pages, databases, blocks, search |
| **receptionist-buzz** | software-development | receptionist-buzz | coordinator, planner | specialist | ✅ Fills gap: Operator dialog, approval flows, marker-based wakeup |
| **receptionist-hermes** | software-development | receptionist-hermes | coordinator, planner, workflowreconciler | specialist | ✅ Fills gap: Profile/skill/kanban/cron/memory/delegation management |
| **receptionist-pi** | software-development | receptionist-pi | builder, deploy | specialist | ✅ Fills gap: Pi Builder containers, workspaces, egress rules |
| **receptionist-codex** | software-development | receptionist-codex | reviewer, planner | specialist | ✅ Fills gap: Codex App Server — read-only reviews, chat management |
| **node-inspect-debugger** | software-development | builder | reviewer | specialist | 📦 Available: Node.js debugging via CDP — useful for builder |
| **python-debugpy** | software-development | builder | reviewer | specialist | 📦 Available: Python debugging — useful for builder |
| **requesting-code-review** | software-development | reviewer | coordinator, builder | specialist | ⚠️ Partial overlap: Pre-commit verification pipeline; our `review` skill is broader |
| **simplify-code** | software-development | reviewer | builder | specialist | 📦 Available: Parallel 3-agent cleanup of recent changes |
| **spike** | software-development | researcher | planner, builder | specialist | ✅ Fills gap: Throwaway experiments for feasibility validation |
| **strategic-discovery** | software-development | coordinator | planner, researcher | specialist | ✅ Fills gap: Strategic direction exploration without premature solutions |
| **systematic-debugging** | software-development | builder | reviewer, researcher | specialist | ✅ Fills gap: 4-phase root cause debugging methodology |
| **test-driven-development** | software-development | builder | reviewer, planner | core | ✅ Fills gap: Strict RED-GREEN-REFACTOR enforcement |
| **cli-markdown-safety** | software-development | coordinator | reviewer, deploy | specialist | 📦 Available: Safe markdown passing through shell commands |
| **hermes-agent-skill-authoring** | software-development | coordinator | all | specialist | 📦 Available: In-repo skill authoring conventions |
| **swarm-interface-generation** | autonomous-ai-agents | coordinator | builder | specialist | ✅ Fills gap: Parallel interface generation for 17+ skills |
| **agent-orchestration** | autonomous-ai-agents | coordinator | workflowreconciler, planner | specialist | ✅ Fills gap: Multi-runtime orchestration around GitHub Issues |
| **claude-code** | autonomous-ai-agents | builder | reviewer, coordinator | specialist | 📦 Available: Delegate to Claude Code CLI (requires auth) |
| **codex** | autonomous-ai-agents | builder | reviewer, coordinator | specialist | 📦 Available: Delegate to OpenAI Codex CLI |
| **hermes-agent** | autonomous-ai-agents | coordinator | all | core | ✅ Fills gap: Hermes self-management (profiles, skills, gateway, etc.) |
| **hermes-kanban-multi-agent** | autonomous-ai-agents | workflowreconciler | coordinator, planner | specialist | ✅ Fills gap: Kanban execution ledger for parallel workers |
| **hermes-model-routing** | autonomous-ai-agents | coordinator | all | specialist | ✅ Fills gap: Cost-aware model routing across profiles |
| **opencode** | autonomous-ai-agents | builder | reviewer | specialist | 📦 Available: Delegate to OpenCode CLI |
| **ui-ux-designer** | creative | ui-ux-designer | planner, researcher, writer | specialist | ✅ Fills gap: 6-stage design workflow (wireframes→handoff) |
| **writer** | creative | writer | planner, researcher, coordinator | specialist | ✅ Fills gap: 9 writing types, 6-stage pipeline, style guide |
| **architecture-diagram** | creative | ui-ux-designer | planner, writer | specialist | ✅ Fills gap: Dark-themed SVG architecture diagrams |
| **architecture-diagram-wrapper** | creative | ui-ux-designer | planner, writer | specialist | ✅ Fills gap: Programmatic interface to architecture-diagram |
| **baoyu-infographic** | creative | ui-ux-designer | writer | specialist | 📦 Available: 21×21 layout×style infographics |
| **claude-design** | creative | ui-ux-designer | writer | specialist | 📦 Available: One-off HTML artifacts (landing, deck, prototype) |
| **claude-design-wrapper** | creative | ui-ux-designer | writer | specialist | ✅ Fills gap: Programmatic interface to claude-design |
| **design-an-interface** | creative | ui-ux-designer | planner | specialist | ✅ Fills gap: Multiple radically different interface designs |
| **design-md** | creative | ui-ux-designer | writer | specialist | ✅ Fills gap: Google DESIGN.md token spec authoring/validation |
| **excalidraw** | creative | ui-ux-designer | planner, writer | specialist | ✅ Fills gap: Hand-drawn Excalidraw JSON diagrams |
| **excalidraw-wrapper** | creative | ui-ux-designer | planner, writer | specialist | ✅ Fills gap: Programmatic interface to excalidraw |
| **impeccable-design-polish** | creative | ui-ux-designer | writer | specialist | ⚠️ Missing SKILL.md — reference only |
| **popular-web-designs** | creative | ui-ux-designer | writer | specialist | ✅ Fills gap: 54 real design systems as reference |
| **popular-web-designs-wrapper** | creative | ui-ux-designer | writer | specialist | ✅ Fills gap: Programmatic interface to design systems |
| **ascii-art** | creative | ui-ux-designer | writer | specialist | 📦 Available: Text banners, boxes, image-to-ASCII |
| **p5js** | creative | ui-ux-designer | writer | specialist | 📦 Available: Generative art, shaders, interactive sketches |
| **p5js-wrapper** | creative | ui-ux-designer | writer | specialist | ✅ Fills gap: Programmatic interface to p5js |
| **humanizer** | creative | writer | ui-ux-designer | specialist | ✅ Fills gap: Strip AI-isms, add human voice |
| **pretext** | creative | ui-ux-designer | writer | specialist | 📦 Available: DOM-free text layout for ASCII/typography |
| **sketch** | creative | ui-ux-designer | planner, writer | specialist | 📦 Available: Throwaway HTML mockups (2-3 variants) |
| **songwriting-and-ai-music** | creative | writer | ui-ux-designer | specialist | 📦 Available: Songwriting craft + Suno prompts |
| **touchdesigner-mcp** | creative | ui-ux-designer | writer | specialist | 📦 Available: Real-time visuals via TouchDesigner MCP |
| **manim-video** | creative | ui-ux-designer | writer | specialist | ✅ Fills gap: 3Blue1Brown-style math/algorithm animations |
| **ascii-video** | creative | ui-ux-designer | writer | specialist | 📦 Available: ASCII video pipeline (video/audio→ASCII MP4/GIF) |
| **arxiv** | research | researcher | planner, writer | specialist | ✅ Fills gap: arXiv search, Semantic Scholar citations, BibTeX |
| **blogwatcher** | research | researcher | writer, coordinator | specialist | 📦 Available: RSS/Atom feed monitoring |
| **llm-wiki** | research | researcher | writer, planner | specialist | ✅ Fills gap: Karpathy's LLM Wiki — compounding knowledge base |
| **polymarket** | research | researcher | planner | specialist | 📦 Available: Prediction market data querying |
| **research-paper-writing** | research | researcher | writer, planner | specialist | ✅ Fills gap: End-to-end ML paper pipeline (NeurIPS/ICML/ICLR) |
| **jupyter-live-kernel** | data-science | researcher | builder | specialist | 📦 Available: Stateful Jupyter kernel for iterative exploration |
| **evaluating-llms-harness** | mlops | reviewer | researcher, builder | specialist | ✅ Fills gap: lm-eval-harness benchmarking (MMLU, GSM8K, etc.) |
| **weights-and-biases** | mlops | builder | researcher, reviewer | specialist | 📦 Available: W&B experiment tracking, sweeps, model registry |
| **huggingface-hub** | mlops | builder | researcher, reviewer | specialist | 📦 Available: HF Hub CLI — models, datasets, spaces |
| **llama-cpp** | mlops | builder | researcher, deploy | specialist | ✅ Fills gap: Local GGUF inference + HF model discovery |
| **serving-llms-vllm** | mlops | deploy | builder, monitor | specialist | ✅ Fills gap: High-throughput LLM serving (PagedAttention) |
| **audiocraft-audio-generation** | mlops | ui-ux-designer | writer | specialist | 📦 Available: MusicGen/AudioGen text-to-music/audio |
| **segment-anything-model** | mlops | ui-ux-designer | writer, builder | specialist | 📦 Available: SAM zero-shot image segmentation |
| **obsidian** | note-taking | researcher | writer, coordinator | specialist | ✅ Fills gap: Filesystem-first Obsidian vault work |
| **airtable** | productivity | coordinator | researcher, writer | specialist | 📦 Available: Airtable REST API via curl |
| **google-workspace** | productivity | coordinator | researcher, writer | specialist | 📦 Available: Gmail, Calendar, Drive, Sheets, Docs via OAuth |
| **notion** | productivity | researcher | writer, coordinator | specialist | ✅ Fills gap: Notion API + ntn CLI (pages, databases, Workers) |
| **maps** | productivity | researcher | writer, coordinator | specialist | 📦 Available: Geocoding, POIs, routes via OSM/OSRM |
| **nano-pdf** | productivity | writer | researcher | specialist | 📦 Available: Edit PDF text via natural language |
| **petdex** | productivity | coordinator | all | specialist | 📦 Available: Animated terminal mascots |
| **powerpoint** | productivity | writer | ui-ux-designer, researcher | specialist | ✅ Fills gap: .pptx creation/editing with design QA |
| **ocr-and-documents** | productivity | researcher | writer, builder | specialist | ✅ Fills gap: PDF extraction (pymupdf + marker-pdf for OCR) |
| **teams-meeting-pipeline** | productivity | coordinator | workflowreconciler, writer | specialist | ✅ Fills gap: Teams meeting summaries, Graph subscriptions |
| **himalaya** | email | coordinator | researcher | specialist | 📦 Available: IMAP/SMTP email via CLI |
| **apple-notes** | apple | researcher | writer, coordinator | specialist | 📦 Available: Apple Notes via memo CLI (macOS only) |
| **apple-reminders** | apple | coordinator | planner | specialist | 📦 Available: Apple Reminders via remindctl (macOS only) |
| **findmy** | apple | coordinator | researcher | specialist | 📦 Available: Find My devices/AirTags via AppleScript (macOS only) |
| **imessage** | apple | coordinator | researcher | specialist | 📦 Available: iMessage/SMS via imsg CLI (macOS only) |
| **openhue** | smart-home | coordinator | deploy, monitor | specialist | 📦 Available: Philips Hue control via CLI |
| **xurl** | social-media | coordinator | writer, researcher | specialist | ✅ Fills gap: X/Twitter API v2 via official CLI |
| **gif-search** | media | writer | ui-ux-designer | specialist | 📦 Available: Tenor GIF search/download |
| **heartmula** | media | ui-ux-designer | writer | specialist | 📦 Available: Open-source music generation (HeartMuLa/HeartCodec) |
| **songsee** | media | ui-ux-designer | writer | specialist | 📦 Available: Audio spectrograms/features visualization |
| **youtube-content** | media | writer | researcher, ui-ux-designer | specialist | ✅ Fills gap: YouTube transcripts → summaries/threads/blogs |
| **github-issues** | github | coordinator | workflowreconciler, planner | specialist | ✅ Fills gap: GitHub Issues CRUD via gh/REST |
| **codebase-inspection** | github | researcher | reviewer, builder | specialist | 📦 Available: pygount LOC/language analysis |
| **github-auth** | github | coordinator | all | specialist | 📦 Available: GitHub auth setup (PAT, SSH, gh CLI) |
| **github-code-review** | github | reviewer | coordinator, builder | specialist | ✅ Fills gap: PR review with inline comments via gh/REST |
| **github-pr-workflow** | github | builder | reviewer, coordinator | specialist | ✅ Fills gap: Complete PR lifecycle (branch→CI→merge) |
| **github-repo-management** | github | coordinator | builder, deploy | specialist | 📦 Available: Repo CRUD, forks, releases, secrets, Actions |

---

## Summary by Profile

### Core Profile Loads (auto-load on profile activation)

| Profile | Core Skills (always loaded) |
|---------|----------------------------|
| **coordinator** | credential-manager, plan, telemetry, receptionist-base, hermes-agent, hermes-model-routing |
| **planner** | plan, test-driven-development, telemetry |
| **researcher** | telemetry, arxiv, llm-wiki, ocr-and-documents, youtube-content |
| **builder** | test-driven-development, systematic-debugging, telemetry |
| **reviewer** | requesting-code-review, telemetry |
| **workflowreconciler** | kanban-github-mirror, telemetry, hermes-kanban-multi-agent |
| **monitor** | telemetry, behaviour-validator |
| **deploy** | telemetry, serving-llms-vllm |
| **credential-manager** | credential-manager, telemetry |
| **ui-ux-designer** | telemetry, ui-ux-designer, architecture-diagram, design-md |
| **writer** | telemetry, writer, humanizer |
| **plan-auditor** | telemetry, plan-auditor |
| **behaviour-validator** | telemetry, behaviour-validator |
| **receptionist-*** | receptionist-base, telemetry, respective receptionist skill |

### Specialist Loads (on-demand)

Each profile loads relevant specialist skills when the task requires them. See full table for mappings.

---

## Architecture Gaps Filled by Installed Skills

| Gap ID | Architecture Gap | Filled By |
|--------|------------------|-----------|
| G-01 | Centralized secret management for all receptionists | credential-manager |
| G-02 | Shared workspace memory for multi-agent runs | (architecture-defined, not skill) |
| G-03 | Builder ↔ Pi vault access via volume mount | receptionist-pi + receptionist-obsidian |
| G-04 | Skill manifest schema + interface generation | swarm-interface-generation |
| G-05 | Skill maturity + error taxonomy + retry policy | All skills with skill.yaml |
| G-06 | Dispatch contract validation | agent-orchestration |
| G-08 | Skill versioning + breaking change tracking | hermes-agent-skill-authoring |
| — | Adversarial plan review before implementation | plan-auditor |
| — | BVC contract execution in production | behaviour-validator |
| — | OpenTelemetry observability across all profiles | telemetry |
| — | Receptionist pattern for 6 external systems | receptionist-base + 6 concrete |
| — | Cost-aware model routing | hermes-model-routing |
| — | Kanban↔GitHub mirror for workflow state | kanban-github-mirror |
| — | Multi-runtime orchestration around GitHub Issues | agent-orchestration |
| — | Parallel interface generation for 17 skills | swarm-interface-generation |
| — | TDD-compliant implementation planning | plan |
| — | 4-phase root cause debugging | systematic-debugging |
| — | Karpathy's compounding knowledge base | llm-wiki |
| — | End-to-end ML paper pipeline | research-paper-writing |
| — | arXiv + Semantic Scholar research | arxiv |
| — | YouTube content transformation | youtube-content |
| — | 6-stage UI/UX design workflow | ui-ux-designer |
| — | 9-type writing pipeline with style guide | writer |
| — | Notion API with ntn CLI + Workers | notion |
| — | PDF extraction (text + OCR) | ocr-and-documents |
| — | Teams meeting pipeline + Graph subscriptions | teams-meeting-pipeline |
| — | X/Twitter API v2 official CLI | xurl |
| — | High-throughput LLM serving | serving-llms-vllm |
| — | Local GGUF inference + HF discovery | llama-cpp |
| — | lm-eval-harness benchmarking | evaluating-llms-harness |
| — | Manim math/algorithm animations | manim-video |

---

## Redundancies / Overlaps to Resolve

| Skill | Overlaps With | Recommendation |
|-------|---------------|----------------|
| requesting-code-review | review (custom) | Prefer `review` for broader scope; use `requesting-code-review` for pre-commit gate only |
| claude-code / codex / opencode | builder profile delegation | Keep all three — different providers, different strengths |
| architecture-diagram vs architecture-diagram-wrapper | Wrapper adds programmatic interface | Keep both — creative skill + programmatic wrapper pattern |
| claude-design vs claude-design-wrapper | Same pattern | Keep both |
| excalidraw vs excalidraw-wrapper | Same pattern | Keep both |
| popular-web-designs vs popular-web-designs-wrapper | Same pattern | Keep both |
| p5js vs p5js-wrapper | Same pattern | Keep both |

---

## Skills Not Yet Mapped to Architecture (Available but Unassigned)

These skills are installed and functional but don't have a clear home in the current 12-profile architecture. Consider creating new specialist profiles or assigning to existing profiles as needs emerge:

- **Creative:** baoyu-infographic, impeccable-design-polish, ascii-art, sketch, songwriting-and-ai-music, touchdesigner-mcp, ascii-video, pretext
- **Research:** blogwatcher, polymarket
- **MLOps:** weights-and-biases, huggingface-hub, audiocraft-audio-generation, segment-anything-model
- **Productivity:** airtable, google-workspace, maps, nano-pdf, petdex, himalaya
- **Apple:** apple-notes, apple-reminders, findmy, imessage (macOS only)
- **Smart Home:** openhue
- **Media:** gif-search, heartmula, songsee
- **Social Media:** xurl (mapped to coordinator but could be specialist)
- **GitHub:** codebase-inspection, github-auth, github-repo-management
- **Debugging:** node-inspect-debugger, python-debugpy, simplify-code, cli-markdown-safety
- **Autonomous:** hermes-agent-skill-authoring
- **Data Science:** jupyter-live-kernel

---

## Next Steps

1. **Create skill.yaml manifests** for all 101 skills matching `schemas/skill-manifest.schema.json`
2. **Generate interfaces** via `swarm-interface-generation` swarm pattern (3 workers)
3. **Validate** with `validate_skill_manifest.py --strict`
4. **Assign unassigned skills** to profiles as architecture evolves
5. **Deprecate/consolidate** redundant skills after profiling usage