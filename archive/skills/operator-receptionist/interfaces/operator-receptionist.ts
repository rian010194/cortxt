export interface OperatorRequest {
  intent: string;
  language?: "sv" | "en";
  urgency?: "low" | "normal" | "high";
}

export interface IssuePlan {
  title: string;
  scope: string;
  acceptance_criteria: string[];
  budget: {
    max_runtime_seconds: number;
    max_cost_usd: number;
  };
  worker_role: "researcher" | "builder" | "reviewer";
  model: string;
  provider: string;
}

export interface DispatchResult {
  issue_id: number;
  issue_url: string;
  run_id: string;
  status: "succeeded" | "failed" | "blocked" | "cancelled";
  worker_role: string;
  model: string;
  cost_usd: number;
  duration_seconds: number;
  artifacts: string[];
  evidence: string;
}
