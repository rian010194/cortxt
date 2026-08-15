/**
 * Auto-generated TypeScript interfaces for claude-design-wrapper
 * Generated from skill.yaml — DO NOT EDIT MANUALLY
 * Run: python scripts/generate_interfaces.py
 */

// Input Request
export interface claudedesignwrapperRequest {
  action: string;
  resource: string;
  params: Record<string, unknown>;
  context: {
    run_id: string;
    agent_id: string;
    trace_id: string;
    priority: "normal" | "high" | "low";
    timeout_ms?: number;
  };
}

// Output Response
export interface claudedesignwrapperResponse<T = unknown> {
  success: boolean;
  data: T | null;
  metadata: {
    request_id: string;
    timestamp: string;
    duration_ms: number;
    rate_limit_remaining: number;
    rate_limit_reset: string;
    cache_hit: boolean;
    pagination?: {
      page: number;
      page_size: number;
      total_pages: number;
      total_items: number;
    };
  };
  links?: Record<string, string>;
  errors?: claudedesignwrapperError[];
}

// Error
export interface claudedesignwrapperError {
  code: claudedesignwrapperErrorCode;
  message: string;
  details?: Record<string, unknown>;
  recovery_hint?: "refresh_token" | "backoff_retry" | "check_permissions" | "contact_admin";
}

// Error Codes (from skill manifest)
export type claudedesignwrapperErrorCode = 
  | "AUTH_EXPIRED"
  | "RATE_LIMITED"
  | "NOT_FOUND"
  | "VALIDATION_ERROR"
  | "UPSTREAM_ERROR"
  | "TIMEOUT"
  | "PERMISSION_DENIED";
  // Add skill-specific codes here

// Skill Interface
export interface claudedesignwrapperSkill {
  call(request: claudedesignwrapperRequest): Promise<claudedesignwrapperResponse>;
}
