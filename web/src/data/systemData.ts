export interface Profile {
  id: string;
  name: string;
  model: string;
  provider: string;
  usage: string;
  costTier: string;
  latency: string;
  status: 'verified' | 'experimental' | 'blocked';
  skills: string[];
  category: string;
  costPer1MInput?: number;
  costPer1MOutput?: number;
  costCurrency?: string;
  dailyLimit?: number; // for free-tier models (requests per day)
}

export interface Skill {
  name: string;
  category: string;
  primaryProfile: string;
  secondaryProfiles: string[];
  loadStrategy: 'core' | 'specialist' | 'conditional';
  maturity: 'experimental' | 'stable' | 'deprecated';
  notes: string;
}

export interface BVC {
  name: string;
  description: string;
  threshold: string;
  severity: 'critical' | 'warning' | 'info';
}

export interface VerticalStep {
  name: string;
  role: string;
  description: string;
  artifacts: string[];
}

export const profiles: Profile[] = [
  { id: 'coordinator', name: 'Coordinator', model: 'nemotron-3-ultra', provider: 'OpenRouter', usage: 'Planning, klassificering, synthesis, routing', costTier: 'free', latency: '<2s', status: 'verified', skills: ['credential-manager','plan','telemetry','receptionist-base','hermes-agent','hermes-model-routing'], category: 'Orchestration', costPer1MInput: 0, costPer1MOutput: 0, costCurrency: 'USD' },
  { id: 'researcher', name: 'Researcher', model: 'kimi-k2.6', provider: 'Moonshot', usage: 'Djupgående analys, fakta-sökning, research', costTier: 'low', latency: '<5m', status: 'verified', skills: ['telemetry','arxiv','llm-wiki','ocr-and-documents','youtube-content'], category: 'Research', costPer1MInput: 0.55, costPer1MOutput: 2.65, costCurrency: 'USD' },
  { id: 'planner', name: 'Planner', model: 'kimi-k2.6', provider: 'Moonshot', usage: 'Detaljerad planering, task-brytning', costTier: 'low', latency: '<5m', status: 'verified', skills: ['plan','test-driven-development','telemetry'], category: 'Orchestration', costPer1MInput: 0.55, costPer1MOutput: 2.65, costCurrency: 'USD' },
  { id: 'builder', name: 'Builder', model: 'kimi-k2.6', provider: 'Moonshot (via Pi)', usage: 'Bounded file writes, kod, konfig, artifacts', costTier: 'medium', latency: 'async', status: 'verified', skills: ['test-driven-development','systematic-debugging','telemetry'], category: 'Implementation', costPer1MInput: 0.55, costPer1MOutput: 2.65, costCurrency: 'USD' },
  { id: 'reviewer', name: 'Reviewer', model: 'codex', provider: 'OpenAI', usage: 'Architecture/security review, PR review', costTier: 'premium', latency: 'async', status: 'verified', skills: ['requesting-code-review','telemetry'], category: 'Review', costPer1MInput: 1.75, costPer1MOutput: 14.0, costCurrency: 'USD' },
  { id: 'workflowreconciler', name: 'Workflow Reconciler', model: 'nemotron-3-ultra', provider: 'OpenRouter', usage: 'Kanban↔GitHub mirror, workflow state reconciliation', costTier: 'free', latency: '<5m', status: 'verified', skills: ['kanban-github-mirror','telemetry','hermes-kanban-multi-agent'], category: 'Operations', costPer1MInput: 0, costPer1MOutput: 0, costCurrency: 'USD' },
  { id: 'credential-manager', name: 'Credential Manager', model: 'nemotron-3-ultra', provider: 'OpenRouter', usage: 'Centraliserad secret-hantering, vault-integration', costTier: 'free', latency: '<2s', status: 'verified', skills: ['credential-manager','telemetry'], category: 'Orchestration', costPer1MInput: 0, costPer1MOutput: 0, costCurrency: 'USD' },
  { id: 'ui-ux-designer', name: 'UI/UX Designer', model: 'kimi-k2.6', provider: 'Moonshot', usage: 'Wireframes → design tokens → handoff spec', costTier: 'low', latency: 'async', status: 'experimental', skills: ['telemetry','ui-ux-designer','architecture-diagram','design-md'], category: 'Specialist', costPer1MInput: 0.55, costPer1MOutput: 2.65, costCurrency: 'USD' },
  { id: 'writer', name: 'Writer', model: 'kimi-k2.6', provider: 'Moonshot', usage: 'Docs, bloggar, PR-beskrivningar, release notes', costTier: 'low', latency: 'async', status: 'experimental', skills: ['telemetry','writer','humanizer'], category: 'Specialist', costPer1MInput: 0.55, costPer1MOutput: 2.65, costCurrency: 'USD' },
  { id: 'plan-auditor', name: 'Plan Auditor', model: 'nemotron-3-ultra', provider: 'OpenRouter', usage: 'Adversarial review-cykel (2-3 iterationer, fresh eyes)', costTier: 'free', latency: 'async', status: 'experimental', skills: ['telemetry','plan-auditor'], category: 'Review', costPer1MInput: 0, costPer1MOutput: 0, costCurrency: 'USD' },
  { id: 'behaviour-validator', name: 'Behaviour Validator', model: 'nemotron-3-ultra', provider: 'OpenRouter', usage: 'Kör BVC-kontrakt i prod, loggar avvikelser, alertar', costTier: 'free', latency: 'batch', status: 'experimental', skills: ['telemetry','behaviour-validator'], category: 'Operations', costPer1MInput: 0, costPer1MOutput: 0, costCurrency: 'USD' },
  // Free-tier fallbacks (OpenRouter)
  { id: 'researcher-free', name: 'Researcher (Free)', model: 'kimi-k2.6:free', provider: 'OpenRouter', usage: 'Djupanalys, research — gratis fallback', costTier: 'free', latency: '<5m', status: 'verified', skills: ['telemetry','arxiv','llm-wiki','ocr-and-documents','youtube-content'], category: 'Research', costPer1MInput: 0, costPer1MOutput: 0, costCurrency: 'USD', dailyLimit: 300 },
  { id: 'builder-free', name: 'Builder (Free)', model: 'qwen3-coder:free', provider: 'OpenRouter', usage: 'Kod, konfig — gratis fallback', costTier: 'free', latency: '<2m', status: 'experimental', skills: ['test-driven-development','systematic-debugging','telemetry'], category: 'Implementation', costPer1MInput: 0, costPer1MOutput: 0, costCurrency: 'USD', dailyLimit: 200 },
  { id: 'planner-free', name: 'Planner (Free)', model: 'qwen3-coder:free', provider: 'OpenRouter', usage: 'Planering, task-brytning — gratis fallback', costTier: 'free', latency: '<2m', status: 'experimental', skills: ['plan','test-driven-development','telemetry'], category: 'Orchestration', costPer1MInput: 0, costPer1MOutput: 0, costCurrency: 'USD', dailyLimit: 200 },
];

