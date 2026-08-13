"""
Auto-generated Python stubs for p5js-wrapper
Generated from skill.yaml — DO NOT EDIT MANUALLY
Run: python scripts/generate_interfaces.py
"""

from typing import Any, Dict, List, Literal, Optional, TypedDict, Union

class P5JswrapperContext(TypedDict):
    run_id: str
    agent_id: str
    trace_id: str
    priority: Literal["normal", "high", "low"]
    timeout_ms: Optional[int]

class P5JswrapperRequest(TypedDict):
    action: str
    resource: str
    params: Dict[str, Any]
    context: P5JswrapperContext

class P5JswrapperMetadata(TypedDict):
    request_id: str
    timestamp: str
    duration_ms: int
    rate_limit_remaining: int
    rate_limit_reset: str
    cache_hit: bool
    pagination: Optional[Dict[str, int]]

class P5JswrapperError(TypedDict):
    code: str
    message: str
    details: Optional[Dict[str, Any]]
    recovery_hint: Optional[Literal["refresh_token", "backoff_retry", "check_permissions", "contact_admin"]]

class P5JswrapperResponse(TypedDict):
    success: bool
    data: Optional[Any]
    metadata: P5JswrapperMetadata
    links: Optional[Dict[str, str]]
    errors: Optional[List[P5JswrapperError]]

# Skill interface
class P5JswrapperSkill:
    async def call(self, request: P5JswrapperRequest) -> P5JswrapperResponse: ...

# Error codes (from manifest)
P5JSWRAPPER_ERROR_CODES = [
    "AUTH_EXPIRED",
    "RATE_LIMITED",
    "NOT_FOUND",
    "VALIDATION_ERROR",
    "UPSTREAM_ERROR",
    "TIMEOUT",
    "PERMISSION_DENIED",
    # Add skill-specific codes here
]
