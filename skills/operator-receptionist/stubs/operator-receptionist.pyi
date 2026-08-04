from typing import TypedDict, Literal, List, Optional

class OperatorRequest(TypedDict):
    intent: str
    language: Optional[Literal["sv", "en"]]
    urgency: Optional[Literal["low", "normal", "high"]]

class Budget(TypedDict):
    max_runtime_seconds: int
    max_cost_usd: float

class IssuePlan(TypedDict):
    title: str
    scope: str
    acceptance_criteria: List[str]
    budget: Budget
    worker_role: Literal["researcher", "builder", "reviewer"]
    model: str
    provider: str

class DispatchResult(TypedDict):
    issue_id: int
    issue_url: str
    run_id: str
    status: Literal["succeeded", "failed", "blocked", "cancelled"]
    worker_role: str
    model: str
    cost_usd: float
    duration_seconds: int
    artifacts: List[str]
    evidence: str

def parse_intent(request: OperatorRequest) -> IssuePlan: ...
def dispatch(plan: IssuePlan) -> DispatchResult: ...