export const fallbackChains: Record<string, string[]> = {
  researcher: ['researcher-free', 'researcher', 'planner-free'],
  builder: ['builder-free', 'builder', 'planner-free'],
  planner: ['planner-free', 'planner', 'coordinator'],
  reviewer: ['reviewer', 'plan-auditor'],
  coordinator: ['coordinator', 'workflowreconciler'],
};

export const rateLimitStatus = {
  'researcher-free': { used: 47, limit: 300, resetsAt: '2026-08-05T00:00:00Z' },
  'builder-free': { used: 12, limit: 200, resetsAt: '2026-08-05T00:00:00Z' },
  'planner-free': { used: 8, limit: 200, resetsAt: '2026-08-05T00:00:00Z' },
  'coordinator': { used: 156, limit: Infinity, resetsAt: null },
  'researcher': { used: 23, limit: Infinity, resetsAt: null },
};

export interface SessionRun {
  id: string;
  task: string;
  description: string;
  status: 'success' | 'failed' | 'in_progress';
  cost: number;
  duration: string;
  tokens: string;
  phases: { name: string; duration: string; agent: string; status: 'done' | 'active' | 'pending' }[];
  gates: { name: string; passed: boolean }[];
  startedAt: string;
}

export const sessions: SessionRun[] = [
  {
    id: 'ad066baa',
    task: 'adw_plan_build_test',
    description: 'Add a light mode to contrast the default dark mode, and build...',
    status: 'success',
    cost: 0.6742,
    duration: '2m 41s',
    tokens: '1.11M',
    phases: [
      { name: 'request', duration: '0.00s', agent: 'engineer', status: 'done' },
      { name: 'plan', duration: '1m 37s', agent: 'planner', status: 'done' },
      { name: 'build', duration: '1m 04s', agent: 'builder', status: 'done' },
    ],
    gates: [
      { name: 'Syntax', passed: true },
      { name: 'Tests', passed: true },
      { name: 'Review', passed: true },
    ],
    startedAt: 'Jul 29 11:44:29',
  },
  {
    id: '048f96d8',
    task: 'adw_simple_sdlc',
    description: 'Implement EU AI Act classification workflow with BVC validation',
    status: 'success',
    cost: 1.24,
    duration: '8m 07s',
    tokens: '7.74M',
    phases: [
      { name: 'request', duration: '0.00s', agent: 'engineer', status: 'done' },
      { name: 'plan', duration: '2m 15s', agent: 'planner', status: 'done' },
      { name: 'build', duration: '4m 30s', agent: 'builder', status: 'done' },
      { name: 'test', duration: '1m 22s', agent: 'reviewer', status: 'done' },
    ],
    gates: [
      { name: 'Syntax', passed: true },
      { name: 'Tests', passed: true },
      { name: 'Review', passed: true },
      { name: 'BVC', passed: true },
    ],
    startedAt: 'Aug 04 08:30:15',
  },
  {
    id: '7d3e9a12',
    task: 'adw_scout',
    description: 'Research OpenRouter free model tier list and pricing updates',
    status: 'in_progress',
    cost: 0.08,
    duration: '0m 45s',
    tokens: '245k',
    phases: [
      { name: 'request', duration: '0.00s', agent: 'engineer', status: 'done' },
      { name: 'plan', duration: '0m 15s', agent: 'planner', status: 'done' },
      { name: 'build', duration: '0m 30s', agent: 'builder', status: 'active' },
    ],
    gates: [
      { name: 'Syntax', passed: true },
      { name: 'Tests', passed: false },
      { name: 'Review', passed: false },
    ],
    startedAt: 'Aug 04 11:42:00',
  },
  {
    id: '9f1b4c55',
    task: 'adw_plan_build_test',
    description: 'Build cost telemetry dashboard with fallback chains',
    status: 'success',
    cost: 0.32,
    duration: '3m 12s',
    tokens: '1.89M',
    phases: [
      { name: 'request', duration: '0.00s', agent: 'engineer', status: 'done' },
      { name: 'plan', duration: '0m 45s', agent: 'planner', status: 'done' },
      { name: 'build', duration: '2m 27s', agent: 'builder', status: 'done' },
    ],
    gates: [
      { name: 'Syntax', passed: true },
      { name: 'Tests', passed: true },
      { name: 'Review', passed: true },
    ],
    startedAt: 'Aug 04 10:15:33',
  },
  {
    id: 'e2a8f6d1',
    task: 'adw_simple_sdlc',
    description: 'Fix Kanban→GitHub mirror sync issue with blocked tasks',
    status: 'failed',
    cost: 0.15,
    duration: '1m 55s',
    tokens: '890k',
    phases: [
      { name: 'request', duration: '0.00s', agent: 'engineer', status: 'done' },
      { name: 'plan', duration: '0m 30s', agent: 'planner', status: 'done' },
      { name: 'build', duration: '1m 25s', agent: 'builder', status: 'done' },
    ],
    gates: [
      { name: 'Syntax', passed: true },
      { name: 'Tests', passed: false },
      { name: 'Review', passed: false },
    ],
    startedAt: 'Aug 03 16:22:10',
  },
  {
    id: 'b5c3d7e9',
    task: 'adw_plan_build_test',
    description: 'Add free-tier model fallbacks (kimi-k2.6:free, qwen3-coder:free)',
    status: 'success',
    cost: 0.18,
    duration: '2m 08s',
    tokens: '1.05M',
    phases: [
      { name: 'request', duration: '0.00s', agent: 'engineer', status: 'done' },
      { name: 'plan', duration: '0m 38s', agent: 'planner', status: 'done' },
      { name: 'build', duration: '1m 30s', agent: 'builder', status: 'done' },
    ],
    gates: [
      { name: 'Syntax', passed: true },
      { name: 'Tests', passed: true },
      { name: 'Review', passed: true },
    ],
    startedAt: 'Aug 04 09:05:22',
  },
];

