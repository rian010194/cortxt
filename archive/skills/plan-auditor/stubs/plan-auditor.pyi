"""
Auto-generated Python stubs for plan-auditor
Generated from skill.yaml — DO NOT EDIT MANUALLY
Run: python scripts/generate_interfaces.py
"""

from typing import Any, Dict, List, Literal, Optional, TypedDict, Union

class PlanauditorContext(TypedDict):
    run_id: str
    agent_id: str
    trace_id: str
    priority: Literal["normal", "high", "low"]
    timeout_ms: Optional[int]

class PlanauditorRequest(TypedDict):
    action: str
    resource: str
    params: Dict[str, Any]
    context: PlanauditorContext

class PlanauditorMetadata(TypedDict):
    request_id: str
    timestamp: str
    duration_ms: int
    rate_limit_remaining: int
    rate_limit_reset: str
    cache_hit: bool
    pagination: Optional[Dict[str, int]]

class PlanauditorError(TypedDict):
    code: str
    message: str
    details: Optional[Dict[str, Any]]
    recovery_hint: Optional[Literal["refresh_token", "backoff_retry", "check_permissions", "contact_admin"]]

class PlanauditorResponse(TypedDict):
    success: bool
    data: Optional[Any]
    metadata: PlanauditorMetadata
    links: Optional[Dict[str, str]]
    errors: Optional[List[PlanauditorError]]

# Skill interface
class PlanauditorSkill:
    async def call(self, request: PlanauditorRequest) -> PlanauditorResponse: ...

# Error codes (from manifest)
PLANAUDITOR_ERROR_CODES = [
    "AUTH_EXPIRED",
    "RATE_LIMITED",
    "NOT_FOUND",
    "VALIDATION_ERROR",
    "UPSTREAM_ERROR",
    "TIMEOUT",
    "PERMISSION_DENIED",
    # Add skill-specific codes here
]
