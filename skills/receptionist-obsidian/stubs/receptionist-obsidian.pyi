"""
Auto-generated Python stubs for receptionist-obsidian
Generated from skill.yaml — DO NOT EDIT MANUALLY
Run: python scripts/generate_interfaces.py
"""

from typing import Any, Dict, List, Literal, Optional, TypedDict, Union

class ReceptionistobsidianContext(TypedDict):
    run_id: str
    agent_id: str
    trace_id: str
    priority: Literal["normal", "high", "low"]
    timeout_ms: Optional[int]

class ReceptionistobsidianRequest(TypedDict):
    action: str
    resource: str
    params: Dict[str, Any]
    context: ReceptionistobsidianContext

class ReceptionistobsidianMetadata(TypedDict):
    request_id: str
    timestamp: str
    duration_ms: int
    rate_limit_remaining: int
    rate_limit_reset: str
    cache_hit: bool
    pagination: Optional[Dict[str, int]]

class ReceptionistobsidianError(TypedDict):
    code: str
    message: str
    details: Optional[Dict[str, Any]]
    recovery_hint: Optional[Literal["refresh_token", "backoff_retry", "check_permissions", "contact_admin"]]

class ReceptionistobsidianResponse(TypedDict):
    success: bool
    data: Optional[Any]
    metadata: ReceptionistobsidianMetadata
    links: Optional[Dict[str, str]]
    errors: Optional[List[ReceptionistobsidianError]]

# Skill interface
class ReceptionistobsidianSkill:
    async def call(self, request: ReceptionistobsidianRequest) -> ReceptionistobsidianResponse: ...

# Error codes (from manifest)
RECEPTIONISTOBSIDIAN_ERROR_CODES = [
    "AUTH_EXPIRED",
    "RATE_LIMITED",
    "NOT_FOUND",
    "VALIDATION_ERROR",
    "UPSTREAM_ERROR",
    "TIMEOUT",
    "PERMISSION_DENIED",
    # Add skill-specific codes here
]