export const receptionists = [
  { name: 'receptionist-obsidian', system: 'Obsidian', capabilities: ['CRUD','search','webhook','vault access'], status: 'verified' },
  { name: 'receptionist-notion', system: 'Notion', capabilities: ['CRUD','search','webhook','database query'], status: 'verified' },
  { name: 'receptionist-buzz', system: 'Buzz', capabilities: ['Messaging','approval-flow','operator dialog','marker routing'], status: 'partial' },
  { name: 'receptionist-hermes', system: 'Hermes', capabilities: ['Profile mgmt','skill mgmt','kanban','dispatch','cron'], status: 'verified' },
  { name: 'receptionist-pi', system: 'Pi Builder', capabilities: ['Container lifecycle','bounded writes','egress rules'], status: 'experimental' },
  { name: 'receptionist-codex', system: 'Codex', capabilities: ['App-server API','chat mgmt','review dispatch'], status: 'verified' },
];

export const skills: Skill[] = [
  { name: 'credential-manager', category: 'software-development', primaryProfile: 'credential-manager', secondaryProfiles: ['coordinator','all receptionists'], loadStrategy: 'core', maturity: 'experimental', notes: 'Centralized vault abstraction' },
  { name: 'kanban-github-mirror', category: 'software-development', primaryProfile: 'workflowreconciler', secondaryProfiles: ['coordinator','deploy'], loadStrategy: 'specialist', maturity: 'experimental', notes: 'Kanban↔GitHub sync' },
  { name: 'plan', category: 'software-development', primaryProfile: 'planner', secondaryProfiles: ['coordinator','builder'], loadStrategy: 'core', maturity: 'stable', notes: 'TDD-compliant planning' },
  { name: 'plan-auditor', category: 'software-development', primaryProfile: 'plan-auditor', secondaryProfiles: ['coordinator','reviewer'], loadStrategy: 'specialist', maturity: 'experimental', notes: 'Adversarial multi-iteration audit' },
  { name: 'behaviour-validator', category: 'software-development', primaryProfile: 'behaviour-validator', secondaryProfiles: ['monitor','reviewer'], loadStrategy: 'specialist', maturity: 'experimental', notes: 'BVC contract runner' },
  { name: 'telemetry', category: 'software-development', primaryProfile: 'monitor', secondaryProfiles: ['all profiles'], loadStrategy: 'core', maturity: 'stable', notes: 'OpenTelemetry observability' },
  { name: 'receptionist-base', category: 'software-development', primaryProfile: 'coordinator', secondaryProfiles: ['all receptionists'], loadStrategy: 'core', maturity: 'experimental', notes: 'Generic base for 6 receptionists' },
  { name: 'hermes-agent', category: 'autonomous-ai-agents', primaryProfile: 'coordinator', secondaryProfiles: ['all'], loadStrategy: 'core', maturity: 'stable', notes: 'Hermes self-management' },
  { name: 'hermes-kanban-multi-agent', category: 'autonomous-ai-agents', primaryProfile: 'workflowreconciler', secondaryProfiles: ['coordinator','planner'], loadStrategy: 'specialist', maturity: 'experimental', notes: 'Kanban execution ledger' },
  { name: 'hermes-model-routing', category: 'autonomous-ai-agents', primaryProfile: 'coordinator', secondaryProfiles: ['all'], loadStrategy: 'specialist', maturity: 'experimental', notes: 'Cost-aware model routing' },
  { name: 'agent-orchestration', category: 'autonomous-ai-agents', primaryProfile: 'coordinator', secondaryProfiles: ['workflowreconciler','planner'], loadStrategy: 'specialist', maturity: 'experimental', notes: 'Multi-runtime orchestration' },
  { name: 'swarm-interface-generation', category: 'autonomous-ai-agents', primaryProfile: 'coordinator', secondaryProfiles: ['builder'], loadStrategy: 'specialist', maturity: 'experimental', notes: 'Parallel interface generation' },
  { name: 'test-driven-development', category: 'software-development', primaryProfile: 'builder', secondaryProfiles: ['reviewer','planner'], loadStrategy: 'core', maturity: 'stable', notes: 'RED-GREEN-REFACTOR enforcement' },
  { name: 'systematic-debugging', category: 'software-development', primaryProfile: 'builder', secondaryProfiles: ['reviewer','researcher'], loadStrategy: 'specialist', maturity: 'stable', notes: '4-phase root cause debugging' },
  { name: 'spike', category: 'software-development', primaryProfile: 'researcher', secondaryProfiles: ['planner','builder'], loadStrategy: 'specialist', maturity: 'stable', notes: 'Throwaway experiments' },
  { name: 'strategic-discovery', category: 'software-development', primaryProfile: 'coordinator', secondaryProfiles: ['planner','researcher'], loadStrategy: 'specialist', maturity: 'stable', notes: 'Strategic direction exploration' },
  { name: 'ui-ux-designer', category: 'creative', primaryProfile: 'ui-ux-designer', secondaryProfiles: ['planner','researcher','writer'], loadStrategy: 'specialist', maturity: 'experimental', notes: '6-stage design workflow' },
  { name: 'writer', category: 'creative', primaryProfile: 'writer', secondaryProfiles: ['planner','researcher','coordinator'], loadStrategy: 'specialist', maturity: 'experimental', notes: '9 writing types, 6-stage pipeline' },
  { name: 'architecture-diagram', category: 'creative', primaryProfile: 'ui-ux-designer', secondaryProfiles: ['planner','writer'], loadStrategy: 'specialist', maturity: 'stable', notes: 'Dark-themed SVG diagrams' },
  { name: 'excalidraw', category: 'creative', primaryProfile: 'ui-ux-designer', secondaryProfiles: ['planner','writer'], loadStrategy: 'specialist', maturity: 'stable', notes: 'Hand-drawn diagrams' },
  { name: 'claude-design', category: 'creative', primaryProfile: 'ui-ux-designer', secondaryProfiles: ['writer'], loadStrategy: 'specialist', maturity: 'stable', notes: 'HTML artifacts' },
  { name: 'arxiv', category: 'research', primaryProfile: 'researcher', secondaryProfiles: ['planner','writer'], loadStrategy: 'specialist', maturity: 'stable', notes: 'arXiv + Semantic Scholar' },
  { name: 'llm-wiki', category: 'research', primaryProfile: 'researcher', secondaryProfiles: ['writer','planner'], loadStrategy: 'specialist', maturity: 'stable', notes: 'Compounding knowledge base' },
  { name: 'ocr-and-documents', category: 'productivity', primaryProfile: 'researcher', secondaryProfiles: ['writer','builder'], loadStrategy: 'specialist', maturity: 'stable', notes: 'PDF extraction' },
  { name: 'youtube-content', category: 'media', primaryProfile: 'writer', secondaryProfiles: ['researcher','ui-ux-designer'], loadStrategy: 'specialist', maturity: 'stable', notes: 'Transcripts → summaries' },
  { name: 'github-issues', category: 'github', primaryProfile: 'coordinator', secondaryProfiles: ['workflowreconciler','planner'], loadStrategy: 'specialist', maturity: 'stable', notes: 'GitHub Issues CRUD' },
  { name: 'github-code-review', category: 'github', primaryProfile: 'reviewer', secondaryProfiles: ['coordinator','builder'], loadStrategy: 'specialist', maturity: 'stable', notes: 'PR review with inline comments' },
  { name: 'github-pr-workflow', category: 'github', primaryProfile: 'builder', secondaryProfiles: ['reviewer','coordinator'], loadStrategy: 'specialist', maturity: 'stable', notes: 'Complete PR lifecycle' },
  { name: 'notion', category: 'productivity', primaryProfile: 'researcher', secondaryProfiles: ['writer','coordinator'], loadStrategy: 'specialist', maturity: 'stable', notes: 'Notion API + ntn CLI' },
  { name: 'teams-meeting-pipeline', category: 'productivity', primaryProfile: 'coordinator', secondaryProfiles: ['workflowreconciler','writer'], loadStrategy: 'specialist', maturity: 'experimental', notes: 'Teams summaries' },
  { name: 'serving-llms-vllm', category: 'mlops', primaryProfile: 'deploy', secondaryProfiles: ['builder','monitor'], loadStrategy: 'specialist', maturity: 'experimental', notes: 'High-throughput serving' },
  { name: 'llama-cpp', category: 'mlops', primaryProfile: 'builder', secondaryProfiles: ['researcher','deploy'], loadStrategy: 'specialist', maturity: 'stable', notes: 'Local GGUF inference' },
  { name: 'evaluating-llms-harness', category: 'mlops', primaryProfile: 'reviewer', secondaryProfiles: ['researcher','builder'], loadStrategy: 'specialist', maturity: 'stable', notes: 'lm-eval-harness benchmarking' },
  { name: 'manim-video', category: 'creative', primaryProfile: 'ui-ux-designer', secondaryProfiles: ['writer'], loadStrategy: 'specialist', maturity: 'experimental', notes: '3Blue1Brown-style animations' },
];

