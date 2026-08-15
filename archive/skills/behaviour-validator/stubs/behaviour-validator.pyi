"""
Auto-generated Python stubs for behaviour-validator
Generated from skill.yaml — DO NOT EDIT MANUALLY
Run: python scripts/generate_interfaces.py
"""

from typing import Any, Dict, List, Literal, Optional, TypedDict, Union

class BehaviourvalidatorContext(TypedDict):
    run_id: str
    agent_id: str
    trace_id: str
    priority: Literal["normal", "high", "low"]
    timeout_ms: Optional[int]

class BehaviourvalidatorRequest(TypedDict):
    action: str
    resource: str
    params: Dict[str, Any]
    context: BehaviourvalidatorContext

class BehaviourvalidatorMetadata(TypedDict):
    request_id: str
    timestamp: str
    duration_ms: int
    rate_limit_remaining: int
    rate_limit_reset: str
    cache_hit: bool
    pagination: Optional[Dict[str, int]]

class BehaviourvalidatorError(TypedDict):
    code: str
    message: str
    details: Optional[Dict[str, Any]]
    recovery_hint: Optional[Literal["refresh_token", "backoff_retry", "check_permissions", "contact_admin"]]

class BehaviourvalidatorResponse(TypedDict):
    success: bool
    data: Optional[Any]
    metadata: BehaviourvalidatorMetadata
    links: Optional[Dict[str, str]]
    errors: Optional[List[BehaviourvalidatorError]]

# Skill interface
class BehaviourvalidatorSkill:
    async def call(self, request: BehaviourvalidatorRequest) -> BehaviourvalidatorResponse: ...

# Error codes (from manifest)
BEHAVIOURVALIDATOR_ERROR_CODES = [
    "AUTH_EXPIRED",
    "RATE_LIMITED",
    "NOT_FOUND",
    "VALIDATION_ERROR",
    "UPSTREAM_ERROR",
    "TIMEOUT",
    "PERMISSION_DENIED",
    # Add skill-specific codes here
]
