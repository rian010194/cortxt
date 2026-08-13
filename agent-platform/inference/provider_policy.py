"""Deterministic provider-assurance policy for Cortxt."""
from dataclasses import dataclass
from enum import Enum

class DataClass(str, Enum):
    L0 = "L0"; L1 = "L1"; L2 = "L2"; L3 = "L3"

class AssuranceStatus(str, Enum):
    NONE = "none"; IN_PROGRESS = "in_progress"; COMPLETED = "completed"

@dataclass(frozen=True)
class ProviderEvidence:
    provider_id: str
    approved: bool
    zero_data_retention: bool = False
    encryption: bool = False
    dpa: bool = False
    subprocessors_published: bool = False
    hosting_region_published: bool = False
    incident_process_published: bool = False
    independent_assurance: AssuranceStatus = AssuranceStatus.NONE

@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    data_class: str
    provider_id: str
    reasons: tuple[str, ...]

_REQUIREMENTS = {
    DataClass.L0: ("approved",),
    DataClass.L1: ("approved", "zero_data_retention", "encryption"),
    DataClass.L2: ("approved", "zero_data_retention", "encryption", "dpa",
                   "subprocessors_published", "hosting_region_published",
                   "incident_process_published"),
}

def evaluate_provider(data_class: str, evidence: ProviderEvidence | None) -> PolicyDecision:
    """Return a fail-closed, machine-readable provider eligibility decision."""
    provider_id = evidence.provider_id if evidence else "unknown"
    try:
        level = DataClass(data_class)
    except (TypeError, ValueError):
        return PolicyDecision(False, str(data_class), provider_id, ("unknown_data_class",))
    if evidence is None or not evidence.provider_id.strip():
        return PolicyDecision(False, level.value, provider_id, ("missing_provider_evidence",))
    if level is DataClass.L3:
        return PolicyDecision(False, level.value, provider_id, ("l3_policy_not_defined",))
    missing = tuple(f"missing_{field}" for field in _REQUIREMENTS[level]
                    if not getattr(evidence, field))
    if level is DataClass.L2 and evidence.independent_assurance is not AssuranceStatus.COMPLETED:
        missing += ("independent_assurance_not_completed",)
    if missing:
        return PolicyDecision(False, level.value, provider_id, missing)
    return PolicyDecision(True, level.value, provider_id, ("requirements_satisfied",))