export const bvcs: BVC[] = [
  { name: 'api-error-rate', description: 'API-felrate får inte överskrida tröskel', threshold: '< 1%', severity: 'critical' },
  { name: 'api-latency-p95', description: 'P95-latens för API-anrop', threshold: '< 2000ms', severity: 'warning' },
  { name: 'daily-llm-cost', description: 'Daglig LLM-kostnad', threshold: '< $50', severity: 'warning' },
  { name: 'deployment-success-rate', description: 'Deployment-framgångsgrad', threshold: '> 95%', severity: 'critical' },
  { name: 'service-availability', description: 'Tjänstens tillgänglighet', threshold: '> 99.5%', severity: 'critical' },
];

export const kanbanColumns = [
  { id: 'backlog', name: 'Backlog', tasks: 3 },
  { id: 'triage', name: 'Triage', tasks: 1 },
  { id: 'ready', name: 'Ready', tasks: 2 },
  { id: 'in-progress', name: 'In Progress', tasks: 2 },
  { id: 'review', name: 'Review', tasks: 1 },
  { id: 'blocked', name: 'Blocked', tasks: 1 },
  { id: 'done', name: 'Done', tasks: 4 },
];

export const kanbanTasks = [
  { id: 't-1', title: 'AI Act classification workflow', column: 'done', assignee: 'researcher', issue: '#9', runId: 'run-2026-08-02-001' },
  { id: 't-2', title: 'Swarm-mode verification', column: 'done', assignee: 'coordinator', issue: '#21', runId: 'run-2026-08-03-002' },
  { id: 't-3', title: 'Kanban→GitHub mirror', column: 'done', assignee: 'workflowreconciler', issue: '#7', runId: 'run-2026-08-03-003' },
  { id: 't-4', title: 'Gateway dispatch test', column: 'done', assignee: 'coordinator', issue: '#7', runId: 'run-2026-08-03-004' },
  { id: 't-5', title: 'Vertical-01 schema design', column: 'in-progress', assignee: 'builder', issue: '#9', runId: 'run-2026-08-04-005' },
  { id: 't-6', title: 'BVC contract runner', column: 'in-progress', assignee: 'behaviour-validator', issue: '#15', runId: 'run-2026-08-04-006' },
  { id: 't-7', title: 'Cost telemetry dashboard', column: 'ready', assignee: 'monitor', issue: '#6', runId: null },
  { id: 't-8', title: 'Buzz workflow repair', column: 'blocked', assignee: 'builder', issue: '#21', runId: null },
  { id: 't-9', title: 'n8n/VPS automation plan', column: 'review', assignee: 'planner', issue: '#12', runId: 'run-2026-08-04-007' },
];

