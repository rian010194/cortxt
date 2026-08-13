"""
Auto-generated Python stubs for excalidraw-wrapper
Generated from skill.yaml — DO NOT EDIT MANUALLY
Run: python scripts/generate_interfaces.py
"""

from typing import Any, Dict, List, Literal, Optional, TypedDict, Union

class ExcalidrawwrapperContext(TypedDict):
    run_id: str
    agent_id: str
    trace_id: str
    priority: Literal["normal", "high", "low"]
    timeout_ms: Optional[int]

class ExcalidrawwrapperRequest(TypedDict):
    action: str
    resource: str
    params: Dict[str, Any]
    context: ExcalidrawwrapperContext

class ExcalidrawwrapperMetadata(TypedDict):
    request_id: str
    timestamp: str
    duration_ms: int
    rate_limit_remaining: int
    rate_limit_reset: str
    cache_hit: bool
    pagination: Optional[Dict[str, int]]

class ExcalidrawwrapperError(TypedDict):
    code: str
    message: str
    details: Optional[Dict[str, Any]]
    recovery_hint: Optional[Literal["refresh_token", "backoff_retry", "check_permissions", "contact_admin"]]

class ExcalidrawwrapperResponse(TypedDict):
    success: bool
    data: Optional[Any]
    metadata: ExcalidrawwrapperMetadata
    links: Optional[Dict[str, str]]
    errors: Optional[List[ExcalidrawwrapperError]]

# Skill interface
class ExcalidrawwrapperSkill:
    async def call(self, request: ExcalidrawwrapperRequest) -> ExcalidrawwrapperResponse: ...

# Error codes (from manifest)
EXCALIDRAWWRAPPER_ERROR_CODES = [
    "AUTH_EXPIRED",
    "RATE_LIMITED",
    "NOT_FOUND",
    "VALIDATION_ERROR",
    "UPSTREAM_ERROR",
    "TIMEOUT",
    "PERMISSION_DENIED",
    # Add skill-specific codes here
]