export const swarmGraph = {
  workers: [
    { id: 'w1', name: 'Researcher A', status: 'done', task: 'Article 2-3 analysis' },
    { id: 'w2', name: 'Researcher B', status: 'done', task: 'Article 5 analysis' },
    { id: 'w3', name: 'Researcher C', status: 'done', task: 'Annex III mapping' },
  ],
  verifier: { id: 'v1', name: 'Verifier', status: 'done', task: 'Cross-check findings' },
  synthesizer: { id: 's1', name: 'Synthesizer', status: 'done', task: 'Final synthesis' },
};

export const telemetryData = [
  { time: '00:00', coordinator: 0.0, researcher: 0.12, builder: 0.0, total: 0.12 },
  { time: '04:00', coordinator: 0.0, researcher: 0.0, builder: 0.0, total: 0.0 },
  { time: '08:00', coordinator: 0.02, researcher: 0.45, builder: 0.30, total: 0.77 },
  { time: '12:00', coordinator: 0.05, researcher: 0.89, builder: 0.15, total: 1.09 },
  { time: '16:00', coordinator: 0.03, researcher: 0.34, builder: 0.45, total: 0.82 },
  { time: '20:00', coordinator: 0.01, researcher: 0.22, builder: 0.10, total: 0.33 },
];

export const flowSteps = [
  {
    id: 'buzz',
    title: 'Buzz',
    subtitle: 'Operator Dialog Surface',
    description: 'Buzz är operatorns dialog- och approval-yta. Här skapas scope, godkännanden ges, och status visas.',
    verified: true,
    blockers: ['Buzz-native delegation discovery-only — by design, ej dispatch (se current-operating-model.md)', 'Hermes↔Buzz returkanal saknas — huvudluckan att bygga', 'Buzz Builder terminal: INTE reproducerbart (probe 2026-08-02 llr) — ska ej längre visas som stoppad'],
    outputs: ['GitHub Issue', 'Scope clarification'],
  },
  {
    id: 'github',
    title: 'GitHub Issues/Projects',
    subtitle: 'Source of Truth',
    description: 'Enda masterregistret för scope, workflow status, evidence, review och approval. Ingen annan backlog får existera.',
    verified: true,
    blockers: [],
    outputs: ['Approved scope', 'Acceptance criteria', 'Ready status'],
  },
  {
    id: 'dispatch',
    title: 'Dispatch',
    subtitle: 'Claim & Run Identity',
    description: 'Manuell dispatch eller gateway dispatch etablerar claim, run_id, profil och lease.',
    verified: true,
    blockers: ['General dispatcher från Ready-issue finns ej än', 'Hermes Kanban gateway limited till scratch workspaces'],
    outputs: ['run_id', 'Claim', 'Profile selection'],
  },
  {
    id: 'runtime',
    title: 'Runtime',
    subtitle: 'Hermes / Pi Builder',
    description: 'Hermes kör Coordinator/Researcher-profiler. Pi Builder kör bounded writes i isolerad container.',
    verified: true,
    blockers: ['Pi Builder är experiment, ej produktions-harness', 'Worktree mode kräver cygpath -w på Windows'],
    outputs: ['Artifacts', 'Evidence', 'Usage tokens'],
  },
  {
    id: 'review',
    title: 'Review',
    subtitle: 'Codex / Plan Auditor',
    description: 'Oberoende review av resultat. Codex för read-only architecture/security review. Plan Auditor för adversarial review.',
    verified: true,
    blockers: [],
    outputs: ['Review comments', 'Approval recommendation'],
  },
  {
    id: 'approval',
    title: 'Operator Approval',
    subtitle: 'Final Gate',
    description: 'Endast mänsklig operator får godkänna scope, merge, deploy och final completion. Ingen agent godkänner sitt eget arbete.',
    verified: true,
    blockers: [],
    outputs: ['Done status'],
  },
];

export const dispatchSchema = {
  required: ['issue_id','workflow','worker_role','scope','acceptance_criteria','max_runtime_seconds','max_cost_usd','max_parallel_workers','delegation_depth','artifact_policy','approval_ref'],
  fields: [
    { name: 'issue_id', type: 'string', pattern: '^[^/]+/[^/]+#\\d+$', example: 'rian010194/ai-workspace#9' },
    { name: 'workflow', type: 'string', example: 'vertical-01-ai-act/classify' },
    { name: 'worker_role', type: 'enum', values: ['researcher','builder','planner','reviewer','monitor'], example: 'researcher' },
    { name: 'scope', type: 'string', minLength: 10, example: 'Classify AI system under EU AI Act Articles 2-3, 5, 6' },
    { name: 'acceptance_criteria', type: 'array', example: ['Valid JSON output','All risk classes identified'] },
    { name: 'max_runtime_seconds', type: 'integer', min: 60, max: 86400, example: 3600 },
    { name: 'max_cost_usd', type: 'number', min: 0, max: 1000, example: 10.00 },
    { name: 'max_parallel_workers', type: 'integer', min: 1, example: 2 },
    { name: 'delegation_depth', type: 'integer', min: 0, example: 1 },
    { name: 'artifact_policy', type: 'enum', values: ['workspace_only','github_artifacts','external_refs'], example: 'workspace_only' },
    { name: 'approval_ref', type: 'string', format: 'uri', example: 'https://github.com/rian010194/ai-workspace/issues/9#issuecomment-123' },
  ],
};

export const resultEnvelope = {
  required: ['issue_id','run_id','status','runtime','worker_role','started_at','finished_at','model','usage','cost','artifacts','evidence'],
  statuses: ['succeeded','failed','timed_out','budget_exceeded','blocked','cancelled'],
};

export const vertical01 = {
  name: 'vertical-01-ai-act',
  version: '0.1.0',
  description: 'EU AI Act compliance assessment vertical',
  workflows: [
    { name: 'classify', description: 'Classify AI system under EU AI Act risk categories', input: 'ai-act-assessment-input.schema.json', output: 'ai-act-assessment-output.schema.json' },
    { name: 'assess-obligations', description: 'Assess compliance obligations for classified system', input: 'ai-act-assessment-output.schema.json', output: 'obligation-report.schema.json' },
  ],
  schemas: [
    'ai-act-assessment-input.schema.json',
    'ai-act-assessment-output.schema.json',
    'artifact-ref.schema.json',
    'eval-fixture.schema.json',
    'vertical-manifest.schema.json',
  ],
  evals: {
    positive: 3,
    negative: 3,
    boundary: 3,
    uncertainty: 3,
  },
  decisionBasis: ['Articles 2-3','Article 5','Article 6 (6.3-6.4)','Annex I','Annex III'],
  requirements: ['Articles 9-12 (v0.1)','Annex IV supporting Article 11'],
  deferred: ['Articles 14-15 (v0.2)'],
};

export const architectureMermaid = `
graph TD
    B[Buzz<br/>Operator Dialog] --> G[GitHub Issues/Projects<br/>Source of Truth]
    G --> D[Dispatch<br/>Claim & Run ID]
    D --> H[Hermes Runtime<br/>Coordinator/Researcher]
    D --> P[Pi Builder<br/>Bounded Writes]
    H --> R[Result Envelope]
    P --> R
    R --> C[Codex Review<br/>Read-only]
    C --> O[Operator Approval]
    O --> G
    H --> K[Hermes Kanban<br/>cortxt-cp]
    K --> M[Kanban→GitHub Mirror<br/>Cron 10min]
    M --> G
    H --> S[Swarm Mode<br/>Workers→Verifier→Synthesizer]
    style B fill:#8b5cf6,stroke:#a78bfa,color:#fff
    style G fill:#3b82f6,stroke:#60a5fa,color:#fff
    style D fill:#f59e0b,stroke:#fbbf24,color:#000
    style H fill:#10b981,stroke:#34d399,color:#fff
    style P fill:#06b6d4,stroke:#22d3ee,color:#fff
    style R fill:#ec4899,stroke:#f472b6,color:#fff
    style C fill:#f43f5e,stroke:#fb7185,color:#fff
    style O fill:#84cc16,stroke:#a3e635,color:#000
    style K fill:#6366f1,stroke:#818cf8,color:#fff
    style M fill:#8b5cf6,stroke:#a78bfa,color:#fff
    style S fill:#14b8a6,stroke:#2dd4bf,color:#fff
`;

export function calculateCost(modelId: string, inputTokens: number, outputTokens: number): { amount: number | null; currency: string; breakdown: { input: number; output: number } } {
  const profile = profiles.find(p => p.model === modelId);
  if (!profile || profile.costPer1MInput === undefined || profile.costPer1MOutput === undefined) {
    return { amount: null, currency: 'USD', breakdown: { input: 0, output: 0 } };
  }
  const inputCost = (inputTokens / 1_000_000) * profile.costPer1MInput;
  const outputCost = (outputTokens / 1_000_000) * profile.costPer1MOutput;
  return {
    amount: inputCost + outputCost,
    currency: profile.costCurrency || 'USD',
    breakdown: { input: inputCost, output: outputCost },
  };
}

export function estimateRunCost(workerRole: string, estimatedInputTokens: number, estimatedOutputTokens: number): { amount: number | null; currency: string; profile: string } {
  const profile = profiles.find(p => p.id === workerRole);
  if (!profile || profile.costPer1MInput === undefined) {
    return { amount: null, currency: 'USD', profile: workerRole };
  }
  const inputCost = (estimatedInputTokens / 1_000_000) * profile.costPer1MInput;
  const outputCost = (estimatedOutputTokens / 1_000_000) * profile.costPer1MOutput!;
  return {
    amount: inputCost + outputCost,
    currency: profile.costCurrency || 'USD',
    profile: profile.name,
  };
}
